"""Turn orchestration.

Sits between the UI and the model layer. The UI never talks to a backend
directly; it hands text to a `Responder` and gets a `Turn` back.

The indirection exists so the lock pipeline can be inserted without the UI
changing. `DirectResponder` runs Layers 1-2 only and is what the early build
stages use; `pipeline.PipelineResponder` runs all five and is what ships. Both
satisfy the same protocol, so there is exactly one code path in the UI and no
`if locked_enabled` branch anywhere in it -- a branch like that is how a
disabled layer turns into an unlocked assistant.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

from .models import ChatMessage, GenerationResult, ModelManager, Role


@dataclass(frozen=True)
class BlockDetail:
    """Why a response was withheld.

    Surfaced in the UI behind an expander. The user needs to be able to see
    which layer fired and on what, because Layer 4 produces false positives by
    design and an unexplained block is indistinguishable from a broken app.
    """

    layer: str  # "directive" | "retrieval" | "tripwires" | "auditor" | "error"
    topic: str = ""
    reason: str = ""
    evidence: str = ""
    raw_verdict: str = ""

    def summary(self) -> str:
        parts = [f"Layer: {self.layer}"]
        if self.topic:
            parts.append(f"Topic: {self.topic}")
        if self.reason:
            parts.append(f"Reason: {self.reason}")
        if self.evidence:
            parts.append(f"Evidence: {self.evidence}")
        if self.raw_verdict:
            parts.append(f"Auditor said: {self.raw_verdict}")
        return "\n".join(parts)


@dataclass(frozen=True)
class Turn:
    """One exchange, after gating."""

    user_text: str
    text: str
    blocked: bool = False
    detail: BlockDetail | None = None
    system_prompt: str = ""
    draft: str = ""
    duration_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    budget_note: str = ""
    # Pre-rendered text for the assembled-prompt viewer. Held as a string
    # rather than an AssembledContext so that `chat` stays free of any import
    # from `context.assembly`, which imports this module.
    prompt_view: str = ""
    notices: tuple[str, ...] = ()

    @property
    def display_text(self) -> str:
        return self.text


class TurnCancelled(Exception):
    """Raised out of a streaming callback to abandon a turn in progress.

    A generation on a 24B takes minutes, and watching an answer you already
    know is wrong crawl out with no way to stop it is the worst thing about
    using the application. There is no way to kill a thread in Python, so
    cancellation is cooperative: the UI sets a flag, the token and stage
    callbacks raise this, and llama.cpp's stream unwinds through the `finally`
    that closes it.

    Cancellation between phases works the same way -- `on_stage` fires before
    each layer, so pressing Stop while MAIN is streaming aborts before the
    auditor is ever asked. Only a generation already inside the auditor has to
    run to completion, and its result is discarded on arrival.
    """


@dataclass
class Conversation:
    """Recent turns, in model-message form.

    Deliberately not the transcript of record -- that is the session file under
    `memory/`. This is only what gets replayed into context.
    """

    messages: list[ChatMessage] = field(default_factory=list)

    def add_user(self, text: str) -> None:
        self.messages.append(ChatMessage(role="user", content=text))

    def add_assistant(self, text: str) -> None:
        self.messages.append(ChatMessage(role="assistant", content=text))

    def tail(self, limit: int) -> list[ChatMessage]:
        return self.messages[-limit:] if limit > 0 else []

    def drop_last_assistant(self) -> None:
        """Remove the most recent assistant turn.

        Used by the personality live preview, which regenerates the last
        response under new settings without committing them.
        """
        for index in range(len(self.messages) - 1, -1, -1):
            if self.messages[index].role == "assistant":
                del self.messages[index]
                return


class Responder(Protocol):
    """Turns user text into a gated `Turn`."""

    def respond(
        self,
        user_text: str,
        conversation: Conversation,
        *,
        on_token: Callable[[str], None] | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> Turn: ...


class DirectResponder:
    """Layers 1-2 only: manifest-derived directive, then MAIN.

    Not the shipping configuration. It is the build-order stage where the
    directive exists but retrieval, tripwires, and the auditor do not, and it is
    kept afterwards because it is the honest baseline the adversarial tests
    measure against -- the leak rate of the directive alone is what justifies
    the other three layers existing.
    """

    def __init__(self, manager: ModelManager, settings, manifest) -> None:
        self._manager = manager
        self._settings = settings
        self._manifest = manifest

    def _system_prompt(self) -> str:
        from .lock.directive import build_directive

        directive = build_directive(self._manifest.unlocked_topics)
        # The user's own prompt first, the directive last. Order is the point:
        # see the module docstring in lock/directive.py.
        parts = [p for p in (self._settings.system_prompt.strip(), directive.text) if p]
        return "\n\n".join(parts)

    def respond(
        self,
        user_text: str,
        conversation: Conversation,
        *,
        on_token: Callable[[str], None] | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> Turn:
        started = time.monotonic()
        system_prompt = self._system_prompt()
        messages: list[ChatMessage] = [ChatMessage(role="system", content=system_prompt)]
        messages.extend(conversation.tail(20))
        messages.append(ChatMessage(role="user", content=user_text))

        if on_stage:
            on_stage("generating")

        models = self._settings.models
        with self._manager.acquire(Role.MAIN) as backend:
            result: GenerationResult = backend.generate(
                messages,
                max_tokens=models.max_tokens,
                temperature=models.temperature,
                top_p=models.top_p,
                on_token=on_token,
            )

        return Turn(
            user_text=user_text,
            text=result.text.strip(),
            system_prompt=system_prompt,
            draft=result.text,
            duration_s=time.monotonic() - started,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )


def blocked_turn(user_text: str, detail: BlockDetail, *, draft: str = "", system_prompt: str = "") -> Turn:
    """Construct the response the user actually sees when a layer fires.

    The visible text is only the marker. The draft is retained on the Turn for
    the block inspector but never rendered inline -- showing a blocked draft
    alongside its block notice would defeat the block.
    """
    from .lock.directive import decline_for

    return Turn(
        user_text=user_text,
        text=decline_for(detail.topic or "unknown"),
        blocked=True,
        detail=detail,
        draft=draft,
        system_prompt=system_prompt,
    )


def conversation_from(messages: Sequence[ChatMessage]) -> Conversation:
    return Conversation(messages=list(messages))
