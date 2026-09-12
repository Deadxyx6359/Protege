"""The event stream an agent run produces.

Every agent emits these as it works, and everything downstream reads them: the
live activity view, the transcript, the after-the-fact scrub of a finished run.
One stream, so what you watch and what you replay cannot disagree.

Kept deliberately dumb — a list of facts with timestamps, no behaviour. Anything
that decides what an event *means* belongs where the decision is made, not here.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable


class Kind(Enum):
    """What happened. Named for what a person watching would call it."""

    STARTED = "started"
    """An agent began a task."""

    THINKING = "thinking"
    """The model is generating. Carries partial text while it streams."""

    TOOL_CALL = "tool_call"
    """An agent decided to use a tool, with these arguments."""

    TOOL_RESULT = "tool_result"
    """What the tool returned, or why it refused."""

    MESSAGE = "message"
    """One agent said something to another. The edges in the team graph."""

    ANSWER = "answer"
    """An agent finished and produced its result."""

    FAILED = "failed"
    """An agent stopped without an answer."""

    NOTE = "note"
    """Anything worth showing that is none of the above."""


@dataclass(frozen=True, slots=True)
class Event:
    """One thing that happened during a run."""

    at: float
    kind: Kind
    agent: str
    text: str = ""

    tool: str = ""
    arguments: dict = field(default_factory=dict)
    ok: bool = True

    to: str = ""
    """For MESSAGE: the agent on the receiving end."""

    step: int = 0

    def to_json(self) -> dict:
        return {
            "at": round(self.at, 3), "kind": self.kind.value, "agent": self.agent,
            "text": self.text, "tool": self.tool, "arguments": self.arguments,
            "ok": self.ok, "to": self.to, "step": self.step,
        }


class Trace:
    """Collects events and hands them to whoever is listening.

    Safe to write from a worker thread, which is where agents run. Listeners
    are called on that same thread, so a listener that touches the interface
    must marshal — the Qt bridge does exactly that.
    """

    def __init__(self, limit: int = 2000) -> None:
        self._events: deque[Event] = deque(maxlen=limit)
        self._listeners: list[Callable[[Event], None]] = []
        self._lock = threading.Lock()

    def listen(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        """Register a listener; returns the function that removes it."""
        with self._lock:
            self._listeners.append(callback)

        def stop() -> None:
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)

        return stop

    def emit(self, kind: Kind, agent: str, **fields) -> Event:
        event = Event(at=time.time(), kind=kind, agent=agent, **fields)
        with self._lock:
            self._events.append(event)
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - a bad listener must not stop the run
                pass
        return event

    def events(self, kind: Kind | None = None) -> list[Event]:
        with self._lock:
            events = list(self._events)
        return [e for e in events if kind is None or e.kind is kind]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def replay(self, into: Iterable[Callable[[Event], None]] | None = None) -> list[Event]:
        """Everything so far, for a listener that arrived late."""
        events = self.events()
        for callback in into or ():
            for event in events:
                try:
                    callback(event)
                except Exception:  # noqa: BLE001
                    pass
        return events
