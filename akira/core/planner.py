"""The calendar kept in Akira, on this computer and nowhere else.

Google's sign-in for a calendar expired every week, and with it the calendar.
This one needs no account: events are kept in `calendar.json` in the settings
folder, and nothing about them is sent anywhere. It does not sync to a phone;
that is what being local costs.

Named `planner` rather than `calendar`, which is Python's, and apart from
`connect.gcal`, which is Google's.

Times are the person's own, as they say them: an event at 15:00 is at 15:00 on
this computer's clock, with no time zone kept. An all-day event has dates, and
its end is the last day it covers.

An event may repeat: every day, week, fortnight, month or year, until a date or
for good. A month without the day (the 31st) has it on its last day, and 29
February falls on the 28th in other years, so rent due on the 31st is not lost
in the months without one.

A reminder is so many minutes before the start; for an all-day event, before
nine in the morning of its day. `PlannerStore.due` says which are due, and what
has been given is kept so none is given twice. One whose event is already over
when Akira opens is not given late.
"""

from __future__ import annotations

import calendar as _months
import contextlib
import json
import os
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator

from akira.core import files
from akira.core.config import config_dir

MAX_TITLE = 200
MAX_WHERE = 200
MAX_NOTES = 2_000

#: The most events kept. A calendar that full is a mistake in a loop, not a life.
MAX_EVENTS = 5_000

#: The longest one event may last. Longer is almost always a slip of the month.
MAX_SPAN = timedelta(days=31)

#: How long an event given no end lasts.
DEFAULT_LENGTH = timedelta(hours=1)

#: How an event may repeat; "" for once.
REPEATS = ("", "daily", "weekly", "fortnightly", "monthly", "yearly")

#: The longest a reminder may come before its event: four weeks.
MAX_REMIND_MINUTES = 28 * 24 * 60

#: When in the day an all-day event's reminder is counted back from.
ALL_DAY_HOUR = 9

#: The most occurrences one look returns.
MAX_OCCURRENCES = 2_000


class PlannerError(ValueError):
    """Something about an event that cannot be kept, said for the person."""


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    start: date
    """A date for an all-day event, otherwise a date and time, with no time zone."""
    end: date
    """As `start`. For an all-day event, the last day it covers."""
    where: str = ""
    notes: str = ""
    repeat: str = ""
    """One of `REPEATS`."""
    until: date | None = None
    """The last day it repeats on, or None for no end."""
    remind: int | None = None
    """Minutes before the start a notice is shown, or None for none."""
    reminded: str = ""
    """The start of the last occurrence a reminder was given for."""
    created: float = 0.0
    changed: float = 0.0

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)

    @property
    def length(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True)
class Occurrence:
    """One time an event happens: the event itself, or one turn of a repeating one."""

    event: Event
    start: date
    end: date

    @property
    def first_day(self) -> date:
        return self.start.date() if isinstance(self.start, datetime) else self.start

    @property
    def last_day(self) -> date:
        if not isinstance(self.end, datetime):
            return self.end
        # An event ending at midnight does not reach into the day it ends on.
        ends = self.end - timedelta(microseconds=1) if self.end > self.start else self.end
        return ends.date()

    @property
    def remind_at(self) -> datetime | None:
        """When its reminder is due, or None if it has none."""
        if self.event.remind is None:
            return None
        begins = (self.start if isinstance(self.start, datetime)
                  else datetime(self.start.year, self.start.month, self.start.day, ALL_DAY_HOUR))
        return begins - timedelta(minutes=self.event.remind)

    @property
    def over_at(self) -> datetime:
        """When it is over, after which a reminder is not worth giving."""
        if isinstance(self.end, datetime):
            return self.end
        return datetime(self.end.year, self.end.month, self.end.day) + timedelta(days=1)


# -- what the person says, read and checked ------------------------------------------------------


def moment(text, what: str = "a start") -> date:
    """A date, or a date and time, from \a text: 2026-10-02 or 2026-10-02T15:00.

    A time given with a zone is turned to this computer's own and the zone dropped.
    Raises `PlannerError` for anything else.
    """
    if isinstance(text, datetime):
        return _local(text)
    if isinstance(text, date):
        return text
    said = " ".join(str(text or "").split())
    if not said:
        raise PlannerError(f"Give {what}: a date such as 2026-10-02, or a date and time such "
                           "as 2026-10-02T15:00.")
    try:
        if len(said) <= 10:
            return date.fromisoformat(said)
        return _local(datetime.fromisoformat(said.replace(" ", "T", 1)))
    except ValueError:
        raise PlannerError(f"{said!r} is not a date or a date and time this can read. Write "
                           "2026-10-02, or 2026-10-02T15:00.") from None


def _local(when: datetime) -> datetime:
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when.replace(second=0, microsecond=0)


def span(start, end="") -> tuple[date, date]:
    """When an event begins and ends, from what was said. Checked.

    With no end, a timed event lasts an hour and an all-day one its day.
    """
    begins = moment(start)
    timed = isinstance(begins, datetime)
    if end is None or (isinstance(end, str) and not end.strip()):
        return begins, (begins + DEFAULT_LENGTH if timed else begins)
    ends = moment(end, "an end")
    if isinstance(ends, datetime) != timed:
        raise PlannerError("The start and the end are both dates, for all day, or both dates "
                           "with times.")
    if ends < begins or (timed and ends == begins):
        raise PlannerError("The end is before the start." if ends < begins
                           else "The end is the same as the start.")
    if ends - begins > MAX_SPAN:
        raise PlannerError(f"An event lasts at most {MAX_SPAN.days} days. Check the month and "
                           "the year.")
    return begins, ends


def _line(text, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def draft(title, start, end="", *, where="", notes="", repeat="", until="",
          remind=None, ident: str = "") -> Event:
    """An event as it will be kept, from what was said. Raises `PlannerError`."""
    name = _line(title, MAX_TITLE)
    if not name:
        raise PlannerError("An event needs a title.")
    begins, ends = span(start, end)
    how = str(repeat or "").strip().lower()
    if how in ("none", "once", "no", "never"):
        how = ""
    if how not in REPEATS:
        raise PlannerError(f"{repeat!r} is not a way to repeat. Use daily, weekly, fortnightly, "
                           "monthly or yearly, or leave it out for once.")
    last = None
    if until not in (None, ""):
        last = moment(until, "a last day")
        last = last.date() if isinstance(last, datetime) else last
        if not how:
            raise PlannerError("A last day is for an event that repeats.")
        if last < _day(begins):
            raise PlannerError("The last day it repeats on is before it starts.")
    if how and ends - begins >= _step_floor(how):
        raise PlannerError("It lasts longer than the gap between its repeats.")
    minutes = None
    if remind not in (None, ""):
        try:
            minutes = int(remind)
        except (TypeError, ValueError):
            raise PlannerError("A reminder is a number of minutes before the start.") from None
        if not 0 <= minutes <= MAX_REMIND_MINUTES:
            raise PlannerError("A reminder is at most four weeks before the start.")
    now = time.time()
    return Event(id=ident or secrets.token_hex(8), title=name, start=begins, end=ends,
                 where=_line(where, MAX_WHERE), notes=str(notes or "").strip()[:MAX_NOTES],
                 repeat=how, until=last, remind=minutes, created=now, changed=now)


def _day(when: date) -> date:
    return when.date() if isinstance(when, datetime) else when


def _step_floor(repeat: str) -> timedelta:
    """The shortest gap between two turns of an event repeating so."""
    return {"daily": timedelta(days=1), "weekly": timedelta(days=7),
            "fortnightly": timedelta(days=14), "monthly": timedelta(days=28),
            "yearly": timedelta(days=365)}[repeat]


# -- when it happens -------------------------------------------------------------------------------


def _shifted(when: date, months: int) -> date:
    """\a when moved on by \a months, on the same day of the month or its last."""
    index = when.year * 12 + when.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    day = min(when.day, _months.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)


def _starts(event: Event, first: date) -> Iterator[date]:
    """Each start of \a event, in order, from the last one before \a first on."""
    begins = event.start
    if not event.repeat:
        yield begins
        return
    days = {"daily": 1, "weekly": 7, "fortnightly": 14}.get(event.repeat)
    if days:
        # Straight to the turn before the span, however long it has repeated.
        behind = (first - _day(begins)).days - event.length.days - 1
        turn = max(0, behind // days)
        while True:
            yield begins + timedelta(days=days * turn)
            turn += 1
    months = 1 if event.repeat == "monthly" else 12
    turn = max(0, ((first.year - begins.year) * 12 + first.month - begins.month) // months - 1)
    while True:
        yield _shifted(begins, months * turn)
        turn += 1


def occurrences(event: Event, first: date, last: date) -> list[Occurrence]:
    """Each time \a event happens on a day from \a first to \a last, both included."""
    found: list[Occurrence] = []
    for begins in _starts(event, first):
        day = _day(begins)
        if day > last or (event.until is not None and day > event.until):
            break
        turn = Occurrence(event, begins, begins + event.length)
        if turn.last_day >= first:
            found.append(turn)
        if len(found) >= MAX_OCCURRENCES:
            break
    return found


def _order(turn: Occurrence):
    # All-day events first in their day, then by time, then by title.
    timed = isinstance(turn.start, datetime)
    return (turn.first_day, timed, turn.start if timed else turn.first_day,
            turn.event.title.lower())


# -- for people ------------------------------------------------------------------------------------


def when(start: date, end: date, *, year: bool = True) -> str:
    """When an event is, as the person reads it."""
    tail = " %Y" if year else ""
    if not isinstance(start, datetime):
        if end == start:
            return f"{start:%a} {start.day} {start:%b{tail}}, all day"
        return f"{start:%a} {start.day} {start:%b} to {end:%a} {end.day} {end:%b{tail}}, all day"
    if start.date() == end.date():
        return f"{start:%a} {start.day} {start:%b{tail}}, {start:%H:%M} to {end:%H:%M}"
    return (f"{start:%a} {start.day} {start:%b{tail}}, {start:%H:%M} to "
            f"{end:%a} {end.day} {end:%b{tail}}, {end:%H:%M}")


REPEAT_WORDS = {"": "", "daily": "every day", "weekly": "every week",
                "fortnightly": "every two weeks", "monthly": "every month",
                "yearly": "every year"}


def repeats(event: Event) -> str:
    """How \a event repeats, in words, or ""."""
    words = REPEAT_WORDS[event.repeat]
    if words and event.until is not None:
        words += f" until {event.until.day} {event.until:%b %Y}"
    return words


def reminder(minutes: int | None) -> str:
    """A reminder's lead, in words, or ""."""
    if minutes is None:
        return ""
    if minutes == 0:
        return "at the start"
    for size, word in ((10_080, "week"), (1_440, "day"), (60, "hour")):
        if minutes % size == 0:
            count = minutes // size
            return f"{count} {word}{'' if count == 1 else 's'} before"
    return f"{minutes} minute{'' if minutes == 1 else 's'} before"


# -- kept --------------------------------------------------------------------------------------------


def _written(when_: date | None) -> str:
    if when_ is None:
        return ""
    return when_.isoformat(timespec="minutes") if isinstance(when_, datetime) else when_.isoformat()


def _as_json(event: Event) -> dict:
    return {"id": event.id, "title": event.title, "start": _written(event.start),
            "end": _written(event.end), "where": event.where, "notes": event.notes,
            "repeat": event.repeat, "until": _written(event.until), "remind": event.remind,
            "reminded": event.reminded, "created": event.created, "changed": event.changed}


def _from_json(raw: dict) -> Event:
    made = draft(raw["title"], raw["start"], raw.get("end") or "", where=raw.get("where", ""),
                 notes=raw.get("notes", ""), repeat=raw.get("repeat", ""),
                 until=raw.get("until", ""), remind=raw.get("remind"),
                 ident=str(raw.get("id") or ""))
    return replace(made, reminded=str(raw.get("reminded") or ""),
                   created=float(raw.get("created") or 0.0),
                   changed=float(raw.get("changed") or 0.0))


_shared: dict[Path, "PlannerStore"] = {}
_sharing = threading.Lock()


def shared() -> "PlannerStore":
    """The one store for the person's own calendar, so that whoever listens for
    changes hears of every one, whether the person made it or an agent did."""
    path = config_dir() / "calendar.json"
    with _sharing:
        store = _shared.get(path)
        if store is None:
            store = _shared[path] = PlannerStore(path)
        return store


class PlannerStore:
    """`calendar.json` in the settings folder. Safe from any thread."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_dir() / "calendar.json"
        self._lock = threading.RLock()
        self._on_change: Callable[[], None] | None = None

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        """Called, from whichever thread changed it, after the calendar changes."""
        self._on_change = callback

    def _changed(self) -> None:
        callback = self._on_change
        if callback is not None:
            with contextlib.suppress(Exception):
                callback()

    # -- reading -------------------------------------------------------------------------------

    def events(self) -> list[Event]:
        """Every event kept, in the order they start. One that cannot be read is left out."""
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                listed = raw.get("events") if isinstance(raw, dict) else None
            except (OSError, ValueError):
                listed = None
        found = []
        for item in listed if isinstance(listed, list) else []:
            try:
                found.append(_from_json(item))
            except (PlannerError, KeyError, TypeError, ValueError, AttributeError):
                continue
        return sorted(found, key=lambda e: (_written(e.start), e.title.lower()))

    def get(self, ident: str) -> Event:
        """The event with \a ident. Raises `PlannerError` if there is none."""
        for event in self.events():
            if event.id == str(ident).strip():
                return event
        raise PlannerError("There is no event with that id. List the calendar for the ids.")

    def between(self, first: date, last: date) -> list[Occurrence]:
        """Everything that happens on a day from \a first to \a last, in order."""
        found: list[Occurrence] = []
        for event in self.events():
            found.extend(occurrences(event, first, last))
        return sorted(found, key=_order)[:MAX_OCCURRENCES]

    def due(self, now: datetime) -> list[Occurrence]:
        """Each occurrence whose reminder is due at \a now, not given yet and not over."""
        found = []
        today = now.date()
        # A reminder is at most four weeks before, so nothing later is due yet.
        ahead = today + timedelta(minutes=MAX_REMIND_MINUTES) + timedelta(days=1)
        for event in self.events():
            if event.remind is None:
                continue
            for turn in occurrences(event, today - timedelta(days=MAX_SPAN.days), ahead):
                at = turn.remind_at
                if (at is not None and at <= now < turn.over_at
                        and _written(turn.start) > event.reminded):
                    found.append(turn)
        return sorted(found, key=_order)

    # -- changing ------------------------------------------------------------------------------

    def add(self, event: Event) -> Event:
        with self._lock:
            kept = self.events()
            if len(kept) >= MAX_EVENTS:
                raise PlannerError(f"The calendar holds at most {MAX_EVENTS} events.")
            if any(other.id == event.id for other in kept):
                raise PlannerError("There is already an event with that id.")
            self._save(kept + [event])
        self._changed()
        return event

    def change(self, event: Event) -> Event:
        """Keep \a event in place of the one with its id. Its reminder is due again."""
        with self._lock:
            kept = self.events()
            was = next((other for other in kept if other.id == event.id), None)
            if was is None:
                raise PlannerError("There is no event with that id.")
            moved = (was.start, was.repeat, was.remind) != (event.start, event.repeat, event.remind)
            now = replace(event, created=was.created, changed=time.time(),
                          reminded="" if moved else was.reminded)
            self._save([now if other.id == event.id else other for other in kept])
        self._changed()
        return now

    def remove(self, ident: str) -> Event:
        with self._lock:
            kept = self.events()
            gone = next((other for other in kept if other.id == str(ident).strip()), None)
            if gone is None:
                raise PlannerError("There is no event with that id.")
            self._save([other for other in kept if other.id != gone.id])
        self._changed()
        return gone

    def reminded(self, turn: Occurrence) -> None:
        """Note that \a turn's reminder was given, so it is not given again."""
        with self._lock:
            kept = self.events()
            self._save([replace(other, reminded=_written(turn.start))
                        if other.id == turn.event.id else other for other in kept])

    def _save(self, events: list[Event]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "events": [_as_json(e) for e in events]}, stream,
                          ensure_ascii=False, indent=1)
            files.replace(temporary, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise


# -- reminders, given as notices -----------------------------------------------------------------

#: How often reminders are looked for.
POLL_S = 20.0

#: The notice's title.
NOTICE_TITLE = "Calendar"


def _until(start: date, now: datetime) -> str:
    """How far off \a start is, in words: "now", "in 30 minutes", "tomorrow"."""
    if not isinstance(start, datetime):
        days = (start - now.date()).days
        return "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"
    minutes = round((start - now).total_seconds() / 60)
    if minutes <= 0:
        return "now" if minutes > -2 else "started"
    if minutes < 60:
        return f"in {minutes} minute{'' if minutes == 1 else 's'}"
    if minutes < 24 * 60:
        hours, rest = divmod(minutes, 60)
        return (f"in {hours} hour{'' if hours == 1 else 's'}"
                + (f" {rest} minutes" if rest and hours < 3 else ""))
    days = (start.date() - now.date()).days
    return "tomorrow" if days == 1 else f"in {days} days"


def notice(turn: Occurrence, now: datetime) -> str:
    """What a reminder of \a turn says."""
    event = turn.event
    text = f"{event.title}, {_until(turn.start, now)}: {when(turn.start, turn.end, year=False)}"
    return text + (f", at {event.where}" if event.where else "") + "."


class Reminders:
    """Gives each reminder that is due, once, as a notice.

    Only while notices are allowed (`allowed`): one due while they are not is
    kept, and given when they are if its event is not over by then.
    """

    def __init__(self, store: PlannerStore, *, notify: Callable[[str, str], None],
                 allowed: Callable[[], bool],
                 clock: Callable[[], datetime] = datetime.now,
                 record: Callable[[str], None] | None = None) -> None:
        self._store = store
        self._notify = notify
        self._allowed = allowed
        self._clock = clock
        # Called with each notice's title, for the activity log.
        self._record = record

    def poll(self) -> int:
        """Show a notice for each reminder due now. How many were shown."""
        now = self._clock()
        due = self._store.due(now)
        if not due or not self._allowed():
            return 0
        for turn in due:
            self._notify(NOTICE_TITLE, notice(turn, now))
            self._store.reminded(turn)
            if self._record is not None:
                with contextlib.suppress(Exception):
                    self._record(turn.event.title)
        return len(due)


class ReminderService:
    """The thread that looks for reminders that are due."""

    def __init__(self, reminders: Reminders, *, interval_s: float = POLL_S) -> None:
        self._reminders = reminders
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="calendar-reminders",
                                        daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            # The thread must outlive any one look.
            with contextlib.suppress(Exception):
                self._reminders.poll()
            self._stop.wait(self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
