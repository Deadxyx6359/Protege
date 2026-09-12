"""A deterministic backend for tests.

**This is never wired into the UI.** There is no setting that selects it and no
code path from `run.py` that reaches it. That restriction matters more than it
might look: a fake model that returns clean output would sail through the
auditor, and a test suite built on one would prove the lock system works against
an adversary that never attacks. Every adversarial test in this repo scripts
MAIN to actually leak, and then asserts the pipeline catches it.

When no real model is configured, the UI refuses to chat and says so. It does
not silently substitute anything.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Sequence

from .base import (
    ChatMessage,
    GenerationResult,
    GenerationTimeout,
    ModelBackend,
    ModelSpec,
    Role,
)


class ScriptedBackend(ModelBackend):
    """Returns pre-programmed replies, in order or by prompt pattern.

    Two modes, combinable:

    * `replies` -- a queue consumed one per call. Exhausting it raises rather
      than looping, so a test that makes an unexpected extra call fails loudly
      instead of silently reusing the last answer.
    * `patterns` -- (regex, reply) pairs matched against the concatenated
      prompt. Checked before the queue.
    """

    def __init__(
        self,
        spec: ModelSpec | None = None,
        *,
        replies: Sequence[str] = (),
        patterns: Sequence[tuple[str, str]] = (),
        latency_s: float = 0.0,
        n_ctx: int = 4096,
    ) -> None:
        super().__init__(spec or ModelSpec(path="<scripted>", role=Role.MAIN, n_ctx=n_ctx))
        self._replies = list(replies)
        self._patterns = [(re.compile(p, re.IGNORECASE | re.DOTALL), r) for p, r in patterns]
        self._latency_s = latency_s
        self._n_ctx = n_ctx
        self._closed = False
        self.calls: list[list[ChatMessage]] = []

    @property
    def is_loaded(self) -> bool:
        return not self._closed

    @property
    def n_ctx(self) -> int:
        return self._n_ctx

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
        with self._lock:
            if self._closed:
                from .base import ModelUnavailable

                raise ModelUnavailable("scripted backend is closed")
            self.calls.append(list(messages))
            started = time.monotonic()

            if self._latency_s:
                # Simulated latency is how the timeout paths get tested without
                # waiting on a real 8B model.
                step = 0.01
                waited = 0.0
                while waited < self._latency_s:
                    if deadline is not None and time.monotonic() > deadline:
                        raise GenerationTimeout(
                            f"scripted backend exceeded deadline after {waited:.2f}s"
                        )
                    time.sleep(step)
                    waited += step

            if deadline is not None and time.monotonic() > deadline:
                raise GenerationTimeout("scripted backend deadline already passed")

            text = self._select(messages)

            if on_token:
                for chunk in text.split(" "):
                    on_token(chunk + " ")

            duration = time.monotonic() - started
            return GenerationResult(
                text=text,
                prompt_tokens=sum(self.count_tokens(m.content) for m in messages),
                completion_tokens=self.count_tokens(text),
                stop_reason="stop",
                duration_s=duration,
            )

    def _select(self, messages: Sequence[ChatMessage]) -> str:
        joined = "\n".join(m.content for m in messages)
        for pattern, reply in self._patterns:
            if pattern.search(joined):
                return reply
        if self._replies:
            return self._replies.pop(0)
        raise AssertionError(
            "ScriptedBackend ran out of replies. The code under test made more "
            "generation calls than the test scripted -- that is the finding, not "
            "a reason to add another reply."
        )

    def count_tokens(self, text: str) -> int:
        # Whitespace tokens. Not the real tokenizer, and deliberately not
        # pretending to be: tests that depend on exact counts should use this
        # backend's own arithmetic, and tests that depend on a real tokenizer
        # cannot be written without a real model.
        return len(text.split())

    def close(self) -> None:
        self._closed = True


def always_pass_auditor(spec: ModelSpec | None = None) -> ScriptedBackend:
    """An auditor that clears everything. For testing the *other* layers.

    Use only where the test's subject is Layer 2, 3 or 4 and the auditor is
    scenery. Never use it in a test that claims to exercise blocking.
    """
    return ScriptedBackend(
        spec or ModelSpec(path="<scripted-auditor>", role=Role.AUDITOR),
        patterns=[(r".*", "VERDICT: PASS")],
    )


def always_block_auditor(topic: str = "unknown", spec: ModelSpec | None = None) -> ScriptedBackend:
    return ScriptedBackend(
        spec or ModelSpec(path="<scripted-auditor>", role=Role.AUDITOR),
        patterns=[(r".*", f"VERDICT: BLOCK\nTOPIC: {topic}")],
    )
