"""Google Calendar, as a connected address (C5): reading it, and changing it when asked.

Reading is held to `calendar.read` for the address, and Google is asked for
`calendar.readonly`. Changing is a service of its own, `events`, held to
`calendar.write` for the address, and Google is asked for
`calendar.events.owned`: events on calendars the person owns, and nothing else.

Every change is to the primary calendar, sent once, and made quietly: nobody is
invited, and when an event with guests is moved or cancelled Google is told not
to write to them (`sendUpdates=none`). Telling other people is sending on the
person's behalf, and that is not this. Only an event the person organises is
moved or cancelled; one someone else organised is theirs to change, and the
refusal says so before anyone is asked.

Named `gcal` rather than `calendar`, which is Python's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from akira.core.net import with_query
from akira.core.net.page import readable

from .google import ConnectError, GoogleAccounts

API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

#: The most events one look returns.
MAX_EVENTS = 50

#: The longest span one look covers.
MAX_DAYS = 31

#: The most of an event's description that is kept.
MAX_DESCRIPTION = 2_000

#: The longest an event added or moved may last. Longer is almost always a slip
#: of the year or the month, and a fortnight covers a holiday.
MAX_SPAN = timedelta(days=14)

MAX_TITLE = 200
MAX_WHERE = 200
MAX_NOTES = 2_000

#: How long an event given no end lasts.
DEFAULT_LENGTH = timedelta(hours=1)

#: What Google's event ids are made of, a repeating event's occurrences included.
#: Checked rather than escaped, so an id can never become part of another path.
_EVENT_ID = re.compile(r"[A-Za-z0-9_]{1,1024}")

#: Nobody is written to about a change.
QUIETLY = {"sendUpdates": "none"}


@dataclass(frozen=True)
class Event:
    title: str
    start: str
    """As Google gives it: a date for an all-day event, otherwise a date and time."""
    end: str
    """As Google gives it. For an all-day event, the day *after* the last one."""
    all_day: bool
    where: str
    organizer: str
    attendees: int
    """Other people on it. The person is not counted, though Google lists them."""
    description: str
    id: str = ""
    mine: bool = False
    """The person organises it, so it is theirs to move or cancel."""
    recurring: bool = False
    """One occurrence of a repeating event."""


@dataclass(frozen=True)
class Draft:
    """What an event will say and when it is, checked before anyone is asked."""

    title: str
    start: date
    """A `datetime` for an event at a time, a `date` for one that lasts all day."""
    end: date
    """For an all-day event, the day after the last, as Google counts it."""
    where: str = ""
    notes: str = ""

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)

    def times(self) -> dict:
        """The start and end, as Google takes them."""
        return times(self.start, self.end)


def times(begins: date, ends: date) -> dict:
    """A start and an end, as Google takes them: dates for all day, or dates and times."""
    field = "dateTime" if isinstance(begins, datetime) else "date"
    return {"start": {field: begins.isoformat()}, "end": {field: ends.isoformat()}}


def _rfc3339(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _description(text: str) -> str:
    text = text.strip()
    if "<" in text and ">" in text:
        text = readable(text)[1].strip()
    return text[:MAX_DESCRIPTION]


def _event(item: dict) -> Event:
    begins, ends = item.get("start") or {}, item.get("end") or {}
    organizer = item.get("organizer") or {}
    return Event(
        str(item.get("summary") or "(no title)"),
        str(begins.get("dateTime") or begins.get("date") or ""),
        str(ends.get("dateTime") or ends.get("date") or ""),
        "dateTime" not in begins,
        str(item.get("location") or ""),
        str(organizer.get("email") or ""),
        sum(1 for guest in item.get("attendees") or []
            if not (isinstance(guest, dict) and guest.get("self"))),
        _description(str(item.get("description") or "")),
        str(item.get("id") or ""),
        bool(organizer.get("self")),
        bool(item.get("recurringEventId")))


def events(accounts: GoogleAccounts, address: str, *, start: datetime, days: int, policy, audit,
           actor: str, limit: int = MAX_EVENTS) -> list[Event]:
    """Events from \a start for \a days, in order. Repeating events are listed once per day."""
    days = max(1, min(int(days), MAX_DAYS))
    url = with_query(API, {"timeMin": _rfc3339(start),
                           "timeMax": _rfc3339(start + timedelta(days=days)),
                           "singleEvents": "true", "orderBy": "startTime",
                           "maxResults": str(max(1, min(int(limit), MAX_EVENTS)))})
    data = accounts.get(address, "calendar", url, policy=policy, audit=audit, actor=actor)
    return [_event(item) for item in data.get("items") or []
            if isinstance(item, dict) and item.get("status") != "cancelled"]


# -- what a change will be ----------------------------------------------------------------------


def moment(text: str, what: str = "a start") -> date:
    """A date, or a date and time, as written: `2026-09-18` or `2026-09-18T15:00`.

    A time given with no offset is this computer's own. Raises `ConnectError`.
    """
    value = str(text).strip()
    if not value:
        raise ConnectError(f"The event needs {what}.")
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        found = datetime.fromisoformat(value)
    except ValueError:
        raise ConnectError(f"{value!r} is not a date, or a date and time, such as 2026-09-18 or "
                           "2026-09-18T15:00.") from None
    return found if found.tzinfo is not None else found.astimezone()


def _line(text: str) -> str:
    return " ".join(str(text).split())


def span(start: str, end: str = "") -> tuple[date, date]:
    """When an event is: \a start, and \a end if given, as Google counts them.

    An all-day event's \a end is the last day it covers, and given none it is one
    day. An event at a time given no end lasts an hour. Raises `ConnectError`.
    """
    begins = moment(start, "a start")
    all_day = not isinstance(begins, datetime)
    if str(end).strip():
        ends = moment(end, "an end")
        if isinstance(ends, datetime) == all_day:
            raise ConnectError("The start and the end must both be dates, for an event that "
                               "lasts all day, or both be dates and times.")
        if all_day:
            ends = ends + timedelta(days=1)
    else:
        ends = begins + (timedelta(days=1) if all_day else DEFAULT_LENGTH)
    if ends <= begins:
        raise ConnectError("The event must end after it starts.")
    if ends - begins > MAX_SPAN:
        raise ConnectError(f"An event may last at most {MAX_SPAN.days} days, and that one lasts "
                           f"{(ends - begins).days}. Check the year and the month.")
    return begins, ends


def draft(title: str, start: str, end: str = "", where: str = "", notes: str = "") -> Draft:
    """An event to add, checked before anyone is asked. Raises `ConnectError` with why not."""
    title = _line(title)
    if not title:
        raise ConnectError("The event needs a title.")
    if len(title) > MAX_TITLE:
        raise ConnectError(f"A title may be at most {MAX_TITLE} characters.")
    where = _line(where)
    if len(where) > MAX_WHERE:
        raise ConnectError(f"Where it is may be at most {MAX_WHERE} characters.")
    notes = str(notes).strip()
    if len(notes) > MAX_NOTES:
        raise ConnectError(f"Notes may be at most {MAX_NOTES} characters, so they can be read "
                           "in full before the event is added.")
    begins, ends = span(start, end)
    return Draft(title, begins, ends, where, notes)


def event_id(text: str) -> str:
    """\a text as an event id. Raises `ConnectError` if it is not one."""
    value = str(text).strip()
    if not _EVENT_ID.fullmatch(value):
        raise ConnectError(f"{value!r} is not an event id. list_events gives each event's id.")
    return value


def changeable(found: Event, doing: str) -> Event:
    """\a found, if the person organises it. Raises `ConnectError` saying whose it is."""
    if not found.mine:
        whose = found.organizer or "someone else"
        raise ConnectError(f"{whose} organises {found.title!r}, so only they can {doing} it. "
                           "Decline it in Google Calendar if you will not go.")
    return found


# -- changes, each sent once ----------------------------------------------------------------------


def event(accounts: GoogleAccounts, address: str, ident: str, *, policy, audit,
          actor: str) -> Event:
    """One event, looked up under the permission to change it. Raises `ConnectError`."""
    data = accounts.get(address, "events", f"{API}/{event_id(ident)}", policy=policy,
                        audit=audit, actor=actor)
    if data.get("status") == "cancelled":
        raise ConnectError("That event has already been cancelled.")
    return _event(data)


def add(accounts: GoogleAccounts, address: str, planned: Draft, *, policy, audit,
        actor: str) -> str:
    """Add \a planned to \a address's calendar, once, inviting nobody. Returns its id."""
    payload = {"summary": planned.title, **planned.times()}
    if planned.where:
        payload["location"] = planned.where
    if planned.notes:
        payload["description"] = planned.notes
    data = accounts.post(address, "events", with_query(API, QUIETLY), payload, policy=policy,
                         audit=audit, actor=actor)
    return str(data.get("id") or "")


def move(accounts: GoogleAccounts, address: str, ident: str, begins: date, ends: date, *,
         policy, audit, actor: str) -> None:
    """Give an event new times, once, telling nobody."""
    accounts.patch(address, "events", with_query(f"{API}/{event_id(ident)}", QUIETLY),
                   times(begins, ends), policy=policy, audit=audit, actor=actor)


def cancel(accounts: GoogleAccounts, address: str, ident: str, *, policy, audit,
           actor: str) -> None:
    """Remove an event, once, telling nobody."""
    accounts.delete(address, "events", with_query(f"{API}/{event_id(ident)}", QUIETLY),
                    policy=policy, audit=audit, actor=actor)
