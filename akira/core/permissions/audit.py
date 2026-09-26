"""An append-only record of everything the agents actually did.

One line of JSON per event. Not a debug log — a log you can hand to someone and
say "this is what it did while I was out". That means it has to be complete
(every tool call, refused ones included), readable, and safe to keep: a record
of an agent's actions that quietly contains your API keys is worse than no
record at all.

Refusals are logged as loudly as successes. A permission system whose denials
are invisible cannot be reviewed, and the pattern of what an agent *tried* to
do is often more interesting than what it managed.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from akira.core.config import config_dir

#: Argument names whose values never reach the log, matched case-insensitively
#: as substrings. Deliberately broad: a false positive costs one redacted
#: field, a false negative writes a credential to disk in plain text.
_SECRET_HINTS = (
    "password", "passwd", "secret", "token", "api_key", "apikey", "key",
    "authorization", "auth", "cookie", "session", "credential", "pin",
    "private", "signature", "otp",
)

#: Long values are trimmed. The log records *what was done*, not a second copy
#: of every file the agent read.
_MAX_VALUE = 400

#: Roll over past this. Keeps one previous file, so the log cannot grow without
#: bound on a machine nobody is watching.
_MAX_BYTES = 8 * 1024 * 1024

REDACTED = "[redacted]"


def _looks_secret(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _SECRET_HINTS)


def redact(value: Any, *, key: str = "") -> Any:
    """Strip secrets and trim bulk, recursively.

    Applied to every argument and every result before writing. Redaction is
    decided by the *name*, so a token still counts as a token when it arrives
    nested three dictionaries deep.
    """
    if key and _looks_secret(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value[:20]]
    if isinstance(value, str):
        return value if len(value) <= _MAX_VALUE else value[:_MAX_VALUE] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


@dataclass(frozen=True, slots=True)
class Event:
    """One thing that happened."""

    at: float
    kind: str
    """`tool`, `grant`, `revoke`, `confirm`, `audit`."""

    actor: str
    """Which agent, or `user` when a person did it."""

    action: str
    """Tool name, or capability id for permission changes."""

    allowed: bool
    detail: dict = field(default_factory=dict)
    duration_ms: int = 0
    error: str = ""

    def to_json(self) -> dict:
        return {
            "at": round(self.at, 3),
            "kind": self.kind,
            "actor": self.actor,
            "action": self.action,
            "allowed": self.allowed,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class AuditLog:
    """The log. Safe to call from any thread."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else config_dir() / "audit.jsonl"
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    # -- writing ------------------------------------------------------------

    def record(self, event: Event) -> None:
        """Append one event.

        Never raises. A failure to log must not take down the action being
        logged, and must not become a way to break the application by making
        its log directory unwritable.
        """
        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed()
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event.to_json(), ensure_ascii=False) + "\n")
        except OSError:
            pass

    def tool_call(self, actor: str, tool: str, arguments: dict, *,
                  allowed: bool, capability: str = "", scope: str = "",
                  duration_ms: int = 0, error: str = "",
                  result: Any = None) -> None:
        """Record one tool invocation, permitted or refused."""
        detail: dict[str, Any] = {"arguments": redact(arguments)}
        if capability:
            detail["capability"] = capability
        if scope:
            detail["scope"] = redact(scope, key="scope")
        if result is not None:
            detail["result"] = redact(result)
        self.record(Event(time.time(), "tool", actor, tool, allowed,
                          detail, duration_ms, error))

    def permission_change(self, capability: str, *, granted: bool,
                          scopes: tuple[str, ...] = (), note: str = "") -> None:
        self.record(Event(time.time(), "grant" if granted else "revoke",
                          "user", capability, granted,
                          {"scopes": list(scopes), "note": note}))

    def confirmation(self, actor: str, action: str, *, approved: bool,
                     summary: str = "") -> None:
        """Record a person's answer to an irreversible-action prompt."""
        self.record(Event(time.time(), "confirm", actor, action, approved,
                          {"summary": redact(summary, key="summary")}))

    def _rotate_if_needed(self) -> None:
        try:
            if self._path.exists() and self._path.stat().st_size > _MAX_BYTES:
                previous = self._path.with_suffix(".1.jsonl")
                previous.unlink(missing_ok=True)
                self._path.replace(previous)
        except OSError:
            pass

    # -- reading ------------------------------------------------------------

    def read(self, limit: int = 500, kind: str = "") -> list[Event]:
        """The most recent events, newest last.

        A malformed line is skipped rather than raising: a log with one bad
        line in it is still worth reading, and refusing to show any of it
        because of a partial write is exactly when you most want to look.
        """
        if not self._path.is_file():
            return []
        events: list[Event] = []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if kind and raw.get("kind") != kind:
                        continue
                    events.append(Event(
                        at=float(raw.get("at", 0)),
                        kind=str(raw.get("kind", "")),
                        actor=str(raw.get("actor", "")),
                        action=str(raw.get("action", "")),
                        allowed=bool(raw.get("allowed", False)),
                        detail=raw.get("detail") or {},
                        duration_ms=int(raw.get("duration_ms", 0)),
                        error=str(raw.get("error", "")),
                    ))
        except OSError:
            return []
        return events[-limit:]

    def since(self, when: float) -> Iterator[Event]:
        for event in self.read(limit=100_000):
            if event.at >= when:
                yield event
