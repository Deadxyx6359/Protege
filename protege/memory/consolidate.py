"""Session end: consolidation, the pending area, and the transcript holding area.

When a session ends:

1. MAIN reviews the live file and merges it into durable notes, deduplicating
   against what is already there.
2. The result goes to `memory/pending/`, **not** to `notes/`.
3. The transcript moves to `memory/holding/`, **not** to the bin.
4. The user reviews the consolidation in a diff view and confirms.
5. On confirmation the notes are committed and the transcript is deleted.

**Why the holding area exists.** Consolidation is done by an 8B model and will
sometimes produce notes that are wrong, or that quietly drop the one detail that
mattered. If the transcript is already gone when the user notices next week, the
source is unrecoverable -- the note is now the only record, and it is a bad one.
Seven days by default, configurable, with an immediate-delete option for people
who would rather not keep transcripts at all.

**Why pending is not retrievable.** Anything in `memory/pending/` is model
output the user has not looked at yet. `NoteScope.MEMORY_PENDING.retrievable` is
False, so it cannot influence answers before review. Otherwise the review step
would be decorative: the content would already be in play by the time anyone
read it.

Deletion is irreversible and the UI says so plainly before doing it.
"""

from __future__ import annotations

import difflib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from ..chat import BlockDetail
from ..lock.pipeline import OutputGate
from ..models import ChatMessage, ModelManager, ModelUnavailable, Role
from ..projects import Project, get_project, slugify
from ..schemas import Manifest, MemorySettings, Settings, normalize_topic, utcnow_iso
from ..store import write_text
from ..vault import Note, read_note, render_note, scan_vault
from .live import LiveMemory, MemoryEntry

SECONDS_PER_DAY = 86400


@dataclass
class ProposedNote:
    """One consolidated note awaiting review."""

    topic: str
    title: str
    body: str
    source_entries: tuple[str, ...] = ()
    merges_into: str = ""       # rel_path of an existing note this extends
    blocked: bool = False
    block_reason: str = ""
    detail: BlockDetail | None = None

    @property
    def filename(self) -> str:
        return f"{slugify(self.title, fallback=self.topic)}.md"

    def diff_against(self, existing: str) -> str:
        """Unified diff for the review dialog.

        Shown rather than a plain "here is a new note" because the interesting
        case is a merge, where the question is what changed in a note the user
        already trusts.
        """
        old = (existing or "").splitlines(keepends=True)
        new = self.body.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old, new,
            fromfile=self.merges_into or "(new note)",
            tofile=f"proposed: {self.filename}",
            lineterm="",
        )
        rendered = "\n".join(line.rstrip("\n") for line in diff)
        return rendered or "(no textual change)"


@dataclass
class ConsolidationResult:
    """Everything produced by one consolidation pass."""

    notes: list[ProposedNote] = field(default_factory=list)
    pending_paths: list[Path] = field(default_factory=list)
    transcript_path: Path | None = None
    live_path: Path | None = None
    errors: list[str] = field(default_factory=list)
    skipped: int = 0

    @property
    def usable(self) -> list[ProposedNote]:
        return [n for n in self.notes if not n.blocked]

    @property
    def blocked(self) -> list[ProposedNote]:
        return [n for n in self.notes if n.blocked]

    def summary(self) -> str:
        bits = [f"{len(self.usable)} note(s) proposed"]
        if self.blocked:
            bits.append(f"{len(self.blocked)} blocked by the lock system")
        if self.transcript_path:
            bits.append("transcript held")
        if self.errors:
            bits.append(f"{len(self.errors)} error(s)")
        return ", ".join(bits)


class Consolidator:
    def __init__(
        self,
        vault: Path,
        project: str,
        manifest: Manifest,
        settings: Settings,
        manager: ModelManager,
        gate: OutputGate,
    ) -> None:
        self.vault = Path(vault)
        self.project: Project = get_project(self.vault, project)
        self.manifest = manifest
        self.settings = settings
        self.manager = manager
        self.gate = gate

    @property
    def memory_settings(self) -> MemorySettings:
        return self.settings.memory

    # -- the pass -----------------------------------------------------------

    def consolidate(
        self,
        live: LiveMemory,
        transcript: str = "",
        *,
        on_stage: Callable[[str], None] | None = None,
    ) -> ConsolidationResult:
        result = ConsolidationResult(live_path=live.path if live.path.exists() else None)
        if not live.entries:
            return result

        by_topic: dict[str, list[MemoryEntry]] = {}
        for entry in live.entries:
            # An entry with no topic cannot be filed. Rather than invent a
            # topic for it, it stays in the live file, where the holding-area
            # rules govern it.
            for topic in entry.topics or ():
                by_topic.setdefault(topic, []).append(entry)
            if not entry.topics:
                result.skipped += 1

        existing = self._existing_notes()

        for topic, entries in sorted(by_topic.items()):
            if on_stage:
                on_stage(f"consolidating {topic}")
            try:
                note = self._consolidate_topic(topic, entries, existing.get(topic))
            except ModelUnavailable as exc:
                result.errors.append(f"{topic}: {exc}")
                continue
            if note is not None:
                result.notes.append(note)

        for note in result.usable:
            path = self.project.memory_pending_dir / note.filename
            write_text(
                path,
                render_note(
                    [note.topic],
                    note.body,
                    extra={
                        "kind": "pending-consolidation",
                        "session": live.session_id,
                        "consolidated_at": utcnow_iso(),
                        "merges_into": note.merges_into,
                    },
                ),
            )
            result.pending_paths.append(path)

        if transcript.strip():
            result.transcript_path = self._hold_transcript(live.session_id, transcript)

        return result

    def _existing_notes(self) -> dict[str, Note]:
        """One representative existing note per topic, for deduplication.

        Only notes the model may see. Handing it a locked note as
        "existing content to merge against" would leak that note into the
        consolidation prompt -- a memory write bypassing the gate through the
        back door of deduplication.
        """
        scan = scan_vault(self.vault)
        out: dict[str, Note] = {}
        for note in scan.visible(self.manifest, project=self.project.name):
            for topic in note.topics:
                out.setdefault(topic, note)
        return out

    def _consolidate_topic(
        self, topic: str, entries: Sequence[MemoryEntry], existing: Note | None
    ) -> ProposedNote | None:
        topic = normalize_topic(topic)
        bullet_text = "\n".join(f"- {e.content.strip()}" for e in entries)
        existing_body = existing.body.strip() if existing else ""

        with self.manager.acquire(Role.MAIN) as backend:
            generated = backend.generate(
                _consolidation_messages(topic, bullet_text, existing_body),
                max_tokens=self.settings.models.max_tokens,
                temperature=self.settings.models.temperature,
                top_p=self.settings.models.top_p,
            ).text.strip()

        if not generated:
            return None

        title = _first_heading(generated) or f"{topic.replace('_', ' ').title()} notes"
        note = ProposedNote(
            topic=topic,
            title=title,
            body=generated,
            source_entries=tuple(e.content for e in entries),
            merges_into=existing.rel_path if existing else "",
        )

        # Consolidation output is model output. Same gate as everything else.
        gate_result = self.gate.check(
            f"consolidate memory about {topic}", generated, allow_decline_shortcut=False
        )
        if not gate_result.allowed:
            note.blocked = True
            note.block_reason = f"blocked by the {gate_result.layer} layer: {gate_result.reason}"
            note.detail = gate_result.to_block_detail()
        return note

    # -- the holding area ---------------------------------------------------

    def _hold_transcript(self, session_id: str, transcript: str) -> Path | None:
        settings = self.memory_settings
        if settings.delete_transcript_immediately:
            # Explicitly chosen by the user. Nothing is written, so there is
            # nothing to recover -- which is the point of the option.
            return None
        path = self.project.memory_holding_dir / f"{session_id}.transcript.md"
        write_text(
            path,
            render_note(
                [],  # No topics: the holding area is never retrievable.
                transcript,
                extra={
                    "kind": "held-transcript",
                    "session": session_id,
                    "held_at": utcnow_iso(),
                    "delete_after_days": settings.holding_days,
                },
            ),
        )
        return path

    def _retire_transcript(self, path: Path | None) -> Path | None:
        """Delete a held transcript, or move it to the archive if asked to keep it.

        One place decides, so "keep transcripts" cannot be honoured at session
        end and quietly ignored by the sweep a week later -- which is exactly
        the sort of half-wired setting that makes a privacy control worthless.
        Returns the archived path, or None when the file was deleted.
        """
        if path is None or not path.exists():
            return None
        if not self.memory_settings.keep_transcripts:
            path.unlink(missing_ok=True)
            return None

        archive = self.project.memory_archive_dir
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / path.name
        counter = 2
        while target.exists():
            target = archive / f"{path.stem}-{counter}{path.suffix}"
            counter += 1
        try:
            path.replace(target)
        except OSError:
            # Across devices, or a locked file. Copying and unlinking is worse
            # than leaving it in holding, where the next sweep will find it.
            return None
        return target

    def sweep_holding(self, *, now: float | None = None) -> list[Path]:
        """Delete held transcripts past their retention period.

        Returns what was deleted so the UI can say so. A holding period of 0
        means "delete at the next sweep", which is distinct from
        `delete_transcript_immediately` -- that one never writes the file at all.
        """
        days = self.memory_settings.holding_days
        now = now if now is not None else time.time()
        cutoff = now - days * SECONDS_PER_DAY
        removed: list[Path] = []
        directory = self.project.memory_holding_dir
        if not directory.is_dir():
            return removed
        for path in sorted(directory.glob("*.transcript.md")):
            try:
                if path.stat().st_mtime <= cutoff:
                    self._retire_transcript(path)
                    removed.append(path)
            except OSError:
                continue
        return removed

    # -- confirmation -------------------------------------------------------

    def confirm(self, result: ConsolidationResult, *, accept: Sequence[str] | None = None) -> list[Path]:
        """Commit reviewed notes to `notes/` and delete the session's traces.

        `accept` names the pending filenames to keep; None accepts all usable
        ones. Anything not accepted is discarded along with the rest.

        Irreversible. The caller must have confirmed with the user first -- this
        method does not ask.
        """
        committed: list[Path] = []
        wanted = set(accept) if accept is not None else {n.filename for n in result.usable}

        for pending in list(result.pending_paths):
            if pending.name not in wanted:
                pending.unlink(missing_ok=True)
                continue
            note = read_note(pending, self.vault)
            target = self.project.notes_dir / pending.name
            write_text(
                target,
                render_note(
                    list(note.topics),
                    note.body,
                    extra={"kind": "note", "consolidated_at": utcnow_iso()},
                ),
            )
            pending.unlink(missing_ok=True)
            committed.append(target)

        self._retire_transcript(result.transcript_path)
        if result.live_path is not None:
            result.live_path.unlink(missing_ok=True)
        return committed

    def discard(self, result: ConsolidationResult, *, keep_transcript: bool = True) -> None:
        """Throw the consolidation away.

        The transcript is kept by default: the user rejecting a bad
        consolidation is exactly the case the holding area was built for, and
        deleting the source at that moment would be the worst possible timing.
        """
        for pending in result.pending_paths:
            pending.unlink(missing_ok=True)
        result.pending_paths.clear()
        if not keep_transcript:
            self._retire_transcript(result.transcript_path)


# --- prompts ---------------------------------------------------------------


def _consolidation_messages(topic: str, bullets: str, existing: str) -> list[ChatMessage]:
    instruction = (
        "You are merging session notes into a durable note. Write clean markdown starting with a "
        "single '# ' heading. Do not invent facts. Do not add anything not present in the material "
        "below. Keep it concise."
    )
    if existing:
        body = (
            f"EXISTING NOTE ON '{topic}':\n\n{existing}\n\n"
            f"NEW OBSERVATIONS FROM THIS SESSION:\n\n{bullets}\n\n"
            "Produce the updated note. Do not repeat anything the existing note already says; "
            "integrate the new observations into it."
        )
    else:
        body = (
            f"OBSERVATIONS FROM THIS SESSION ABOUT '{topic}':\n\n{bullets}\n\n"
            "Produce a new note capturing these."
        )
    return [
        ChatMessage(role="system", content=instruction),
        ChatMessage(role="user", content=body),
    ]


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""
