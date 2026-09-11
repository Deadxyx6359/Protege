"""The model abstraction.

The brief is explicit that the base model is a replaceable component. Nothing
above this layer may know that llama.cpp exists: the lock pipeline, the context
assembler, and the UI all speak only to `ModelBackend`.

That is not architectural decoration. The auditor's whole justification is that
it reads MAIN's output in the same dialect it was written in, which is a claim
about a *pairing* of models. When the pairing changes -- and for this project it
already has, since Ministral 3B's weights were never published -- the swap has
to be a config change, not a rewrite.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Sequence


class Role(Enum):
    """Which of the two models a backend is filling.

    MAIN is the protege and is the only model the user ever reads. AUDITOR never
    speaks to the user; it emits structured verdicts only, and its raw text is
    surfaced only in the block-detail inspector.
    """

    MAIN = "main"
    AUDITOR = "auditor"


class ModelError(RuntimeError):
    """Base for every failure originating in the model layer."""


class ModelUnavailable(ModelError):
    """The backend could not be loaded: missing file, missing library, no memory.

    Callers in the lock pipeline must treat this as a BLOCK, never as a PASS.
    A model that failed to load has not cleared anything.
    """


class GenerationTimeout(ModelError):
    """Generation exceeded its deadline.

    For the auditor this maps directly to BLOCK. A verdict that did not arrive
    is not a passing verdict.
    """


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str

    VALID_ROLES = ("system", "user", "assistant")

    def __post_init__(self) -> None:
        if self.role not in self.VALID_ROLES:
            raise ValueError(f"role must be one of {self.VALID_ROLES}, got {self.role!r}")

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class GenerationResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stop_reason: str = "stop"  # "stop" | "length" | "timeout"
    duration_s: float = 0.0

    @property
    def truncated(self) -> bool:
        """True when the model was cut off mid-thought.

        Worth surfacing: a truncated draft that the auditor then passes is only
        cleared up to the point it was cut, and the user sees an incomplete
        answer with no indication why.
        """
        return self.stop_reason == "length"


@dataclass(frozen=True)
class ModelSpec:
    """Everything needed to instantiate one model."""

    path: str
    role: Role
    n_ctx: int = 4096
    n_gpu_layers: int = -1
    n_threads: int = 0
    seed: int = -1

    @property
    def label(self) -> str:
        from pathlib import Path

        return f"{self.role.value}:{Path(self.path).name or '<unset>'}"


class ModelBackend(ABC):
    """One loaded model.

    Implementations must be safe to call from a worker thread. `_lock` serializes
    generation because a llama.cpp context is not reentrant -- two concurrent
    completions on one context interleave their KV cache and produce garbage.
    Subclasses should hold it for the duration of any inference call.
    """

    def __init__(self, spec: ModelSpec) -> None:
        self.spec = spec
        self._lock = threading.RLock()

    @property
    def role(self) -> Role:
        return self.spec.role

    @property
    def label(self) -> str:
        return self.spec.label

    @property
    @abstractmethod
    def is_loaded(self) -> bool: ...

    @property
    @abstractmethod
    def n_ctx(self) -> int: ...

    @abstractmethod
    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop: Sequence[str] = (),
        deadline: float | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> GenerationResult:
        """Run a chat completion.

        `deadline` is an absolute `time.monotonic()` value, not a duration, so
        that a budget can be threaded through several calls without drift.
        Implementations must raise `GenerationTimeout` rather than returning
        partial text when it passes -- the auditor's contract depends on being
        unable to mistake a truncated verdict for a complete one.

        `on_token` receives incremental text for UI streaming. It is called from
        the worker thread; Tk callers must marshal back to the main thread.
        """

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Token count using this model's own tokenizer.

        Context budgeting is only meaningful against the tokenizer that will
        actually encode the prompt. A shared heuristic across differing
        tokenizers is how a budget silently overflows.
        """

    @abstractmethod
    def close(self) -> None:
        """Release the model and its memory. Must be idempotent."""

    def __enter__(self) -> "ModelBackend":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def deadline_from(timeout_s: float | None) -> float | None:
    """Convert a duration into an absolute monotonic deadline."""
    if timeout_s is None:
        return None
    return time.monotonic() + timeout_s


@dataclass
class GenerationStats:
    """Rolling counters for the status line."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_seconds: float = 0.0
    timeouts: int = 0
    by_role: dict[str, int] = field(default_factory=dict)

    def record(self, role: Role, result: GenerationResult) -> None:
        self.calls += 1
        self.prompt_tokens += result.prompt_tokens
        self.completion_tokens += result.completion_tokens
        self.total_seconds += result.duration_s
        if result.stop_reason == "timeout":
            self.timeouts += 1
        self.by_role[role.value] = self.by_role.get(role.value, 0) + 1

    @property
    def tokens_per_second(self) -> float:
        if self.total_seconds <= 0:
            return 0.0
        return self.completion_tokens / self.total_seconds
