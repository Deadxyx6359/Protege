"""The live session memory file.

During a session MAIN maintains a markdown scratch file at
`projects/<project>/memory/live/<session-id>.md`, written as the conversation
proceeds. Two mechanisms fill it, and both are required:

1. **Model-proposed.** MAIN calls `remember(content, topic, importance)` when it
   spots something worth keeping. An 8B model is unreliable at noticing, which
   is exactly why mechanism 2 exists rather than being a nicety.
2. **User-pinned.** The user pins a message or types a note directly. Explicit,
   and always honored.

**Every write passes tripwires and the auditor before it touches disk.** This is
the leak vector the brief singles out and it deserves restating: a memory write
is not a private scratchpad. Whatever lands in the vault becomes retrievable
later, at which point it is just a note like any other -- so if MAIN writes
locked-topic content here, Layer 3 will hand it back next week and the gate will
have been bypassed by the model's own notes. Skipping the check for writes
because "it is only memory" is the single most tempting shortcut in this
codebase and the one that would quietly undo it.

The whole file is rewritten on each write. Live files are small (a session's
worth of notes), and append-only I/O on a file that also carries a frontmatter
block whose `topics` list changes with every entry is more trouble than it
saves.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from ..chat import BlockDetail
from ..lock.pipeline import GateResult, OutputGate
from ..projects import Project, get_project
from ..schemas import Manifest, SchemaError, normalize_topic, utcnow_iso
from ..security.paths import TierCapabilities, capabilities
from ..store import write_text
from ..vault import render_note

ENTRY_HEADER_RE = re.compile(
    r"^##\s+(?P<at>\S+)\s+\|\s+(?P<source>proposed|pinned)\s+\|\s+importance\s+(?P<importance>\d+)"
    r"(?:\s+\|\s+topics:\s*(?P<topics>[a-z0-9_,\s]*))?\s*$",
    re.MULTILINE,
)

SOURCE_PROPOSED = "proposed"
SOURCE_PINNED = "pinned"

MAX_ENTRY_CHARS = 4000


def new_session_id() -> str:
    """A short, sortable, collision-resistant session id.

    Timestamp for human sortability plus random bytes for uniqueness.
    Deliberately not `uuid` -- `uuid.getnode()` reads the machine's MAC address,
    and `verify_offline.py` lists the module as forbidden for that reason.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{secrets.token_hex(3)}"


@dataclass(frozen=True)
class MemoryEntry:
    content: str
    topics: tuple[str, ...] = ()
    source: str = SOURCE_PINNED
    importance: int = 3
    at: str = ""
    session_id: str = ""

    def render(self) -> str:
        topics = ", ".join(self.topics)
        header = f"## {self.at} | {self.source} | importance {self.importance}"
        if topics:
            header += f" | topics: {topics}"
        return f"{header}\n\n{self.content.strip()}\n"


@dataclass(frozen=True)
class MemoryWriteResult:
    """Outcome of one attempted write."""

    accepted: bool
    entry: MemoryEntry | None = None
    reason: str = ""
    detail: BlockDetail | None = None

    @property
    def blocked_by_gate(self) -> bool:
        return self.detail is not None


class LiveMemory:
    """The current session's scratch file."""

    def __init__(
        self,
        vault: Path,
        project: str,
        manifest: Manifest,
        gate: OutputGate,
        *,
        session_id: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.vault = Path(vault)
        self.project: Project = get_project(self.vault, project)
        self.manifest = manifest
        self.gate = gate
        self.session_id = session_id or new_session_id()
        self.enabled = enabled
        self.entries: list[MemoryEntry] = []
        self.started_at = utcnow_iso()
        self.rejected: list[MemoryWriteResult] = []

    @property
    def caps(self) -> TierCapabilities:
        return capabilities(self.manifest.trust_tier)

    @property
    def path(self) -> Path:
        return self.project.memory_live_dir / f"{self.session_id}.md"

    @property
    def topics(self) -> tuple[str, ...]:
        """Union of every entry's topics.

        This becomes the file's frontmatter, and visibility requires *all* of a
        note's topics to be unlocked. So re-locking any single topic hides the
        entire live file rather than just the entries carrying it. That is the
        fail-closed reading and it is intentional: entries in one file are not
        separable by retrieval, which returns chunks that may span them.
        """
        seen: set[str] = set()
        for entry in self.entries:
            seen.update(entry.topics)
        return tuple(sorted(seen))

    # -- policy -------------------------------------------------------------

    def may_write(self, source: str) -> tuple[bool, str]:
        if not self.enabled:
            return False, "memory is disabled in settings"
        caps = self.caps
        if source == SOURCE_PROPOSED and not caps.model_proposed_memory:
            return False, (
                f"model-proposed memory is not available at {caps.label}; "
                "raise the trust tier to 2 to let the model write to the vault"
            )
        if source == SOURCE_PINNED and not caps.user_pinned_memory:
            return False, (
                f"memory writes are disabled at {caps.label}; the model has not yet earned "
                "write access to the vault"
            )
        return True, ""

    # -- writing ------------------------------------------------------------

    def write(
        self,
        content: str,
        *,
        topics: Sequence[str] = (),
        source: str = SOURCE_PINNED,
        importance: int = 3,
        user_prompt: str = "",
    ) -> MemoryWriteResult:
        """Gate, then persist. Returns without writing if anything objects."""
        content = (content or "").strip()
        if not content:
            return MemoryWriteResult(False, reason="nothing to write")
        if len(content) > MAX_ENTRY_CHARS:
            return MemoryWriteResult(
                False,
                reason=f"entry is {len(content)} characters, over the {MAX_ENTRY_CHARS} limit",
            )
        if source not in (SOURCE_PROPOSED, SOURCE_PINNED):
            return MemoryWriteResult(False, reason=f"unknown memory source {source!r}")

        allowed, why = self.may_write(source)
        if not allowed:
            return MemoryWriteResult(False, reason=why)

        try:
            normalized = tuple(sorted({normalize_topic(t) for t in topics}))
        except SchemaError as exc:
            return MemoryWriteResult(False, reason=f"invalid topic tag: {exc}")

        locked = self.manifest.all_locked(normalized)
        if locked:
            # Tagging a memory note with a locked topic would make it invisible
            # the instant it was written, which is harmless but incoherent --
            # and it usually means the model misunderstood what it is allowed to
            # record. Refuse rather than write an unreadable note.
            return MemoryWriteResult(
                False,
                reason=f"cannot tag a memory note with locked topic(s): {', '.join(locked)}",
            )

        # The gate. Same checks as a chat response, for the reason in the
        # module docstring.
        result: GateResult = self.gate.check(
            user_prompt or "(memory write)", content, allow_decline_shortcut=False
        )
        if not result.allowed:
            rejection = MemoryWriteResult(
                False,
                reason=f"blocked by the {result.layer} layer: {result.reason}",
                detail=result.to_block_detail(),
            )
            self.rejected.append(rejection)
            return rejection

        entry = MemoryEntry(
            content=content,
            topics=normalized,
            source=source,
            importance=max(1, min(5, int(importance))),
            at=utcnow_iso(),
            session_id=self.session_id,
        )
        self.entries.append(entry)
        self.flush()
        return MemoryWriteResult(True, entry=entry)

    def remove(self, index: int) -> bool:
        """Discard an entry before consolidation. Used by the memory panel."""
        if 0 <= index < len(self.entries):
            del self.entries[index]
            self.flush()
            return True
        return False

    def replace(self, index: int, content: str) -> bool:
        """Edit an entry's text in place.

        Not re-gated: the replacement text is typed by the user in the memory
        panel, and user-authored text is not model output. Gating it would mean
        the tripwire list censoring the user's own notes in their own vault.
        """
        if not (0 <= index < len(self.entries)):
            return False
        existing = self.entries[index]
        self.entries[index] = MemoryEntry(
            content=content.strip(),
            topics=existing.topics,
            source=SOURCE_PINNED,
            importance=existing.importance,
            at=utcnow_iso(),
            session_id=self.session_id,
        )
        self.flush()
        return True

    def flush(self) -> None:
        """Write the file, or delete it when the last entry is gone."""
        if not self.entries:
            if self.path.exists():
                self.path.unlink()
            return
        body = "\n".join(entry.render() for entry in self.entries)
        text = render_note(
            self.topics,
            body,
            extra={
                "session": self.session_id,
                "started": self.started_at,
                "kind": "live-memory",
                "project": self.project.name,
            },
        )
        write_text(self.path, text)

    # -- reading ------------------------------------------------------------

    def render_for_context(self, limit: int = 20) -> str:
        """The text injected at budget priority 5.

        Highest-importance entries first, so truncation loses the least
        valuable ones rather than the oldest.
        """
        if not self.entries:
            return ""
        ordered = sorted(self.entries, key=lambda e: (-e.importance, e.at))[:limit]
        return "\n".join(f"- {e.content.strip()}" for e in ordered)

    def summary(self) -> str:
        proposed = sum(1 for e in self.entries if e.source == SOURCE_PROPOSED)
        pinned = len(self.entries) - proposed
        bits = [f"{len(self.entries)} entr{'y' if len(self.entries) == 1 else 'ies'}"]
        if pinned:
            bits.append(f"{pinned} pinned")
        if proposed:
            bits.append(f"{proposed} proposed")
        if self.rejected:
            bits.append(f"{len(self.rejected)} blocked")
        return ", ".join(bits)


# --- the remember() tool ---------------------------------------------------


def remember_tool_description(unlocked_topics: Sequence[str] = ()) -> str:
    """The tool description, naming the exact topic ids that will be accepted.

    Without the list the model invents plausible-sounding narrower names --
    observed in testing: an answer about gravity proposed `topic: "gravity"`
    while only `physics` was unlocked. A memory write tagged with a topic that
    is not unlocked is refused, so the model appears to record something and
    nothing reaches disk. Naming the valid ids removes the guesswork.
    """
    if unlocked_topics:
        allowed = (
            "  topic:      MUST be exactly one of: " + ", ".join(unlocked_topics) + "\n"
            "              Use the id verbatim. Do not invent a narrower name --\n"
            "              a fact about gravity is recorded under 'physics' if that\n"
            "              is what is unlocked."
        )
    else:
        allowed = "  topic:      (no topics are unlocked, so do not call this tool)"
    return REMEMBER_TOOL_TEMPLATE.replace("{{TOPIC_RULE}}", allowed)


REMEMBER_TOOL_TEMPLATE = """\
You have one tool available.

remember(content, topic, importance)
  Record something worth keeping beyond this conversation.
  content:    one or two sentences, self-contained
{{TOPIC_RULE}}
  importance: 1 (minor) to 5 (essential)

To call it, add a line of exactly this form at the END of your reply, after
your answer:

REMEMBER: {"content": "...", "topic": "...", "importance": 3}

The REMEMBER line is IN ADDITION to your normal answer, never a replacement
for it. Always answer the user first; a reply that is only a REMEMBER line is
wrong. Only record durable facts: decisions, preferences, corrections,
conclusions. Do not record small talk or restate what is already in a note."""

# Back-compat: some callers and tests import the constant directly. It is the
# no-topics form, which is also the safe default.
REMEMBER_TOOL_DESCRIPTION = remember_tool_description(())

REMEMBER_CALL_RE = re.compile(r"^REMEMBER:\s*(\{.*\})\s*$", re.MULTILINE)


@dataclass
class ParsedRemember:
    content: str
    topic: str
    importance: int
    raw: str


def parse_remember_calls(text: str) -> tuple[list[ParsedRemember], str]:
    """Extract `REMEMBER:` lines from MAIN's output.

    Returns the parsed calls and the text with those lines removed, so the tool
    invocation does not appear in the reply the user reads.

    A line-oriented JSON convention rather than a full function-calling
    protocol: llama.cpp's grammar support varies by model and quantization, and
    a convention the model half-follows degrades into a missing memory note,
    which mechanism 2 exists to cover. Malformed calls are dropped silently
    here and surfaced in the memory panel instead.
    """
    calls: list[ParsedRemember] = []
    for match in REMEMBER_CALL_RE.finditer(text):
        import json

        try:
            payload = json.loads(match.group(1))
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        content = str(payload.get("content", "")).strip()
        topic = str(payload.get("topic", "")).strip()
        if not content or not topic:
            continue
        try:
            importance = int(payload.get("importance", 3))
        except (TypeError, ValueError):
            importance = 3
        calls.append(ParsedRemember(content=content, topic=topic, importance=importance, raw=match.group(0)))

    cleaned = REMEMBER_CALL_RE.sub("", text).strip()
    return calls, cleaned
