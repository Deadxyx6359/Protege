"""Reading the vault: markdown, YAML frontmatter, and topic tagging.

The vault is a plain directory of markdown. Obsidian is optional -- Akira
reads and writes the files directly and never touches Obsidian's own state.

Three rules govern visibility, and all three fail closed. They are the reason
Layer 3 is worth more than the directive it backs up:

1. **An untagged note is invisible.** Not "visible to everything" -- invisible.
   The alternative would make the lock opt-in: write a note about a locked
   subject, omit the frontmatter, and retrieval hands it to the model.

2. **A note is visible only if *every* topic it carries is unlocked.** Not any.
   A note tagged `[python_basics, cryptography]` with only `python_basics`
   unlocked would otherwise deliver cryptography content through an unlocked
   door.

3. **A note that fails to parse is invisible.** Malformed frontmatter, an
   unreadable file, or a tag that cannot be coerced into a topic id all mean
   "unknown topics", and unknown is treated as locked. Parse failures are
   collected and surfaced in the UI so they get fixed rather than silently
   swallowing a note the user believed was available.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import yaml

from .schemas import TOPIC_ID_RE, Manifest

FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)

# Directories never scanned for knowledge. `.protege` holds the control files
# (including the manifest that defines the gate) and `.obsidian` holds editor
# state; indexing either would feed Akira its own configuration as knowledge.
EXCLUDED_DIRS = frozenset({".protege", ".obsidian", ".trash", ".git", ".stfolder", "node_modules"})

MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})

# Frontmatter keys inspected for topic tags, in priority order. `tags` is
# included because that is what Obsidian users already write.
TOPIC_KEYS = ("topics", "topic", "tags", "tag")


class NoteScope(Enum):
    """Where a note sits, which determines how it reaches the model."""

    GLOBAL = "global"           # global/notes/** -- available to every project
    PROJECT = "project"         # projects/<p>/notes/** -- that project only
    PROJECT_DOC = "project_doc" # projects/<p>/project.md -- always loaded, never retrieved
    MEMORY_LIVE = "memory_live" # projects/<p>/memory/live/** -- injected directly
    MEMORY_PENDING = "memory_pending"  # consolidated, awaiting user confirmation
    LOOSE = "loose"             # anything else the user keeps in the vault

    @property
    def retrievable(self) -> bool:
        """Whether Layer 3 may return chunks from this scope.

        `PROJECT_DOC` and `MEMORY_LIVE` are excluded because they are injected
        into context directly at their own budget priority; retrieving them too
        would double-count them against the budget.

        `MEMORY_PENDING` is excluded because it holds consolidation output the
        user has not yet confirmed. Feeding unreviewed model-written notes back
        into retrieval would make the review step decorative -- the content
        would already be influencing answers before anyone looked at it.
        """
        return self in (NoteScope.GLOBAL, NoteScope.PROJECT, NoteScope.LOOSE)


def coerce_topic(raw: object) -> str | None:
    """Best-effort conversion of a frontmatter tag into a topic id.

    Deliberately lenient: `Python-Basics`, `#python basics` and `python/basics`
    all become `python_basics`. Being strict here would be actively harmful,
    because a tag that fails to match an unlocked topic makes the note look
    untagged, and untagged means invisible -- so strictness would silently hide
    notes the user believed they had tagged correctly.

    Leniency is safe in both directions. It can only ever make a tag match a
    topic id the user plainly meant; it cannot cause a locked topic to be
    treated as unlocked, because matching happens against the manifest, which
    is validated strictly.

    Returns None when no sensible id can be recovered. The caller must treat
    None as "unknown topic", which makes the note invisible.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if not isinstance(raw, (str, int, float)):
        return None
    text = str(raw).strip().lower().lstrip("#")
    text = re.sub(r"[\s/\\.\-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text or not TOPIC_ID_RE.match(text):
        return None
    return text


@dataclass(frozen=True)
class Note:
    """One markdown file in the vault."""

    path: Path
    rel_path: str            # vault-relative, forward slashes, stable across platforms
    scope: NoteScope
    project: str             # "" for global and loose notes
    topics: tuple[str, ...]
    body: str
    frontmatter: dict
    mtime: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def title(self) -> str:
        heading = re.search(r"^#\s+(.+)$", self.body, re.MULTILINE)
        if heading:
            return heading.group(1).strip()
        return Path(self.rel_path).stem

    def visible_to(self, manifest: Manifest) -> bool:
        """Whether the model may see this note's contents at all.

        The three fail-closed rules from the module docstring, in one place.
        Nothing else in the codebase decides note visibility.
        """
        if self.error:
            return False
        if not self.topics:
            return False
        return not manifest.all_locked(self.topics)

    def locked_topics(self, manifest: Manifest) -> tuple[str, ...]:
        if self.error or not self.topics:
            return ()
        return manifest.all_locked(self.topics)


@dataclass
class VaultScan:
    """Everything found in one pass over the vault."""

    notes: list[Note] = field(default_factory=list)
    problems: list[Note] = field(default_factory=list)
    scanned: int = 0

    def visible(self, manifest: Manifest, *, project: str = "", retrievable_only: bool = True) -> list[Note]:
        """Notes the model may see, scoped to the manifest and the project.

        Project notes are invisible from other projects; global notes are
        available everywhere.
        """
        out: list[Note] = []
        for note in self.notes:
            if retrievable_only and not note.scope.retrievable:
                continue
            if note.scope is NoteScope.PROJECT and project and note.project != project:
                continue
            if not note.visible_to(manifest):
                continue
            out.append(note)
        return out

    def hidden_count(self, manifest: Manifest) -> int:
        """How many notes exist but are withheld.

        Shown in the UI. A user who has written notes and sees nothing retrieved
        needs to know whether the notes are locked, untagged, or unparseable --
        the three look identical from the chat window.
        """
        return sum(1 for n in self.notes if not n.visible_to(manifest))

    def untagged(self) -> list[Note]:
        return [n for n in self.notes if n.ok and not n.topics]

    def by_rel_path(self, rel_path: str) -> Note | None:
        for note in self.notes:
            if note.rel_path == rel_path:
                return note
        return None

    def all_topics(self) -> tuple[str, ...]:
        """Every topic mentioned by any note, for the unlock dialog's picker."""
        seen: set[str] = set()
        for note in self.notes:
            seen.update(note.topics)
        return tuple(sorted(seen))


def parse_frontmatter(text: str) -> tuple[dict, str, str]:
    """Split a markdown document into (frontmatter, body, error).

    On any error the frontmatter comes back empty and `error` is set. Callers
    must not treat an empty frontmatter dict as "no tags, therefore fine" --
    check `error` first, because a note whose tags failed to parse is a note
    whose topics are unknown.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text, ""
    raw = match.group(1)
    body = text[match.end():]
    try:
        # safe_load only: never yaml.load. Frontmatter is user-authored data,
        # and full YAML can construct arbitrary Python objects.
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        detail = str(exc).replace("\n", " ")[:200]
        return {}, body, f"malformed YAML frontmatter: {detail}"
    if loaded is None:
        return {}, body, ""
    if not isinstance(loaded, dict):
        return {}, body, f"frontmatter must be a mapping, got {type(loaded).__name__}"
    return loaded, body, ""


def extract_topics(frontmatter: dict) -> tuple[tuple[str, ...], str]:
    """Pull topic ids out of parsed frontmatter.

    Returns (topics, error). A tag that cannot be coerced yields an error, and
    the caller makes the note invisible -- rather than dropping the bad tag and
    keeping the good ones, which would let `topics: [python_basics, "¿¿¿"]`
    resolve to a fully-unlocked note.
    """
    raw_values: list[object] = []
    for key in TOPIC_KEYS:
        if key not in frontmatter:
            continue
        value = frontmatter[key]
        if isinstance(value, (list, tuple, set)):
            raw_values.extend(value)
        else:
            raw_values.append(value)
        break  # first key present wins; see TOPIC_KEYS ordering

    topics: list[str] = []
    bad: list[str] = []
    for value in raw_values:
        coerced = coerce_topic(value)
        if coerced is None:
            bad.append(repr(value))
        elif coerced not in topics:
            topics.append(coerced)

    if bad:
        return (), f"unusable topic tag(s): {', '.join(bad)}"
    return tuple(sorted(topics)), ""


def classify(rel_path: str) -> tuple[NoteScope, str]:
    """Map a vault-relative path to its scope and owning project."""
    parts = rel_path.split("/")
    if parts[0] == "global" and len(parts) > 2 and parts[1] == "notes":
        return NoteScope.GLOBAL, ""
    if parts[0] == "projects" and len(parts) >= 3:
        project = parts[1]
        rest = parts[2:]
        if rest == ["project.md"]:
            return NoteScope.PROJECT_DOC, project
        if rest[0] == "notes":
            return NoteScope.PROJECT, project
        if rest[0] == "memory" and len(rest) >= 2:
            if rest[1] == "live":
                return NoteScope.MEMORY_LIVE, project
            if rest[1] == "pending":
                return NoteScope.MEMORY_PENDING, project
        return NoteScope.PROJECT, project
    return NoteScope.LOOSE, ""


def iter_markdown(vault: Path) -> Iterator[Path]:
    """Walk the vault, skipping control and editor directories."""
    vault = Path(vault)
    for dirpath, dirnames, filenames in os.walk(vault):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if Path(name).suffix.lower() in MARKDOWN_SUFFIXES:
                yield Path(dirpath) / name


def read_note(path: Path, vault: Path) -> Note:
    """Read and classify one markdown file. Never raises."""
    path = Path(path)
    vault = Path(vault)
    try:
        rel = path.relative_to(vault).as_posix()
    except ValueError:
        rel = path.name

    scope, project = classify(rel)

    try:
        text = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
    except (OSError, UnicodeDecodeError) as exc:
        return Note(
            path=path, rel_path=rel, scope=scope, project=project,
            topics=(), body="", frontmatter={}, error=f"cannot read: {exc}",
        )

    frontmatter, body, error = parse_frontmatter(text)
    topics: tuple[str, ...] = ()
    if not error:
        topics, error = extract_topics(frontmatter)

    return Note(
        path=path,
        rel_path=rel,
        scope=scope,
        project=project,
        topics=topics,
        body=body,
        frontmatter=frontmatter,
        mtime=mtime,
        error=error,
    )


def scan_vault(vault: Path, *, limit: int = 20000) -> VaultScan:
    """Read every markdown file in the vault.

    A full re-read rather than an incremental index. At vault scale -- hundreds
    to low thousands of notes -- this takes milliseconds, and a stale index is a
    correctness problem here rather than a performance one: a note re-tagged as
    locked must stop being retrievable on the very next turn, not whenever a
    cache happens to expire.
    """
    scan = VaultScan()
    for path in iter_markdown(vault):
        if scan.scanned >= limit:
            break
        scan.scanned += 1
        note = read_note(path, vault)
        scan.notes.append(note)
        if note.error:
            scan.problems.append(note)
    return scan


def render_note(topics: Sequence[str], body: str, extra: dict | None = None) -> str:
    """Serialize a note with frontmatter, for anything Akira writes.

    Always emits a `topics:` list, even when empty. An empty list is explicit
    and stays invisible to retrieval; omitting the key entirely looks like an
    oversight and invites someone to "fix" it by making untagged notes visible.
    """
    meta: dict = {"topics": list(topics)}
    if extra:
        meta.update(extra)
    dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{dumped}---\n\n{body.lstrip()}"


def topics_of(notes: Iterable[Note]) -> tuple[str, ...]:
    seen: set[str] = set()
    for note in notes:
        seen.update(note.topics)
    return tuple(sorted(seen))
