"""Searching kept transcripts.

Transcripts are deleted after consolidation unless `memory.keep_transcripts`
says otherwise, in which case they land in each project's `memory/archive/`.
This module reads that archive back.

Search is a plain case-folded substring scan over the body, not the BM25 index
used for retrieval. Two reasons, and the second is the important one. Archived
transcripts are few and small, so ranking buys nothing. And they are
deliberately *outside* the lock: a transcript records both sides of a
conversation, including drafts the gate later blocked, so indexing it for
retrieval would hand the model back exactly what it was stopped from saying.
Nothing here is ever put in front of the model -- it is for the user to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .projects import list_projects
from .vault import parse_frontmatter

MAX_TRANSCRIPTS = 2000
SNIPPET_CHARS = 160


@dataclass(frozen=True)
class Transcript:
    path: Path
    project: str
    session: str
    held_at: str
    body: str

    @property
    def lines(self) -> int:
        return self.body.count("\n") + 1

    def label(self) -> str:
        when = self.held_at[:16].replace("T", " ") if self.held_at else "unknown date"
        return f"{when}   {self.project}   ({self.lines} lines)"

    def snippet(self, needle: str = "") -> str:
        """The first match in context, or the opening of the transcript."""
        if needle:
            found = self.body.lower().find(needle.lower())
            if found != -1:
                start = max(0, found - SNIPPET_CHARS // 3)
                return self.body[start:start + SNIPPET_CHARS].replace("\n", " ").strip()
        return self.body[:SNIPPET_CHARS].replace("\n", " ").strip()


def _read(path: Path, project: str) -> Transcript | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        frontmatter, body, _ = parse_frontmatter(raw)
    except Exception:  # noqa: BLE001 - a damaged archive file is not fatal
        frontmatter, body = {}, raw
    return Transcript(
        path=path,
        project=project,
        session=str(frontmatter.get("session", path.stem)),
        held_at=str(frontmatter.get("held_at", "")),
        body=body.strip(),
    )


def load_all(vault: Path) -> list[Transcript]:
    """Every archived transcript across every project, newest first."""
    out: list[Transcript] = []
    for project in list_projects(vault):
        archive = project.memory_archive_dir
        if not archive.is_dir():
            continue
        for path in sorted(archive.glob("*.md")):
            transcript = _read(path, project.name)
            if transcript is not None:
                out.append(transcript)
            if len(out) >= MAX_TRANSCRIPTS:
                break
    return sorted(out, key=lambda t: (t.held_at, t.path.name), reverse=True)


def search(transcripts: list[Transcript], needle: str) -> list[Transcript]:
    """Case-folded substring match. An empty query returns everything."""
    needle = needle.strip().lower()
    if not needle:
        return transcripts
    return [t for t in transcripts if needle in t.body.lower()]


def summarize(all_count: int, shown: int, *, enabled: bool) -> str:
    if not enabled:
        return (
            "Transcripts are not being kept. They are deleted once consolidation is "
            "confirmed, which is the default -- turn on 'Keep transcripts' in "
            "Settings -> Memory to start an archive from the next session."
        )
    if not all_count:
        return (
            "No transcripts archived yet. They are kept from the next session that "
            "ends with consolidation confirmed."
        )
    if shown == all_count:
        return f"{all_count} transcript(s) archived."
    return f"{shown} of {all_count} transcript(s) match."
