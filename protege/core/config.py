"""Application configuration.

Small on purpose. This holds what the *application* needs to start — which
models exist, which appearance you chose — and nothing that belongs to a
project. Project state lives with the project.

Stored outside the repository so a checkout can be replaced without taking your
settings with it, and written atomically so an interrupted save cannot leave a
truncated JSON file that fails to parse on next launch.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Where GGUF files are looked for when no explicit path is configured.
MODELS_DIR = REPO_ROOT / "models"


def config_dir() -> Path:
    """Per-user configuration directory.

    ``LOCALAPPDATA`` rather than ``APPDATA`` on Windows: this is machine-local
    state — model paths that mean nothing on another machine — and roaming it
    onto a domain profile would be wrong.
    """
    base = os.environ.get("PROTEGE_CONFIG_DIR")
    if base:
        return Path(base)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Protege"
    return Path.home() / ".config" / "protege"


@dataclass
class ModelConfig:
    """One routable model."""

    path: str = ""
    n_ctx: int = 8192
    #: -1 offloads every layer the GPU will take. Lower it only when a model
    #: does not fit; on this machine the counter-intuitive result is that
    #: offloading *more* reduces system-RAM pressure, because llama.cpp keeps
    #: whatever is not offloaded in host memory.
    n_gpu_layers: int = -1
    n_threads: int = 0
    temperature: float = 0.7
    top_p: float = 0.95
    max_tokens: int = 1024

    @property
    def configured(self) -> bool:
        return bool(self.path)

    @property
    def exists(self) -> bool:
        return self.configured and Path(self.path).is_file()


@dataclass
class AppConfig:
    """Everything the application reads at startup."""

    #: "auto" | "dark" | "light"
    appearance: str = "auto"
    reduce_motion: bool = False

    #: Route name -> model. See core.models.Route for what each is for.
    models: dict[str, ModelConfig] = field(default_factory=dict)

    #: Route used when nothing more specific applies.
    default_route: str = "chat"

    #: Load the default model in the background at startup.
    #:
    #: Measured on this machine: a cold first message waits 6.3 s before its
    #: first token; a warm one waits 0.14 s. Paying that once, invisibly, while
    #: the window is already up is worth ~5.8 GB of VRAM sitting occupied — the
    #: card is otherwise idle, since the display runs on the iGPU. Turn it off
    #: if you want the GPU free for something else.
    preload: bool = True

    # -- persistence --------------------------------------------------------

    @staticmethod
    def path() -> Path:
        return config_dir() / "config.json"

    @classmethod
    def load(cls) -> "AppConfig":
        """Read config, falling back to defaults on anything unreadable.

        A corrupt config must not stop the application starting. Losing your
        appearance preference is an annoyance; refusing to launch over it is a
        bug.
        """
        target = cls.path()
        if not target.is_file():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls.from_dict(raw if isinstance(raw, dict) else {})

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppConfig":
        known = {f.name for f in fields(ModelConfig)}
        models: dict[str, ModelConfig] = {}
        for name, entry in (raw.get("models") or {}).items():
            if isinstance(entry, dict):
                models[str(name)] = ModelConfig(
                    **{k: v for k, v in entry.items() if k in known}
                )

        return cls(
            appearance=str(raw.get("appearance", "auto")),
            reduce_motion=bool(raw.get("reduce_motion", False)),
            models=models,
            default_route=str(raw.get("default_route", "chat")),
            preload=bool(raw.get("preload", True)),
        )

    def save(self) -> None:
        """Write atomically: temp file in the same directory, then replace.

        Same directory because ``os.replace`` is only atomic within a
        filesystem, and the temp directory is frequently on another volume.
        """
        target = self.path()
        target.parent.mkdir(parents=True, exist_ok=True)

        handle, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=".config-", suffix=".tmp"
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                json.dump(asdict(self), fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise


def discover_models(directory: Path | None = None) -> list[Path]:
    """Every GGUF in \a directory, largest last.

    Sorted by size because that is the axis that matters here: the smallest
    file present is the one most likely to be usable for the low-latency route,
    and the largest is the one most likely to exhaust 15.7 GB of RAM.
    """
    target = directory if directory is not None else MODELS_DIR
    if not target.is_dir():
        return []
    found = [p for p in target.glob("*.gguf") if p.is_file() and _looks_like_gguf(p)]
    return sorted(found, key=lambda p: p.stat().st_size)


#: Every GGUF file begins with these four bytes.
_GGUF_MAGIC = b"GGUF"

#: Nothing smaller than this is a usable model, so anything under it is junk
#: or a download that barely started.
#:
#: This does NOT reliably catch a download in flight. A half-fetched file is a
#: real .gguf with a valid header and, once past this floor, looks exactly like
#: a small model. The fix for that is on the writing side: fetch to a .part name
#: and rename on completion, which `tools/fetch_model.py` does.
_MIN_MODEL_BYTES = 100 * 1024 * 1024


def _looks_like_gguf(path: Path) -> bool:
    """Cheap sanity check on a candidate model file.

    Reads four bytes rather than trusting the extension. Renaming something to
    .gguf should not be enough to have Protégé try to load it as weights.
    """
    try:
        if path.stat().st_size < _MIN_MODEL_BYTES:
            return False
        with path.open("rb") as fh:
            return fh.read(4) == _GGUF_MAGIC
    except OSError:
        return False


#: Layers to offload when a model is too large to fit the 6 GB card whole.
#: Measured: 24 layers of a 24B Q4_K_M sits at 5787/6144 MiB, which leaves just
#: enough for the KV cache. 30 layers does not.
_PARTIAL_OFFLOAD_LAYERS = 24

#: Above this a GGUF will not fit entirely in 6 GB of VRAM alongside a usable
#: KV cache.
_FITS_ON_GPU_BYTES = 5 * 1024**3

#: Below this a model is small enough to co-exist with a large one, which is
#: what the low-latency route needs.
_SMALL_MODEL_BYTES = 2.5 * 1024**3

#: Context sizes, chosen from measurements on this machine (RTX 3060 Laptop,
#: 6144 MiB, display driven by the iGPU so the card is entirely free):
#:
#:   Qwen2.5-Coder-7B Q4_K_M  4.36 GB   16384 ctx -> 5700 MiB, 36.9 tok/s
#:   Qwen3-8B         Q4_K_M  4.68 GB    8192 ctx -> 5800 MiB, 32.0 tok/s
#:                                       4096 ctx -> 5435 MiB, 30.5 tok/s
#:
#: The threshold sits between those two file sizes because that is where the
#: measurement put it, not because 4.5 GB is a round number. A larger model
#: spends its remaining headroom on weights, so it gets less context.
_ROOMY_MODEL_BYTES = 4.5 * 1024**3
_ROOMY_CONTEXT = 16384
_TIGHT_CONTEXT = 8192
_SPILLED_CONTEXT = 4096


def _is_coder(path: Path) -> bool:
    """Whether a filename says the model is code-tuned.

    Filename rather than GGUF metadata: `general.name` is set by whoever ran
    the conversion and is frequently blank or wrong in community quants, while
    nobody renames a model file to hide what it is.
    """
    name = path.name.lower()
    return "coder" in name or "-code-" in name or name.startswith("code")


def _plan_for(path: Path) -> ModelConfig:
    """The configuration this file should run with on this machine."""
    size = path.stat().st_size

    if size > _FITS_ON_GPU_BYTES:
        # Does not fit whole. Offloaded partially rather than refused —
        # counter-intuitively, offloading *more* lowers system-RAM pressure,
        # because llama.cpp keeps whatever is not offloaded in host memory.
        return ModelConfig(
            path=str(path),
            n_ctx=_SPILLED_CONTEXT,
            n_gpu_layers=_PARTIAL_OFFLOAD_LAYERS,
        )

    context = _ROOMY_CONTEXT if size <= _ROOMY_MODEL_BYTES else _TIGHT_CONTEXT
    config = ModelConfig(path=str(path), n_ctx=context, n_gpu_layers=-1)

    if _is_coder(path):
        # Code wants to be reproducible far more than it wants to be
        # interesting, and a coding answer is usually longer than a chat one.
        return replace(config, temperature=0.3, top_p=0.9, max_tokens=2048)
    return config


def plan_routes(paths: list[Path]) -> dict[str, ModelConfig]:
    """Decide which discovered model serves which route.

    Kept separate from `autoconfigure` so the decision can be tested without
    touching a config file or the filesystem layout.
    """
    if not paths:
        return {}

    coders = [p for p in paths if _is_coder(p)]
    generals = [p for p in paths if not _is_coder(p)]
    small = [p for p in paths if p.stat().st_size <= _SMALL_MODEL_BYTES]

    def best_general() -> Path | None:
        """Largest model that still fits entirely on the card, else the largest.

        Fitting matters more than parameter count: a model that spills to host
        memory runs at a fraction of the speed, and on this machine that is the
        difference between 32 tok/s and 2.
        """
        fits = [p for p in generals if p.stat().st_size <= _FITS_ON_GPU_BYTES]
        pool = fits or generals
        return max(pool, key=lambda p: p.stat().st_size) if pool else None

    plan: dict[str, ModelConfig] = {}

    chat = best_general()
    if chat is not None:
        plan["chat"] = _plan_for(chat)

    # A coder if there is one; otherwise the chat model answers code questions
    # too, which is worse but not broken.
    code = max(coders, key=lambda p: p.stat().st_size) if coders else chat
    if code is not None:
        plan["code"] = _plan_for(code)

    # Only worth a separate entry when there is genuinely a smaller file. Two
    # routes pointing at one 5 GB model is not a fast path.
    smallest = min(small, key=lambda p: p.stat().st_size) if small else None
    if smallest is not None and smallest not in (chat, code):
        plan["fast"] = _plan_for(smallest)

    return plan


def autoconfigure(config: AppConfig, directory: Path | None = None) -> bool:
    """Fill in missing model routes from whatever GGUFs are on disk.

    Runs on every launch so that dropping a file into ``models/`` is all it
    takes to start using it. Only ever *adds*: a route the user has set is
    never overwritten, because a helpful default that silently undoes a
    deliberate choice is worse than no default.

    Returns whether anything changed.
    """
    changed = False
    for route, planned in plan_routes(discover_models(directory)).items():
        existing = config.models.get(route)
        if existing is not None and existing.configured:
            continue
        config.models[route] = planned
        changed = True
    return changed
