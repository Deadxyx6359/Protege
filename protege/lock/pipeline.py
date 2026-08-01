"""The gate: Layers 4 and 5 over any text, fail-closed.

This is the library surface the brief asks for. Anything that puts model output
somewhere a human or a future retrieval pass will see it goes through
`OutputGate.check` -- chat responses, memory writes, consolidation output,
skill source. New components inherit gating by calling this rather than by
remembering to reimplement it.

Memory writes matter as much as chat here, and are easier to overlook. If MAIN
writes locked-topic content into the vault, Layer 3 will happily retrieve it
later, because by then it is just a note. The gate would have been bypassed by
the model's own notes. So the same check runs before anything reaches disk.

**Fail closed, structurally.** `check` has one `try` around its entire body. Any
exception -- a broken regex, an OOM in the auditor, a bug in this file --
produces a block. There is no code path where an exception results in
`allowed=True`, and the test suite asserts that by injecting failures at each
layer.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Sequence

from ..models import ModelManager, Role, deadline_from
from ..schemas import LockLayerToggles, Manifest, Settings
from .auditor import Verdict, audit
from .directive import DECLINE_PATTERN
from .retrieval import RetrievalResult
from .tripwires import TripwireScan, TripwireSet

# A response consisting only of decline markers and whitespace.
PURE_DECLINE_RE = re.compile(rf"\A(?:\s*{DECLINE_PATTERN}\s*)+\Z")


@dataclass(frozen=True)
class GateResult:
    """Whether a piece of text may leave the gate, and why not if not."""

    allowed: bool
    layer: str = ""          # "tripwires" | "auditor" | "error" | ""
    topic: str = ""
    reason: str = ""
    evidence: str = ""
    raw_verdict: str = ""
    layers_run: tuple[str, ...] = ()
    layers_skipped: tuple[str, ...] = ()
    duration_s: float = 0.0

    def to_block_detail(self):
        from ..chat import BlockDetail

        return BlockDetail(
            layer=self.layer or "unknown",
            topic=self.topic,
            reason=self.reason,
            evidence=self.evidence,
            raw_verdict=self.raw_verdict,
        )


def is_pure_decline(text: str) -> bool:
    """True when the text is only `[LOCKED: ...]` markers.

    Such a response is safe by construction -- it conveys no subject knowledge --
    so the auditor pass is skipped. That saves several seconds per refusal on a
    box where the auditor may be sharing MAIN's 8B weights.

    The match is deliberately anchored and total. `[LOCKED: chemistry] but here
    is a hint:` must not short-circuit, and it does not.
    """
    return bool(text.strip()) and bool(PURE_DECLINE_RE.match(text.strip()))


class OutputGate:
    """Layers 4 and 5, applied to arbitrary text."""

    def __init__(
        self,
        manifest: Manifest,
        settings: Settings,
        tripwires: TripwireSet,
        manager: ModelManager,
    ) -> None:
        self._manifest = manifest
        self._settings = settings
        self._tripwires = tripwires
        self._manager = manager

    @property
    def layers(self) -> LockLayerToggles:
        return self._settings.lock_layers

    def locked_topics_to_scan(self) -> tuple[str, ...]:
        """Locked topics that have tripwire rules defined.

        Scanning for a topic with no rules is a no-op, so the set is narrowed to
        those that can actually fire.
        """
        if self._manifest.unrestricted:
            # Everyday mode. Every topic reads as unlocked, and a tripwire for
            # an unlocked topic is inert by definition.
            return ()
        unlocked = set(self._manifest.unlocked_topics)
        return tuple(sorted(t for t in self._tripwires.by_topic if t not in unlocked))

    def check(self, user_prompt: str, text: str, *, allow_decline_shortcut: bool = True) -> GateResult:
        started = time.monotonic()
        run: list[str] = []
        skipped: list[str] = []

        try:
            if allow_decline_shortcut and is_pure_decline(text):
                return GateResult(
                    allowed=True,
                    layers_run=(),
                    layers_skipped=("tripwires", "auditor"),
                    reason="response is a compliant decline; no subject knowledge to check",
                    duration_s=time.monotonic() - started,
                )

            # -- Layer 4 ---------------------------------------------------
            if self.layers.tripwires:
                run.append("tripwires")
                scan: TripwireScan = self._tripwires.scan(text, self.locked_topics_to_scan())
                if scan.triggered:
                    return GateResult(
                        allowed=False,
                        layer="tripwires",
                        topic=scan.first_topic,
                        reason=scan.reason(),
                        evidence=scan.evidence(),
                        layers_run=tuple(run),
                        layers_skipped=tuple(skipped) + ("auditor",),
                        duration_s=time.monotonic() - started,
                    )
            else:
                skipped.append("tripwires")

            # -- Layer 5 ---------------------------------------------------
            if self.layers.auditor:
                run.append("auditor")
                verdict = self._run_auditor(user_prompt, text)
                if verdict.blocked:
                    return GateResult(
                        allowed=False,
                        layer="auditor",
                        topic=verdict.topic,
                        reason=verdict.reason(),
                        evidence=verdict.parse_error,
                        raw_verdict=verdict.raw,
                        layers_run=tuple(run),
                        layers_skipped=tuple(skipped),
                        duration_s=time.monotonic() - started,
                    )
            else:
                skipped.append("auditor")

            return GateResult(
                allowed=True,
                layers_run=tuple(run),
                layers_skipped=tuple(skipped),
                duration_s=time.monotonic() - started,
            )

        except Exception as exc:  # noqa: BLE001
            # The fail-closed backstop. A bug anywhere above becomes a block,
            # never a pass. This is the single most important except clause in
            # the codebase and it must stay this broad.
            return GateResult(
                allowed=False,
                layer="error",
                topic="",
                reason=f"lock system error: {type(exc).__name__}: {exc}",
                evidence="The response was blocked because a lock layer failed. "
                         "Protege blocks rather than passing output it could not fully check.",
                layers_run=tuple(run),
                layers_skipped=tuple(skipped),
                duration_s=time.monotonic() - started,
            )

    def _run_auditor(self, user_prompt: str, text: str) -> Verdict:
        auditor_settings = self._settings.auditor
        with self._manager.acquire(Role.AUDITOR) as backend:
            return audit(
                backend,
                user_prompt,
                text,
                self._manifest.unlocked_topics,
                deadline=deadline_from(auditor_settings.timeout_s),
                strictness=auditor_settings.strictness,
                max_draft_chars=auditor_settings.max_draft_chars,
            )


class PipelineResponder:
    """All five layers, end to end. The shipping configuration.

    One turn:

    1. Scan the vault and retrieve (Layer 3), scoped to the manifest, the
       current project, and the trust tier.
    2. Assemble the prompt within the token budget, directive last (Layers 1-2).
    3. Generate a draft with MAIN.
    4. Put the draft through the gate (Layers 4-5).
    5. Return either the draft or a `[LOCKED: topic]` marker.

    The vault is rescanned every turn rather than cached. A note re-tagged as
    locked, or a topic re-locked mid-session, must take effect on the very next
    message -- a stale index here is a lock bypass, and scanning a few hundred
    markdown files costs milliseconds.
    """

    def __init__(
        self,
        vault,
        manifest: Manifest,
        settings: Settings,
        personality,
        manager: ModelManager,
        *,
        tripwires: TripwireSet | None = None,
        project: str = "default",
        live_memory: "Callable[[], str] | None" = None,
        profile=None,
        audit=None,
        attachments: "Callable[[], list[tuple[str, str]]] | None" = None,
    ) -> None:
        self.vault = Path(vault)
        self.manifest = manifest
        self.settings = settings
        self.personality = personality
        self.profile = profile
        self.manager = manager
        self.project = project
        self._tripwires = tripwires
        self._live_memory = live_memory or (lambda: "")
        self._attachments = attachments or (lambda: [])
        self.report = GateReport()
        self.audit = audit

    @property
    def tripwires(self) -> TripwireSet:
        # Reloaded per turn for the same reason the vault is rescanned: an
        # edited pattern list must apply to the next message, not the next
        # restart.
        return self._tripwires if self._tripwires is not None else TripwireSet.load(self.vault)

    def gate(self) -> OutputGate:
        return OutputGate(self.manifest, self.settings, self.tripwires, self.manager)

    def _token_counter(self):
        """Prefer MAIN's own tokenizer; fall back to an estimate.

        A budget measured with the wrong tokenizer overflows silently, so the
        real one is used whenever a model is resident. The fallback exists for
        the case where nothing is loaded yet.
        """
        from ..context.assembly import estimate_tokens

        try:
            with self.manager.acquire(Role.MAIN) as backend:
                counter = backend.count_tokens
                counter("warm")
                return counter
        except Exception:  # noqa: BLE001
            return estimate_tokens

    def respond(
        self,
        user_text: str,
        conversation,
        *,
        on_token=None,
        on_stage=None,
    ):
        from ..chat import Turn, blocked_turn
        from ..context.assembly import ContextAssembler
        from ..lock.retrieval import retrieve
        from ..projects import get_project
        from ..security.paths import capabilities
        from ..vault import scan_vault

        started = time.monotonic()
        caps = capabilities(self.manifest.trust_tier)

        # -- Layer 3 ---------------------------------------------------------
        if on_stage:
            on_stage("retrieving")
        if caps.retrieval_enabled and self.settings.lock_layers.retrieval:
            scan = scan_vault(self.vault)
            retrieval = retrieve(
                scan,
                self.manifest,
                user_text,
                project=self.project,
                k=self.settings.context.max_retrieved_chunks,
                chunk_tokens=self.settings.context.chunk_tokens,
                overlap_tokens=self.settings.context.chunk_overlap_tokens,
            )
            project_doc = get_project(self.vault, self.project).read_doc() if caps.model_reads_vault else ""
        else:
            reason = (
                "trust tier 0 grants no vault access"
                if not caps.retrieval_enabled
                else "retrieval layer disabled in settings"
            )
            retrieval = RetrievalResult(disabled_reason=reason)
            project_doc = ""

        # -- Layers 1-2, within the budget ------------------------------------
        if on_stage:
            on_stage("assembling")
        assembler = ContextAssembler(self.settings, self._token_counter())
        assembled = assembler.assemble(
            manifest=self.manifest,
            personality=self.personality,
            profile=self.profile,
            project_doc=project_doc,
            retrieval=retrieval,
            live_memory=self._live_memory() if caps.model_reads_vault else "",
            conversation=conversation,
            user_text=user_text,
            # Only describe the tool where calling it could actually succeed.
            # Advertising it at tier 0 or 1 would have the model emit REMEMBER
            # lines that are parsed, refused by the tier check, and reported to
            # the user as failures -- noise generated by our own prompt.
            memory_tool=caps.model_proposed_memory and self.settings.memory.enabled,
            attached_files=self._attachments(),
        )

        # -- generate ---------------------------------------------------------
        if on_stage:
            on_stage("generating")
        models = self.settings.models
        with self.manager.acquire(Role.MAIN) as backend:
            result = backend.generate(
                assembled.messages,
                max_tokens=models.max_tokens,
                temperature=models.temperature,
                top_p=models.top_p,
                on_token=on_token,
            )
        draft = result.text.strip()

        # -- Layers 4-5 --------------------------------------------------------
        if on_stage:
            on_stage("checking")
        gate_result = self.gate().check(user_text, draft)
        self.report.record(gate_result)
        if self.audit is not None:
            self.audit.gate(gate_result, kind="response")

        if not gate_result.allowed:
            turn = blocked_turn(
                user_text,
                gate_result.to_block_detail(),
                draft=draft,
                system_prompt=assembled.system_prompt,
            )
            return replace(
                turn,
                duration_s=time.monotonic() - started,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                budget_note=assembled.usage_line,
                prompt_view=assembled.render_for_viewer(),
                notices=tuple(assembled.notices),
            )

        return Turn(
            user_text=user_text,
            text=draft,
            system_prompt=assembled.system_prompt,
            draft=draft,
            duration_s=time.monotonic() - started,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            budget_note=assembled.usage_line,
            prompt_view=assembled.render_for_viewer(),
            notices=tuple(assembled.notices),
        )


@dataclass
class GateReport:
    """Aggregate gate outcomes for a session, for the UI."""

    checks: int = 0
    blocks: int = 0
    by_layer: dict[str, int] = field(default_factory=dict)

    def record(self, result: GateResult) -> None:
        self.checks += 1
        if not result.allowed:
            self.blocks += 1
            self.by_layer[result.layer] = self.by_layer.get(result.layer, 0) + 1

    def summary(self) -> str:
        if not self.checks:
            return "no checks yet"
        parts = [f"{self.checks} checked", f"{self.blocks} blocked"]
        for layer, count in sorted(self.by_layer.items()):
            parts.append(f"{layer}: {count}")
        return ", ".join(parts)


def gate_topics(manifest: Manifest, topics: Sequence[str]) -> tuple[str, ...]:
    """Convenience for callers that need the locked subset of a topic list."""
    return manifest.all_locked(topics)
