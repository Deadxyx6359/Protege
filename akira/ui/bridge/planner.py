"""The calendar kept in Akira, as QML sees it (context name `Planner`).

Everything a month view, a week view and an event editor need: the days of a
month or a week with what is on each, an event whole, and adding, changing and
removing. What the person does here is their own act and needs no grant, as
typing in any calendar would not; `planner.read` and `planner.write` are for
agents and the chat's models, and `agentsRead` and `agentsChange` say whether
those are granted, for the screen to say so.

An agent's change arrives from its own thread; like the scheduler's, it crosses
to the UI thread through a private signal before anything QML is bound to moves.

Dates cross as text, `2026-10-02` and `2026-10-02T15:00`, never as JavaScript
dates: those carry a time zone, and the calendar has none.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from akira.core import agenda, planner
from akira.core.planner import Event, Occurrence, PlannerError, PlannerStore

#: The reminders the editor offers: minutes before, -1 for none.
REMINDERS = (-1, 0, 5, 10, 15, 30, 60, 120, 1_440, 2_880, 10_080)

#: The most days `upcoming` looks ahead.
MAX_UPCOMING_DAYS = 366


def _text(when: date | None) -> str:
    if when is None:
        return ""
    return when.isoformat(timespec="minutes") if isinstance(when, datetime) else when.isoformat()


def _event(event: Event) -> dict:
    return {"id": event.id, "title": event.title, "start": _text(event.start),
            "end": _text(event.end), "allDay": event.all_day, "where": event.where,
            "notes": event.notes, "repeat": event.repeat, "until": _text(event.until),
            "remind": -1 if event.remind is None else event.remind,
            "when": planner.when(event.start, event.end),
            "repeatWords": planner.repeats(event),
            "remindWords": planner.reminder(event.remind)}


def _turn(turn: Occurrence, day: date | None = None) -> dict:
    """One occurrence, as a row. With \a day, how it sits in that day: where it
    starts and ends in minutes from midnight, clipped to the day."""
    event = turn.event
    timed = isinstance(turn.start, datetime)
    row = {"id": event.id, "title": event.title, "allDay": not timed,
           "start": _text(turn.start), "end": _text(turn.end),
           "time": f"{turn.start:%H:%M}" if timed else "",
           "endTime": f"{turn.end:%H:%M}" if timed else "",
           "when": planner.when(turn.start, turn.end, year=False),
           "where": event.where, "notes": event.notes, "repeats": bool(event.repeat),
           "repeatWords": planner.repeats(event),
           "remind": -1 if event.remind is None else event.remind,
           "days": (turn.last_day - turn.first_day).days + 1}
    if day is not None:
        row["first"] = turn.first_day == day
        row["last"] = turn.last_day == day
        if timed:
            midnight = datetime(day.year, day.month, day.day)
            begins = max(turn.start, midnight)
            ends = min(turn.end, midnight + timedelta(days=1))
            row["startMinute"] = int((begins - midnight).total_seconds() // 60)
            row["endMinute"] = int((ends - midnight).total_seconds() // 60)
            # "09:00" on the day it starts; "" where it only carries on.
            row["time"] = f"{turn.start:%H:%M}" if row["first"] else ""
    return row


class PlannerBridge(QObject):
    """The calendar: what is on, and changing it."""

    #: Anything in the calendar changed. Ask again for whatever is on screen.
    changed = Signal()

    #: An event was added, with its id, so the screen can show it.
    added = Signal(str)

    #: Whether agents may read or change it changed.
    accessChanged = Signal()

    #: Private: carry a change from a worker thread to this one.
    _changedElsewhere = Signal()

    def __init__(self, store: PlannerStore | None = None, *,
                 policy: Callable[[], object] | None = None,
                 today: Callable[[], date] = date.today,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store if store is not None else planner.shared()
        self._policy = policy
        self._today = today
        self._revision = 0
        # No connection type given: direct within a thread, queued across.
        self._changedElsewhere.connect(self._bump)
        self._store.set_on_change(self._changedElsewhere.emit)

    @property
    def store(self) -> PlannerStore:
        return self._store

    def _bump(self) -> None:
        self._revision += 1
        self.changed.emit()

    # -- what is on --------------------------------------------------------------------------------

    @Property(int, notify=changed)
    def revision(self) -> int:
        """Goes up with every change: bind to it to ask again for what is shown."""
        return self._revision

    @Property(int, notify=changed)
    def count(self) -> int:
        """How many events are kept, a repeating one counted once."""
        return len(self._store.events())

    @Property(str, notify=changed)
    def today(self) -> str:
        """Today, as `2026-10-02`. Read again when a day or the calendar is asked for."""
        return self._today().isoformat()

    def _days(self, first: date, count: int, month: int | None = None) -> list:
        last = first + timedelta(days=count - 1)
        turns = self._store.between(first, last)
        today = self._today()
        days = []
        for ahead in range(count):
            day = first + timedelta(days=ahead)
            on = [t for t in turns if t.first_day <= day <= t.last_day]
            days.append({"date": day.isoformat(), "day": day.day, "weekday": f"{day:%a}",
                         "label": f"{day:%A} {day.day} {day:%B}",
                         "inMonth": month is None or day.month == month,
                         "today": day == today, "weekend": day.weekday() >= 5,
                         "events": [_turn(t, day) for t in on]})
        return days

    @Slot(int, int, result="QVariantList")
    @Slot(int, int, bool, result="QVariantList")
    def month(self, year: int, month: int, sunday_first: bool = False) -> list:
        """The six weeks that show \a month: 42 days, each `date`, `day`, `weekday`,
        `label`, `inMonth`, `today`, `weekend` and `events` (see `day`). Weeks
        start on Monday, or on Sunday with \a sunday_first. [] for a month that is not one."""
        try:
            first = date(int(year), int(month), 1)
        except (ValueError, OverflowError):
            return []
        back = (first.weekday() + 1) % 7 if sunday_first else first.weekday()
        return self._days(first - timedelta(days=back), 42, first.month)

    @Slot(str, result="QVariantList")
    @Slot(str, bool, result="QVariantList")
    def week(self, day: str, sunday_first: bool = False) -> list:
        """The seven days of the week \a day is in, as `month` gives days. A timed
        event also has `startMinute` and `endMinute`, from midnight, clipped to the day."""
        try:
            within = _a_day(day)
        except PlannerError:
            return []
        back = (within.weekday() + 1) % 7 if sunday_first else within.weekday()
        return self._days(within - timedelta(days=back), 7)

    @Slot(str, result="QVariantList")
    def day(self, day: str) -> list:
        """What is on \a day, all-day events first: each `id`, `title`, `allDay`,
        `start`, `end`, `time` and `endTime` (`15:00`, or "" for all day), `when`,
        `where`, `notes`, `repeats`, `repeatWords`, `remind`, `days`, `first` and
        `last` (whether it starts and ends on this day)."""
        try:
            within = _a_day(day)
        except PlannerError:
            return []
        return [_turn(t, within) for t in self._store.between(within, within)]

    @Slot(int, result="QVariantList")
    def upcoming(self, days: int) -> list:
        """What is on from today for \a days days, in order, for a list."""
        first = self._today()
        span = max(1, min(int(days), MAX_UPCOMING_DAYS))
        return [dict(_turn(t), date=t.first_day.isoformat())
                for t in self._store.between(first, first + timedelta(days=span - 1))]

    @Slot(str, result="QVariantMap")
    def event(self, ident: str) -> dict:
        """An event whole, for the editor: `id`, `title`, `start`, `end`, `allDay`,
        `where`, `notes`, `repeat`, `until`, `remind` (-1 for none), and in words
        `when`, `repeatWords`, `remindWords`. {} if there is none."""
        try:
            return _event(self._store.get(ident))
        except PlannerError:
            return {}

    # -- the editor's choices ----------------------------------------------------------------------

    @Property("QVariantList", constant=True)
    def repeats(self) -> list:
        """How an event may repeat: `id` and `label`."""
        return [{"id": how, "label": (planner.REPEAT_WORDS[how] or "does not repeat").capitalize()}
                for how in planner.REPEATS]

    @Property("QVariantList", constant=True)
    def reminders(self) -> list:
        """The reminders offered: `minutes` (-1 for none) and `label`."""
        return [{"minutes": minutes,
                 "label": "No reminder" if minutes < 0
                 else planner.reminder(minutes).capitalize()} for minutes in REMINDERS]

    @Slot(str, result="QVariantMap")
    def read(self, text: str) -> dict:
        """What a line typed by the person means, to fill the editor with: "Dentist
        Friday 3pm" gives `title`, `start`, `end`, `allDay` and `when`. `start` is
        "" when no day or time was in it."""
        asked = agenda.read(text)
        if asked.start is None:
            return {"title": asked.title, "start": "", "end": "", "allDay": False, "when": ""}
        try:
            event = asked.event()
        except PlannerError:
            return {"title": asked.title, "start": "", "end": "", "allDay": False, "when": ""}
        return {"title": asked.title, "start": _text(event.start), "end": _text(event.end),
                "allDay": event.all_day, "when": planner.when(event.start, event.end)}

    # -- changing ----------------------------------------------------------------------------------

    def _drafted(self, fields: dict, ident: str = "") -> Event:
        remind = fields.get("remind")
        try:
            remind = None if remind in (None, "") or int(remind) < 0 else int(remind)
        except (TypeError, ValueError):
            raise PlannerError("A reminder is a number of minutes before the start.") from None
        return planner.draft(fields.get("title", ""), fields.get("start", ""),
                             fields.get("end", ""), where=fields.get("where", ""),
                             notes=fields.get("notes", ""), repeat=fields.get("repeat", ""),
                             until=fields.get("until", ""), remind=remind, ident=ident)

    @Slot("QVariantMap", result=str)
    def add(self, fields: dict) -> str:
        """Add an event: `title` and `start`, and optionally `end`, `where`, `notes`,
        `repeat`, `until`, `remind` (minutes before, -1 for none). "" or why not;
        `added` carries the new event's id."""
        try:
            event = self._store.add(self._drafted(dict(fields)))
        except PlannerError as exc:
            return str(exc)
        except OSError as exc:
            return f"The calendar could not be saved: {exc}"
        self.added.emit(event.id)
        return ""

    @Slot(str, "QVariantMap", result=str)
    def change(self, ident: str, fields: dict) -> str:
        """Keep \a fields in place of the event \a ident, all of them as `add`
        takes them. "" or why not."""
        try:
            self._store.get(ident)
            self._store.change(self._drafted(dict(fields), str(ident)))
        except PlannerError as exc:
            return str(exc)
        except OSError as exc:
            return f"The calendar could not be saved: {exc}"
        return ""

    @Slot(str, str, result=str)
    @Slot(str, str, str, result=str)
    def move(self, ident: str, start: str, end: str = "") -> str:
        """Move the event \a ident to \a start, as long as it was unless \a end is
        given: for dragging one to another day or time. "" or why not."""
        try:
            was = self._store.get(ident)
            begins = planner.moment(start)
            if isinstance(begins, datetime) == was.all_day:
                # Dropped on a day, a timed event keeps its time; an all-day one has none.
                begins = (datetime.combine(begins, was.start.time()) if not was.all_day
                          else begins.date())
            ends = planner.moment(end, "an end") if str(end).strip() else begins + was.length
            fields = dict(_event(was), start=_text(begins), end=_text(ends))
            self._store.change(self._drafted(fields, was.id))
        except PlannerError as exc:
            return str(exc)
        except OSError as exc:
            return f"The calendar could not be saved: {exc}"
        return ""

    @Slot(str, result=str)
    def remove(self, ident: str) -> str:
        """Remove the event \a ident, every time it repeats. "" or why not."""
        try:
            self._store.remove(ident)
        except PlannerError as exc:
            return str(exc)
        except OSError as exc:
            return f"The calendar could not be saved: {exc}"
        return ""

    # -- what agents may do ------------------------------------------------------------------------

    def _allowed(self, capability: str) -> bool:
        return self._policy is not None and bool(self._policy().allows(capability))

    @Property(bool, notify=accessChanged)
    def agentsRead(self) -> bool:
        """Whether Akira's agents, and the chat, may read the calendar (`planner.read`)."""
        return self._allowed("planner.read")

    @Property(bool, notify=accessChanged)
    def agentsChange(self) -> bool:
        """Whether agents may ask to change it (`planner.write`); each change is
        still shown to the person first."""
        return self._allowed("planner.write")

    @Property(bool, notify=accessChanged)
    def noticesAllowed(self) -> bool:
        """Whether a reminder can be shown (`notify.send`). Without it, reminders wait."""
        return self._allowed("notify.send")

    def refresh_access(self) -> None:
        """For the shell: the grants changed."""
        self.accessChanged.emit()


def _a_day(text: str) -> date:
    when = planner.moment(text, "a day")
    return when.date() if isinstance(when, datetime) else when

