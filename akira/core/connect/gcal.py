"""Reading Google Calendar, as a connected address (C5).

Only reading: Google was asked for `calendar.readonly`, and every request is
held to `calendar.read` for the address. The primary calendar, one span of at
most a month at a time. Named `gcal` rather than `calendar`, which is Python's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from akira.core.net import with_query
from akira.core.net.page import readable

from .google import GoogleAccounts

API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

#: The most events one look returns.
MAX_EVENTS = 50

#: The longest span one look covers.
MAX_DAYS = 31

#: The most of an event's description that is kept.
MAX_DESCRIPTION = 2_000


@dataclass(frozen=True)
class Event:
    title: str
    start: str
    """As Google gives it: a date for an all-day event, otherwise a date and time."""
    end: str
    all_day: bool
    where: str
    organizer: str
    attendees: int
    description: str


def _rfc3339(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _description(text: str) -> str:
    text = text.strip()
    if "<" in text and ">" in text:
        text = readable(text)[1].strip()
    return text[:MAX_DESCRIPTION]


def events(accounts: GoogleAccounts, address: str, *, start: datetime, days: int, policy, audit,
           actor: str, limit: int = MAX_EVENTS) -> list[Event]:
    """Events from \a start for \a days, in order. Repeating events are listed once per day."""
    days = max(1, min(int(days), MAX_DAYS))
    url = with_query(API, {"timeMin": _rfc3339(start),
                           "timeMax": _rfc3339(start + timedelta(days=days)),
                           "singleEvents": "true", "orderBy": "startTime",
                           "maxResults": str(max(1, min(int(limit), MAX_EVENTS)))})
    data = accounts.get(address, "calendar", url, policy=policy, audit=audit, actor=actor)
    found = []
    for item in data.get("items") or []:
        if not isinstance(item, dict) or item.get("status") == "cancelled":
            continue
        begins, ends = item.get("start") or {}, item.get("end") or {}
        found.append(Event(
            str(item.get("summary") or "(no title)"),
            str(begins.get("dateTime") or begins.get("date") or ""),
            str(ends.get("dateTime") or ends.get("date") or ""),
            "dateTime" not in begins,
            str(item.get("location") or ""),
            str((item.get("organizer") or {}).get("email") or ""),
            len(item.get("attendees") or []),
            _description(str(item.get("description") or ""))))
    return found
