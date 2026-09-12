"""Loading, unloading, and handing out the MAIN and AUDITOR backends.

Three concerns live here.

**Memory.** The target box is an RTX 3060 with 12GB VRAM and 12GB of system
RAM. Both models fit in VRAM with context headroom; system RAM is the binding
constraint, because llama.cpp maps the GGUF into host memory during load
regardless of where the layers end up. `sequential` mode keeps exactly one model
resident, trading a load pause each turn for roughly 5GB of headroom.

**The shared-model case.** Ministral 3B Instruct 2410 was announced as a hosted
model; its weights were never published, so no GGUF exists. Pointing AUDITOR at
the same file as MAIN is therefore a first-class supported configuration, not a
degraded one -- and it preserves the actual argument for same-family pairing
better than any substitute would, since the auditor then reads MAIN's output in
literally the same dialect. When both paths match, one backend is loaded and
shared. Cost is a slower audit pass; benefit is 5GB not spent twice.

**Serialization.** llama.cpp contexts are not reentrant. Every handout goes
through a lock.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from ..schemas import Settings
from .base import ModelBackend, ModelSpec, ModelUnavailable, Role

BackendFactory = Callable[[ModelSpec], ModelBackend]


@dataclass(frozen=True)
class ModelStatus:
    """What the status line and Settings show about the model layer."""

    main_configured: bool
    auditor_configured: bool
    main_loaded: bool
    auditor_loaded: bool
    shared: bool
    loading_mode: str
    library_available: bool
    detail: str = ""

    @property
    def ready(self) -> bool:
        """True when a chat turn can actually complete.

        Requires MAIN *and* AUDITOR. An unconfigured auditor is not a reduced
        capability -- it means Layer 5 cannot run, and a layer that cannot run
        blocks. Reporting "ready" would promise a turn that will always end in
        a block.
        """
        return self.library_available and self.main_configured and self.auditor_configured


def _default_factory(spec: ModelSpec) -> ModelBackend:
    # Imported lazily so a missing llama-cpp-python surfaces as a readable
    # message in the UI instead of an ImportError traceback at startup. The
    # module is scanned directly by verify_offline via ENTRY_POINTS, so this
    # lazy import does not hide it from the offline check.
    #
    # The library check lives here rather than in ModelManager. The manager is
    # the model-agnostic layer; making it assert that a specific inference
    # library is installed would mean an injected backend -- a test double, or
    # a future non-llama.cpp runtime -- could not be used at all, which would
    # make "the base model is a replaceable component" false in practice.
    try:
        from .llama_backend import LlamaBackend
    except Exception as exc:  # noqa: BLE001 - a broken CUDA wheel raises OSError
        raise ModelUnavailable(
            "llama-cpp-python is not installed or failed to load, so no model can be loaded.\n"
            "Install it with:  pip install -r requirements.txt\n"
            "For GPU offload on an RTX 3060 you need a CUDA-enabled build -- see the README.\n"
            f"Underlying error: {exc}"
        ) from exc

    return LlamaBackend(spec)


def library_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
    except Exception:  # noqa: BLE001 - a broken CUDA wheel raises OSError, not ImportError
        return False
    return True


class ModelManager:
    """Owns both backends and their lifetimes.

    Not thread-safe to *construct* concurrently, but every method is safe to
    call from the UI thread and from the single generation worker.
    """

    def __init__(self, settings: Settings, factory: BackendFactory | None = None) -> None:
        self._settings = settings
        self._uses_default_factory = factory is None
        self._factory = factory or _default_factory
        self._backends: dict[Role, ModelBackend] = {}
        self._lock = threading.RLock()

    # -- configuration ------------------------------------------------------

    def update_settings(self, settings: Settings) -> None:
        """Apply new settings, unloading anything whose spec changed.

        Called when the user edits model paths or context length. Reloading
        eagerly here would block the Settings dialog for the length of a 5GB
        load; the next generation triggers it instead.
        """
        with self._lock:
            old = self._settings
            self._settings = settings
            if (
                old.models.main_path != settings.models.main_path
                or old.models.auditor_path != settings.models.auditor_path
                or old.models.main_ctx != settings.models.main_ctx
                or old.models.auditor_ctx != settings.models.auditor_ctx
                or old.models.n_gpu_layers != settings.models.n_gpu_layers
                or old.models.loading != settings.models.loading
            ):
                self.unload_all()

    def spec_for(self, role: Role) -> ModelSpec:
        models = self._settings.models
        if role is Role.MAIN:
            return ModelSpec(
                path=models.main_path,
                role=Role.MAIN,
                n_ctx=models.main_ctx,
                n_gpu_layers=models.n_gpu_layers,
                n_threads=models.n_threads,
                seed=models.seed,
            )
        return ModelSpec(
            path=models.auditor_path,
            role=Role.AUDITOR,
            n_ctx=models.auditor_ctx,
            n_gpu_layers=models.n_gpu_layers,
            n_threads=models.n_threads,
            seed=models.seed,
        )

    @property
    def shares_one_model(self) -> bool:
        """True when AUDITOR points at the same file as MAIN."""
        main = self._settings.models.main_path
        auditor = self._settings.models.auditor_path
        if not main or not auditor:
            return False
        return os.path.normcase(os.path.abspath(main)) == os.path.normcase(os.path.abspath(auditor))

    @property
    def sequential(self) -> bool:
        # A shared model is inherently sequential whatever the setting says:
        # there is one context and the lock serializes access to it. Reporting
        # "concurrent" would tell the user a second model is resident and that
        # roughly 5GB is spoken for, when neither is true.
        if self.shares_one_model:
            return True
        return self._settings.models.loading == "sequential"

    # -- lifetime -----------------------------------------------------------

    def _resolve_role(self, role: Role) -> Role:
        """Map AUDITOR onto MAIN when one file serves both."""
        if role is Role.AUDITOR and self.shares_one_model:
            return Role.MAIN
        return role

    def _load(self, role: Role) -> ModelBackend:
        spec = self.spec_for(role)
        if not spec.path:
            raise ModelUnavailable(
                f"No {role.value.upper()} model configured. Set the path in Settings -> Models."
            )
        return self._factory(spec)

    @contextmanager
    def acquire(self, role: Role) -> Iterator[ModelBackend]:
        """Hold a loaded backend for the duration of one inference call.

        In sequential mode the *other* model is unloaded first. The pipeline
        never nests acquisitions -- MAIN drafts, then the draft goes to
        AUDITOR -- so this cannot deadlock, and a nested acquire of the other
        role would raise rather than silently thrash 5GB in and out.
        """
        with self._lock:
            effective = self._resolve_role(role)
            if self.sequential:
                for other in (Role.MAIN, Role.AUDITOR):
                    if other is not effective and other in self._backends:
                        self._unload(other)
            backend = self._backends.get(effective)
            if backend is None or not backend.is_loaded:
                backend = self._load(effective)
                self._backends[effective] = backend
            yield backend

    def _unload(self, role: Role) -> None:
        backend = self._backends.pop(role, None)
        if backend is not None:
            backend.close()

    def unload_all(self) -> None:
        with self._lock:
            for role in list(self._backends):
                self._unload(role)

    def preload(self, role: Role) -> None:
        """Load ahead of the first turn, so the wait lands somewhere visible."""
        with self.acquire(role):
            pass

    # -- reporting ----------------------------------------------------------

    def status(self) -> ModelStatus:
        with self._lock:
            models = self._settings.models
            # An injected factory supplies its own backend, so the presence of
            # llama-cpp-python is irrelevant to whether this manager can load.
            available = library_available() if self._uses_default_factory else True
            detail = ""
            if not available:
                detail = "llama-cpp-python is not installed"
            elif not models.main_path:
                detail = "no MAIN model configured"
            elif not models.auditor_path:
                detail = "no AUDITOR model configured -- Layer 5 cannot run, so every response blocks"
            elif self.shares_one_model:
                detail = "AUDITOR shares MAIN's model file"
            return ModelStatus(
                main_configured=bool(models.main_path),
                auditor_configured=bool(models.auditor_path),
                main_loaded=Role.MAIN in self._backends,
                auditor_loaded=self._resolve_role(Role.AUDITOR) in self._backends,
                shared=self.shares_one_model,
                loading_mode="sequential" if self.sequential else "concurrent",
                library_available=available,
                detail=detail,
            )

    def close(self) -> None:
        self.unload_all()

    def __enter__(self) -> "ModelManager":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
