"""The unlock flow -- how a topic stops being locked.

    1. The user writes notes on a topic in the vault.
    2. The user starts an unlock, choosing the topic and the source notes.
    3. MAIN is given those notes and asked to demonstrate understanding:
       summarize them, generate questions, then answer its own questions.
    4. The user reviews the demonstration and approves or rejects.
    5. On approval the topic enters the manifest with provenance.

**The one place locked-topic output is deliberately shown.** MAIN must read the
locked notes here -- there is no way to demonstrate understanding of a subject
without discussing it, and refusing to would make unlocking impossible. Three
things keep that from being a hole:

* The notes are chosen explicitly by the user in a file picker. This is a user
  action, not a model action, and it is not gated by trust tier.
* The user already knows the content: they wrote it. Nothing is being revealed
  to them.
* The demonstration goes nowhere. It is shown in a modal review dialog, is not
  appended to conversation history, and is never written to the vault -- unless
  the user approves, and even then only the manifest entry is recorded, not the
  text.

**The demonstration is still gated against every *other* locked topic.** If a
user unlocking `chemistry` gets a demonstration that also explains
`cryptography`, that blocks. The topic under review is exempt from its own
unlock; nothing else is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .lock.pipeline import OutputGate
from .lock.tripwires import TripwireSet
from .models import ChatMessage, ModelManager, ModelUnavailable, Role
from .schemas import Manifest, SchemaError, Settings, normalize_topic, utcnow_iso
from .vault import Note, VaultScan, coerce_topic, read_note, scan_vault

DEFAULT_QUESTION_COUNT = 4
MAX_SOURCE_CHARS = 24000


class UnlockError(RuntimeError):
    """The unlock could not proceed."""


@dataclass
class UnlockProposal:
    """A demonstration awaiting the user's verdict.

    Holds everything the review dialog shows. Deliberately inert: constructing
    one changes nothing. Only `approve` touches the manifest.
    """

    topic: str
    source_notes: tuple[str, ...]
    summary: str = ""
    questions: tuple[str, ...] = ()
    answers: tuple[str, ...] = ()
    blocked: bool = False
    block_reason: str = ""
    source_chars: int = 0
    truncated_sources: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.blocked and bool(self.summary.strip())

    def render(self) -> str:
        """The text shown in the review dialog."""
        lines = [f"TOPIC: {self.topic}", ""]
        lines.append("SOURCE NOTES:")
        lines.extend(f"  - {p}" for p in self.source_notes)
        if self.truncated_sources:
            lines.append("  (source text was truncated to fit the model's context)")
        lines.append("")
        if self.blocked:
            lines.append("DEMONSTRATION BLOCKED")
            lines.append("")
            lines.append(self.block_reason)
            lines.append("")
            lines.append(
                "The demonstration drew on a locked topic other than the one being unlocked. "
                "Approving is not offered."
            )
            return "\n".join(lines)

        lines.append("SUMMARY")
        lines.append("-" * 60)
        lines.append(self.summary.strip() or "(the model produced no summary)")
        lines.append("")
        if self.questions:
            lines.append("SELF-TEST")
            lines.append("-" * 60)
            for i, question in enumerate(self.questions):
                answer = self.answers[i] if i < len(self.answers) else "(no answer)"
                lines.append(f"Q{i + 1}. {question}")
                lines.append(f"A{i + 1}. {answer}")
                lines.append("")
        if self.warnings:
            lines.append("WARNINGS")
            lines.append("-" * 60)
            lines.extend(f"  - {w}" for w in self.warnings)
        return "\n".join(lines)


@dataclass(frozen=True)
class RelockImpact:
    """What re-locking a topic will hide.

    Shown before the user confirms. The brief singles out memory notes, and
    they are the surprising case: the user remembers writing their own notes,
    but not necessarily what the model recorded about the topic three sessions
    ago.
    """

    topic: str
    notes: tuple[str, ...] = ()
    memory_notes: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return len(self.notes) + len(self.memory_notes)

    def describe(self) -> str:
        lines = [f"Re-locking {self.topic!r} will hide {self.total} note(s) from the model:"]
        if self.notes:
            lines.append(f"  {len(self.notes)} knowledge note(s)")
        if self.memory_notes:
            lines.append(f"  {len(self.memory_notes)} memory note(s) written during past sessions")
        if not self.total:
            lines.append("  (no notes currently carry this topic)")
        return "\n".join(lines)


class UnlockFlow:
    """Runs a demonstration and applies the result."""

    def __init__(
        self,
        vault: Path,
        manifest: Manifest,
        settings: Settings,
        manager: ModelManager,
        *,
        tripwires: TripwireSet | None = None,
    ) -> None:
        self.vault = Path(vault)
        self.manifest = manifest
        self.settings = settings
        self.manager = manager
        self._tripwires = tripwires

    # -- source material ----------------------------------------------------

    def load_sources(self, note_paths: Sequence[str]) -> tuple[list[Note], str, bool]:
        """Read the user-selected notes.

        Reads by explicit path rather than through retrieval, because the whole
        point is to see notes that are currently invisible to it.
        """
        notes: list[Note] = []
        for rel in note_paths:
            path = (self.vault / rel).resolve()
            try:
                path.relative_to(self.vault.resolve())
            except ValueError as exc:
                raise UnlockError(f"source note {rel!r} is outside the vault") from exc
            if not path.is_file():
                raise UnlockError(f"source note not found: {rel}")
            note = read_note(path, self.vault)
            if note.error:
                raise UnlockError(f"source note {rel!r} could not be read: {note.error}")
            notes.append(note)

        if not notes:
            raise UnlockError("select at least one source note")

        parts = [f"### {n.rel_path}\n\n{n.body.strip()}" for n in notes]
        combined = "\n\n".join(parts)
        truncated = len(combined) > MAX_SOURCE_CHARS
        if truncated:
            combined = combined[:MAX_SOURCE_CHARS]
        return notes, combined, truncated

    # -- demonstration ------------------------------------------------------

    def demonstrate(
        self,
        topic: str,
        note_paths: Sequence[str],
        *,
        question_count: int = DEFAULT_QUESTION_COUNT,
        on_stage: Callable[[str], None] | None = None,
        review: bool = False,
    ) -> UnlockProposal:
        """Run the demonstration for `topic` against the given notes.

        `review` re-runs it for a topic that is *already* unlocked, which is
        how a retention check works: the same ritual, against whatever the
        notes say now, granting nothing new. Without the flag this refuses,
        and rightly so -- demonstrating to unlock something already unlocked
        would be a no-op dressed up as a decision.
        """
        topic = normalize_topic(topic)
        if self.manifest.is_unlocked(topic) and not review:
            raise UnlockError(f"{topic!r} is already unlocked")
        if review and not self.manifest.is_unlocked(topic):
            raise UnlockError(f"{topic!r} is not unlocked, so there is nothing to review")

        notes, sources, truncated = self.load_sources(note_paths)
        proposal = UnlockProposal(
            topic=topic,
            source_notes=tuple(n.rel_path for n in notes),
            source_chars=len(sources),
            truncated_sources=truncated,
        )

        tagged = {t for n in notes for t in n.topics}
        if topic not in tagged:
            # Not fatal -- the user may be about to tag them -- but unlocking a
            # topic from notes that do not carry it means retrieval will find
            # nothing afterwards, which looks like the unlock failed.
            proposal.warnings.append(
                f"none of the selected notes are tagged with {topic!r}; after unlocking, "
                "retrieval will not surface them until you add the tag"
            )

        models = self.settings.models
        try:
            with self.manager.acquire(Role.MAIN) as backend:
                if on_stage:
                    on_stage("summarizing")
                proposal.summary = backend.generate(
                    _summary_messages(topic, sources),
                    max_tokens=models.max_tokens,
                    temperature=models.temperature,
                    top_p=models.top_p,
                ).text.strip()

                if on_stage:
                    on_stage("generating questions")
                raw_questions = backend.generate(
                    _question_messages(topic, sources, question_count),
                    max_tokens=384,
                    temperature=models.temperature,
                    top_p=models.top_p,
                ).text
                proposal.questions = _parse_questions(raw_questions, question_count)

                answers: list[str] = []
                for i, question in enumerate(proposal.questions):
                    if on_stage:
                        on_stage(f"answering {i + 1}/{len(proposal.questions)}")
                    answers.append(
                        backend.generate(
                            _answer_messages(topic, sources, question),
                            max_tokens=models.max_tokens,
                            temperature=models.temperature,
                            top_p=models.top_p,
                        ).text.strip()
                    )
                proposal.answers = tuple(answers)
        except ModelUnavailable as exc:
            raise UnlockError(str(exc)) from exc

        if on_stage:
            on_stage("checking for other locked topics")
        self._gate_demonstration(proposal)
        return proposal

    def _gate_demonstration(self, proposal: UnlockProposal) -> None:
        """Check the demonstration against every locked topic except this one.

        The topic under review is exempt -- it has to be, or the demonstration
        could never pass. Nothing else is exempt, so a demonstration that
        wanders into a second locked subject is refused and cannot be approved.
        """
        pretend = self.manifest.with_unlocked(proposal.topic, note="temporary, for demonstration gating only")
        tripwires = self._tripwires if self._tripwires is not None else TripwireSet.load(self.vault)
        gate = OutputGate(pretend, self.settings, tripwires, self.manager)

        combined = "\n\n".join(
            [proposal.summary, *proposal.questions, *proposal.answers]
        ).strip()
        if not combined:
            return
        result = gate.check(f"demonstrate understanding of {proposal.topic}", combined)
        if not result.allowed:
            proposal.blocked = True
            proposal.block_reason = (
                f"blocked by the {result.layer} layer: {result.reason}"
                + (f"\n\n{result.evidence}" if result.evidence else "")
            )

    # -- applying -----------------------------------------------------------

    def approve(self, proposal: UnlockProposal, *, note: str = "") -> Manifest:
        if proposal.blocked:
            raise UnlockError(
                "this demonstration was blocked because it drew on another locked topic; "
                "it cannot be approved"
            )
        self.manifest = self.manifest.with_unlocked(
            proposal.topic,
            source_notes=proposal.source_notes,
            note=note or f"approved after demonstration at {utcnow_iso()}",
        )
        return self.manifest

    def confirm_review(self, proposal: UnlockProposal, *, note: str = "") -> Manifest:
        """Record a passed retention check. Access is unchanged either way.

        Only the clock moves. A review that the user rejects simply leaves the
        topic due, which is the honest outcome: the notes did not hold up, and
        the fix is to rewrite them, not to lose the topic.
        """
        if proposal.blocked:
            raise UnlockError(
                "this demonstration was blocked because it drew on another locked "
                "topic; it cannot be recorded as a review"
            )
        self.manifest = self.manifest.with_reviewed(
            proposal.topic,
            source_notes=proposal.source_notes,
            note=note or f"reviewed after demonstration at {utcnow_iso()}",
        )
        return self.manifest

    def relock(self, topic: str, *, note: str = "") -> Manifest:
        self.manifest = self.manifest.with_relocked(normalize_topic(topic), note=note)
        return self.manifest

    def relock_impact(self, topic: str, scan: VaultScan | None = None) -> RelockImpact:
        """What will become invisible if this topic is re-locked.

        Note that nothing has to be *done* to hide memory notes: visibility is
        computed from the manifest on every scan, so removing the topic hides
        every note carrying it, memory notes included. This method exists to
        tell the user what is about to happen, not to make it happen.
        """
        topic = normalize_topic(topic)
        scan = scan or scan_vault(self.vault)
        notes: list[str] = []
        memory: list[str] = []
        for note in scan.notes:
            if topic not in note.topics:
                continue
            if "memory" in note.rel_path.split("/"):
                memory.append(note.rel_path)
            else:
                notes.append(note.rel_path)
        return RelockImpact(topic=topic, notes=tuple(sorted(notes)), memory_notes=tuple(sorted(memory)))


# --- prompts ---------------------------------------------------------------
#
# These are the only prompts in Protege that hand MAIN locked material on
# purpose. Each one restates that the notes are the sole permitted source, so
# the demonstration reflects what the user actually wrote rather than what the
# model already knew about the subject -- which is the whole point of judging it.

_GROUND_RULE = (
    "Use ONLY the notes provided below. Do not add facts from your own knowledge, "
    "even if you are confident they are correct. If the notes do not cover something, say so."
)


def _summary_messages(topic: str, sources: str) -> list[ChatMessage]:
    return [
        ChatMessage(
            role="system",
            content=(
                f"You are being tested on whether you have understood a set of notes about "
                f"'{topic}'. {_GROUND_RULE}"
            ),
        ),
        ChatMessage(
            role="user",
            content=f"NOTES:\n\n{sources}\n\nSummarize what these notes say about {topic}.",
        ),
    ]


def _question_messages(topic: str, sources: str, count: int) -> list[ChatMessage]:
    return [
        ChatMessage(
            role="system",
            content=(
                f"You generate comprehension questions about a set of notes on '{topic}'. "
                f"{_GROUND_RULE}"
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"NOTES:\n\n{sources}\n\n"
                f"Write exactly {count} questions that test understanding of these notes. "
                "Number them 1. through "
                f"{count}. Output only the numbered questions, nothing else."
            ),
        ),
    ]


def _answer_messages(topic: str, sources: str, question: str) -> list[ChatMessage]:
    return [
        ChatMessage(
            role="system",
            content=f"You are answering a comprehension question about notes on '{topic}'. {_GROUND_RULE}",
        ),
        ChatMessage(role="user", content=f"NOTES:\n\n{sources}\n\nQUESTION: {question}\n\nAnswer it."),
    ]


def _parse_questions(raw: str, limit: int) -> tuple[str, ...]:
    """Pull numbered questions out of MAIN's output.

    Small models number lists inconsistently -- "1.", "1)", "Q1:", or bare
    lines. Rather than demand one format, take whatever looks like a question
    and move on; a malformed list here degrades the review, not the lock.
    """
    questions: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        cleaned = re.sub(r"^(?:Q\s*)?\d+\s*[.)\]:-]\s*", "", stripped, flags=re.IGNORECASE)
        cleaned = cleaned.strip("-* \t")
        if len(cleaned) < 8:
            continue
        questions.append(cleaned)
        if len(questions) >= limit:
            break
    return tuple(questions)


def available_topics(scan: VaultScan, manifest: Manifest) -> tuple[str, ...]:
    """Topics mentioned by notes but not yet unlocked -- the picker's contents."""
    return tuple(t for t in scan.all_topics() if not manifest.is_unlocked(t))


def validate_new_topic(raw: str, manifest: Manifest) -> str:
    """Coerce and validate a topic typed into the unlock dialog.

    Uses the same lenient coercion as note frontmatter, so `DC Basics`,
    `DC-Basics` and `dc_basics` all land on `dc_basics`. They previously
    disagreed: writing `topics: [DC Basics]` in a note worked, while typing the
    identical string here was rejected as a malformed id. One input, two
    answers, and no way for the user to tell which rule applied where.

    Coercion is safe in this direction -- it can only map a spelling onto the
    id the user plainly meant. It cannot invent an unlock, because the result
    is still checked against the manifest below.
    """
    coerced = coerce_topic(raw)
    if coerced is None:
        raise SchemaError(
            f"cannot read {raw.strip()!r} as a topic name -- use letters and digits, "
            "e.g. 'dc basics' or 'dc_basics'"
        )
    if manifest.is_unlocked(coerced):
        raise SchemaError(f"{coerced!r} is already unlocked")
    return coerced
