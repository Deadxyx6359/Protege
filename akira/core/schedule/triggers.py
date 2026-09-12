"""When a job runs.

Times are **wall-clock local time**, held as naive datetimes and turned into an
instant only at the last moment with `datetime.timestamp()`, which asks the
operating system. So a job set for 07:30 still runs at 07:30 on the morning
the clocks change, rather than an hour early or late. Doing the arithmetic on
instants instead is simpler and wrong twice a year.

Two consequences worth knowing. A daily job set inside the hour the clocks
skip is resolved by the operating system rather than dropped. And on the night
the clocks go back, a job set inside the repeated hour runs once, not twice,
because the next occurrence is always computed from after the run.

Event triggers have no time at all; they fire when something is published to
the scheduler, subject to a cooldown.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import ClassVar

from .cron import CronExpr

#: The shortest interval a repeating job may have. Anything faster is a busy
#: loop wearing a schedule, and belongs to an event trigger instead.
MIN_INTERVAL_S = 60

#: The shortest cooldown an event trigger may have. Without one, a burst of
#: a thousand file-changed events is a thousand agent runs.
MIN_COOLDOWN_S = 5

_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class TriggerError(ValueError):
    """A trigger that cannot exist, or a stored one that cannot be read."""


def _hhmm(text: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = str(text).split(":")
        hour, minute = int(hour_text), int(minute_text)
    except ValueError:
        raise TriggerError(f"{text!r} is not a time like 07:30") from None
    _check_time(hour, minute)
    return hour, minute


def _check_time(hour: int, minute: int) -> None:
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise TriggerError(f"{hour:02d}:{minute:02d} is not a time of day")


def _ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


class Trigger:
    """Base for every trigger kind."""

    kind: ClassVar[str] = ""
    is_event: ClassVar[bool] = False

    def next_after(self, after: datetime) -> datetime | None:
        """The first occurrence strictly after \a after, or None if none."""
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError

    def to_json(self) -> dict:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Once(Trigger):
    at: datetime
    kind: ClassVar[str] = "once"

    def next_after(self, after: datetime) -> datetime | None:
        return self.at if self.at > after else None

    def describe(self) -> str:
        return f"Once, on {self.at.strftime('%d %b %Y at %H:%M')}"

    def to_json(self) -> dict:
        return {"kind": self.kind, "at": self.at.isoformat(timespec="minutes")}


@dataclass(frozen=True, slots=True)
class Every(Trigger):
    seconds: int
    anchor: float = 0.0
    """The instant occurrences are counted from, so the interval never drifts
    by however long each run happened to take."""
    kind: ClassVar[str] = "every"

    def __post_init__(self) -> None:
        if self.seconds < MIN_INTERVAL_S:
            raise TriggerError(
                f"a repeating job must be at least {MIN_INTERVAL_S} seconds apart")

    def next_after(self, after: datetime) -> datetime | None:
        instant = after.timestamp()
        if instant < self.anchor:
            return datetime.fromtimestamp(self.anchor)
        count = math.floor((instant - self.anchor) / self.seconds) + 1
        return datetime.fromtimestamp(self.anchor + count * self.seconds)

    def describe(self) -> str:
        for unit, size in (("week", 604800), ("day", 86400),
                           ("hour", 3600), ("minute", 60)):
            if self.seconds % size == 0:
                count = self.seconds // size
                return f"Every {unit}" if count == 1 else f"Every {count} {unit}s"
        return f"Every {self.seconds} seconds"

    def to_json(self) -> dict:
        return {"kind": self.kind, "seconds": self.seconds, "anchor": self.anchor}


@dataclass(frozen=True, slots=True)
class Daily(Trigger):
    hour: int
    minute: int = 0
    kind: ClassVar[str] = "daily"

    def __post_init__(self) -> None:
        _check_time(self.hour, self.minute)

    def next_after(self, after: datetime) -> datetime | None:
        candidate = after.replace(hour=self.hour, minute=self.minute,
                                  second=0, microsecond=0)
        if candidate <= after:
            # Naive arithmetic is wall-clock arithmetic: one day later at the
            # same time on the clock, whatever the offset does overnight.
            candidate += timedelta(days=1)
        return candidate

    def describe(self) -> str:
        return f"Every day at {self.hour:02d}:{self.minute:02d}"

    def to_json(self) -> dict:
        return {"kind": self.kind, "time": f"{self.hour:02d}:{self.minute:02d}"}


@dataclass(frozen=True, slots=True)
class Weekly(Trigger):
    days: frozenset[int]
    """0 is Monday, as in Python."""
    hour: int
    minute: int = 0
    kind: ClassVar[str] = "weekly"

    def __post_init__(self) -> None:
        if not self.days or not all(0 <= d <= 6 for d in self.days):
            raise TriggerError("a weekly job needs at least one day, Monday=0 to Sunday=6")
        _check_time(self.hour, self.minute)

    def next_after(self, after: datetime) -> datetime | None:
        for offset in range(8):
            day = after + timedelta(days=offset)
            if day.weekday() not in self.days:
                continue
            candidate = day.replace(hour=self.hour, minute=self.minute,
                                    second=0, microsecond=0)
            if candidate > after:
                return candidate
        return None

    def describe(self) -> str:
        when = f"{self.hour:02d}:{self.minute:02d}"
        if self.days == frozenset(range(7)):
            return f"Every day at {when}"
        if self.days == frozenset(range(5)):
            return f"Weekdays at {when}"
        if self.days == frozenset({5, 6}):
            return f"Weekends at {when}"
        names = ", ".join(_DAY_NAMES[d] for d in sorted(self.days))
        return f"{names} at {when}"

    def to_json(self) -> dict:
        return {"kind": self.kind, "days": sorted(self.days),
                "time": f"{self.hour:02d}:{self.minute:02d}"}


@dataclass(frozen=True, slots=True)
class Monthly(Trigger):
    day: int
    """1–31. A day a month does not have means that month's last day: "the
    31st" still runs in February, because nobody asking for a monthly job on
    the 31st wants it skipped five months a year."""
    hour: int
    minute: int = 0
    kind: ClassVar[str] = "monthly"

    def __post_init__(self) -> None:
        if not 1 <= self.day <= 31:
            raise TriggerError("a monthly job needs a day from 1 to 31")
        _check_time(self.hour, self.minute)

    def next_after(self, after: datetime) -> datetime | None:
        year, month = after.year, after.month
        for _ in range(14):
            last = calendar.monthrange(year, month)[1]
            candidate = datetime(year, month, min(self.day, last),
                                 self.hour, self.minute)
            if candidate > after:
                return candidate
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return None

    def describe(self) -> str:
        when = f"{self.hour:02d}:{self.minute:02d}"
        if self.day > 28:
            return (f"Monthly on the {_ordinal(self.day)} (or the last day, "
                    f"in shorter months) at {when}")
        return f"Monthly on the {_ordinal(self.day)} at {when}"

    def to_json(self) -> dict:
        return {"kind": self.kind, "day": self.day,
                "time": f"{self.hour:02d}:{self.minute:02d}"}


@dataclass(frozen=True, slots=True)
class Cron(Trigger):
    expr: str
    _parsed: CronExpr = field(init=False, repr=False, compare=False)
    kind: ClassVar[str] = "cron"

    def __post_init__(self) -> None:
        object.__setattr__(self, "_parsed", CronExpr.parse(self.expr))

    def next_after(self, after: datetime) -> datetime | None:
        return self._parsed.next_after(after)

    def describe(self) -> str:
        return f"On the schedule “{self.expr}”"

    def to_json(self) -> dict:
        return {"kind": self.kind, "expr": self.expr}


@dataclass(frozen=True, slots=True)
class OnEvent(Trigger):
    name: str
    """Exact event name, or a prefix ending in `.*` — `file.*` matches
    `file.changed` and `file.created`."""
    match: dict = field(default_factory=dict)
    """Payload fields that must be equal for the job to fire."""
    cooldown_s: int = 60
    kind: ClassVar[str] = "event"
    is_event: ClassVar[bool] = True

    def __post_init__(self) -> None:
        if not self.name or self.name in ("*", ".*"):
            raise TriggerError("an event trigger needs an event name")
        if self.cooldown_s < MIN_COOLDOWN_S:
            raise TriggerError(
                f"an event trigger needs a cooldown of at least {MIN_COOLDOWN_S} seconds")

    def next_after(self, after: datetime) -> datetime | None:
        return None

    def matches(self, name: str, payload: dict) -> bool:
        if self.name.endswith(".*"):
            if not name.startswith(self.name[:-1]):
                return False
        elif name != self.name:
            return False
        return all(payload.get(key) == value for key, value in self.match.items())

    def describe(self) -> str:
        return f"When “{self.name}” happens"

    def to_json(self) -> dict:
        return {"kind": self.kind, "name": self.name, "match": dict(self.match),
                "cooldown": self.cooldown_s}


def trigger_from_json(raw: object) -> Trigger:
    """Rebuild a stored trigger. Raises `TriggerError` on anything unexpected.

    Unknown kinds are refused rather than guessed at: a job whose trigger is
    not understood must not run on a schedule nobody chose.
    """
    if not isinstance(raw, dict):
        raise TriggerError("a trigger must be an object")
    kind = raw.get("kind")
    try:
        if kind == "once":
            return Once(datetime.fromisoformat(str(raw["at"])))
        if kind == "every":
            return Every(int(raw["seconds"]), float(raw.get("anchor", 0.0)))
        if kind == "daily":
            return Daily(*_hhmm(raw["time"]))
        if kind == "weekly":
            return Weekly(frozenset(int(d) for d in raw["days"]), *_hhmm(raw["time"]))
        if kind == "monthly":
            return Monthly(int(raw["day"]), *_hhmm(raw["time"]))
        if kind == "cron":
            return Cron(str(raw["expr"]))
        if kind == "event":
            match = raw.get("match") or {}
            if not isinstance(match, dict):
                raise TriggerError("an event match must be an object")
            return OnEvent(str(raw["name"]), dict(match), int(raw.get("cooldown", 60)))
    except TriggerError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise TriggerError(f"malformed {kind} trigger: {exc}") from None
    raise TriggerError(f"unknown trigger kind {kind!r}")
