"""Task-based model routing.

The old design ran one 24B for everything and paid ~2.2 tok/s for it, which is
about five minutes for a long answer. Nothing in the interface can compensate
for that. This replaces it with several smaller specialists and a rule for
which one answers.

Reuses ``protege.models`` for the backend protocol and the llama.cpp binding —
that layer was already written so nothing above it knows llama.cpp exists, and
that property is worth keeping.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator

from protege.models.base import ModelBackend, ModelSpec, ModelUnavailable, Role

from .config import AppConfig, ModelConfig


class Route(Enum):
    """What a request is *for*, not which model answers it.

    Callers name the job; the router decides what runs. That indirection is the
    whole point — swapping which file serves ``CODE`` must not require touching
    anything that asks for code.
    """

    CHAT = "chat"
    """Everyday conversation. The default."""

    CODE = "code"
    """Generating, editing and reviewing code."""

    FAST = "fast"
    """Titles, classification, routing decisions. On the latency path, so this
    one is expected to stay resident."""

    DEEP = "deep"
    """Hard reasoning and long documents. Where a cloud model would be used, if
    one is enabled."""

    @classmethod
    def parse(cls, name: str) -> "Route":
        try:
            return cls(name)
        except ValueError:
            return cls.CHAT


#: Routes that load a large model. At most one of these is resident at a time.
HEAVY = (Route.CHAT, Route.CODE, Route.DEEP)

#: Above this, a model is treated as large enough that a second one alongside it
#: would push this machine into swap. 15.7 GB total, and Windows wants several.
HEAVY_BYTES = 4 * 1024**3


@dataclass(frozen=True)
class RouteStatus:
    """What the interface needs to say about a route without loading it."""

    route: Route
    configured: bool
    file_present: bool
    loaded: bool
    label: str
    detail: str

    @property
    def usable(self) -> bool:
        return self.configured and self.file_present


class ModelRouter:
    """Owns the loaded models and decides which one serves a request.

    Safe to call from a worker thread. Loading and unloading are serialised,
    because two threads racing to load a 5 GB model would try to allocate it
    twice — and so is generation itself, one at a time across the process.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._backends: dict[Route, ModelBackend] = {}
        # Guards the table of loaded backends. Held briefly.
        self._lock = threading.RLock()
        # Held for the whole of a generation, so only one runs at a time
        # across the process. llama.cpp is not safe to call from two threads
        # at once, and evicting a model another thread is still generating on
        # frees memory it is reading: a native crash, not an exception. While
        # only the chat turn generated this could not happen; once a scheduled
        # agent can run while a turn streams, it is load-bearing.
        # Always taken before `_lock`, never after.
        self._inference = threading.Lock()
        # Models whose file changed while something was generating. The next
        # `acquire` unloads them; it holds `_inference`, so it cannot race one.
        self._stale: set[Route] = set()

    # -- configuration ------------------------------------------------------

    def update(self, config: AppConfig) -> None:
        """Adopt new settings, dropping any model whose path changed.

        Comparing paths rather than unloading everything means changing the
        temperature does not cost a five-second reload.
        """
        with self._lock:
            for route in list(self._backends):
                before = self._model_config(route, self._config)
                after = self._model_config(route, config)
                if before.path != after.path:
                    self._stale.add(route)
            self._config = config
        # Free them now if nothing is generating. If something is, the next
        # `acquire` does it: this runs on the UI thread, which must never wait
        # out somebody else's generation.
        if self._inference.acquire(blocking=False):
            try:
                with self._lock:
                    self._drain_stale()
            finally:
                self._inference.release()

    def _model_config(self, route: Route, config: AppConfig | None = None) -> ModelConfig:
        cfg = config if config is not None else self._config
        return cfg.models.get(route.value, ModelConfig())

    def spec_for(self, route: Route) -> ModelSpec | None:
        """The spec that would be loaded for \a route, or None if unconfigured."""
        model = self._model_config(route)
        if not model.configured:
            return None
        return ModelSpec(
            path=model.path,
            # Vestigial. ModelSpec.role dates from the MAIN/AUDITOR pairing the
            # lock system needed, and LlamaBackend now reads it only to name
            # itself in error messages.
            role=Role.MAIN,
            n_ctx=model.n_ctx,
            n_gpu_layers=model.n_gpu_layers,
            n_threads=model.n_threads,
        )

    # -- resolution ---------------------------------------------------------

    def resolve(self, route: Route) -> Route:
        """The route that will actually serve \a route.

        Falls back rather than failing: an unconfigured ``CODE`` route should
        answer with the chat model, not refuse. Routing is an optimisation, and
        an optimisation that turns into an error when it cannot be applied is a
        worse deal than not having it.
        """
        if self._model_config(route).exists:
            return route

        order = [Route.parse(self._config.default_route), Route.CHAT, Route.DEEP, Route.FAST]
        for candidate in order:
            if candidate is not route and self._model_config(candidate).exists:
                return candidate
        return route

    # -- loading ------------------------------------------------------------

    def _unload(self, route: Route) -> None:
        backend = self._backends.pop(route, None)
        if backend is not None:
            backend.close()

    def _drain_stale(self) -> None:
        """Unload the models whose file changed. The caller holds both locks."""
        for route in list(self._stale):
            self._unload(route)
        self._stale.clear()

    def _evict_for(self, route: Route) -> None:
        """Free room before loading a large model.

        The rule is one heavy model resident at a time. FAST is exempt: it is
        small enough to coexist and it is on the interaction path, so paying a
        reload for every title generation would be worse than the memory.
        """
        if route not in HEAVY:
            return
        for other in list(self._backends):
            if other in HEAVY and other is not route:
                self._unload(other)

    @staticmethod
    def _backend_module():
        """Import the llama.cpp binding, and not one moment sooner.

        `protege.models.llama_backend` does `import llama_cpp` at module scope,
        which maps llama.dll and the CUDA 12 runtime into the process — several
        hundred megabytes, before a single model is loaded. Deferring it to the
        first actual load keeps startup fast and keeps every part of the app
        that never runs inference free of it entirely.
        """
        from protege.models import llama_backend

        return llama_backend

    def _load(self, route: Route) -> ModelBackend:
        spec = self.spec_for(route)
        if spec is None:
            raise ModelUnavailable(
                f"No model is configured for the {route.value!r} route."
            )
        llama = self._backend_module()
        if not llama.library_available():
            raise ModelUnavailable(
                "llama-cpp-python is not installed, so no local model can run."
            )
        self._evict_for(route)
        backend = llama.LlamaBackend(spec)
        self._backends[route] = backend
        return backend

    @contextmanager
    def acquire(self, route: Route) -> Iterator[ModelBackend]:
        """Yield a loaded backend for \a route, loading it if needed.

        The backend stays resident afterwards. Unloading on every use would
        make each turn pay the load cost, which for a 5 GB file is several
        seconds before a single token appears.

        Only one caller is inside at a time, across the whole process. The
        rest wait here: a scheduled agent queues behind a streaming chat turn
        rather than generating over it. Keep the block to the generation.
        """
        resolved = self.resolve(route)
        with self._inference:
            with self._lock:
                self._drain_stale()
                backend = self._backends.get(resolved)
                if backend is None or not backend.is_loaded:
                    backend = self._load(resolved)
            yield backend

    def warm(self, route: Route) -> bool:
        """Load  route now, reporting success rather than raising.

        For startup preloading, where a failure is not worth interrupting
        anyone over: the model will be tried again, loudly, on the first
        message. Returns whether it loaded.
        """
        try:
            with self.acquire(route):
                return True
        except (ModelUnavailable, OSError, RuntimeError):
            return False

    def unload_all(self, timeout: float = 30.0) -> bool:
        """Unload everything, once any running generation has finished.

        Returns False, unloading nothing, if one is still running after
        \a timeout. Freeing a model mid-generation crashes the process, and an
        exiting process gets its memory back regardless, so waiting and then
        declining is the safe order.
        """
        if not self._inference.acquire(timeout=timeout):
            return False
        try:
            with self._lock:
                for route in list(self._backends):
                    self._unload(route)
                self._stale.clear()
        finally:
            self._inference.release()
        return True

    def close(self) -> None:
        self.unload_all()

    # -- reporting ----------------------------------------------------------

    def status(self, route: Route) -> RouteStatus:
        model = self._model_config(route)
        path = Path(model.path) if model.path else None
        present = model.exists

        if not model.configured:
            detail = "not configured"
        elif not present:
            detail = "file missing"
        else:
            size = path.stat().st_size / 1024**3 if path else 0.0
            detail = f"{size:.1f} GB"

        return RouteStatus(
            route=route,
            configured=model.configured,
            file_present=present,
            loaded=route in self._backends,
            label=path.stem if path else "—",
            detail=detail,
        )

    def statuses(self) -> list[RouteStatus]:
        return [self.status(route) for route in Route]

    @property
    def any_usable(self) -> bool:
        return any(self._model_config(r).exists for r in Route)
