"""Reminders asked for in the chat: "remind me to call mum tomorrow at 9".

The chat has no tools, and a model asked to set a reminder answered "Reminder
set for 5 PM" when nothing was set. So a message asking for one does not go to
the model. It is read here, what and when; the chat says back what it
understood and asks "yes?"; and only the person's yes makes it a notice job in
Schedule. The time is read by rules, not by a model: a reminder at the wrong
hour is worse than being asked when.

Times are local, as the person says them. What is understood:

  * in 20 minutes, in an hour, in half an hour, in 2 days
  * at 5, at 5pm, at 17:30, at noon, at midnight
  * today, tonight, this morning / afternoon / evening, tomorrow (morning ...)
  * on Friday, next Monday, with or without a time
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

#: A message asking for a reminder: "remind me ...", "set a reminder ...".
_ASKS = re.compile(
    r"^\s*(?:(?:hey|ok|okay)[, ]+(?:akira[, ]+)?)?(?:akira[, ]+)?"
    r"(?:(?:can|could|would|will) you\s+|please\s+)?"
    r"(?:remind me|set (?:a|me a|up a) reminder|add a reminder|make a reminder)\b",
    re.IGNORECASE)

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_IN = re.compile(r"\bin\s+(half an|an?|one|two|three|\d+(?:\.\d+)?)\s*"
                 r"(minutes?|mins?|hours?|hrs?|days?|weeks?)\b", re.IGNORECASE)
_AT = re.compile(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])"
                 r"|\bat\s+(\d{1,2})(?::(\d{2}))?\b"
                 r"|\b(\d{1,2}):(\d{2})\b"
                 r"|\b(?:at\s+)?(noon|midday|midnight)\b", re.IGNORECASE)
_DAY = re.compile(r"\b(today|tonight|tomorrow|this (?:morning|afternoon|evening))"
                  r"(?:\s+(morning|afternoon|evening|night))?\b"
                  r"|\b(?:on\s+|next\s+)?(" + "|".join(_WEEKDAYS) + r")"
                  r"(?:\s+(morning|afternoon|evening|night))?\b", re.IGNORECASE)

_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "half an": 0.5}
_PART_HOUR = {"morning": 9, "afternoon": 15, "evening": 18, "night": 20, "tonight": 20}

_YES = re.compile(r"^\s*(?:yes|yeah|yep|yup|sure|ok|okay|please|do it|go ahead|set it|"
                  r"sounds good|that's right|correct|right)\b", re.IGNORECASE)
_NO = re.compile(r"^\s*(?:no|nope|nah|don't|do not|cancel|never ?mind|stop)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Asked:
    """What a message asked to be reminded of, and when, if that was said."""

    what: str
    when: datetime | None


def asks(text: str) -> bool:
    """Whether \a text asks for a reminder."""
    return bool(_ASKS.search(text))


def read(text: str, now: datetime | None = None) -> Asked:
    """What and when \a text asks to be reminded of. `when` is None if no time was said."""
    now = now or datetime.now()
    when, spans = when_said(text, now)
    rest = _ASKS.sub("", text, count=1)
    offset = len(text) - len(rest)
    for start, end in sorted(spans, reverse=True):
        start, end = max(0, start - offset), max(0, end - offset)
        rest = rest[:start] + " " + rest[end:]
    what = re.sub(r"\s+", " ", rest).strip(" ,.;:!?")
    what = re.sub(r"^(?:to|about|that|of|for)\s+", "", what, flags=re.IGNORECASE)
    what = re.sub(r"\s+(?:to|at|on|for|by)$", "", what, flags=re.IGNORECASE).strip(" ,.;:!?")
    return Asked(what[:200], when)


def day_and_time(text: str, now: datetime) -> tuple[
        "date | None", "tuple[int, int] | None", str, list[tuple[int, int]]]:
    """The day and the clock time \a text names, each or neither, with the part of
    the day said ("evening") and where in \a text they were said.

    A clock time that cannot be (25:00) is given as (-1, -1).
    """
    spans: list[tuple[int, int]] = []
    day, part = None, None
    found = _DAY.search(text)
    if found:
        spans.append(found.span())
        said = (found.group(1) or "").lower()
        if said:
            day = now.date() + timedelta(days=1) if said == "tomorrow" else now.date()
            part = found.group(2) or (said.split()[-1] if said.startswith("this") else
                                      "tonight" if said == "tonight" else None)
        else:
            target = _WEEKDAYS.index(found.group(3).lower())
            ahead = (target - now.weekday()) % 7
            day = now.date() + timedelta(days=ahead or 7)
            part = found.group(4)
            if ahead == 0 and "next" not in text[found.start():found.end()].lower():
                day = now.date()  # "on Friday" said on a Friday: today, if still to come

    clock = None
    found = _AT.search(text)
    if found:
        spans.append(found.span())
        groups = found.groups()
        if groups[0]:
            hour, minute = int(groups[0]), int(groups[1] or 0)
            pm = groups[2].lower().startswith("p")
            hour = hour % 12 + (12 if pm else 0)
        elif groups[3]:
            hour, minute = int(groups[3]), int(groups[4] or 0)
            if hour <= 12 and part in ("afternoon", "evening", "night", "tonight"):
                hour = hour % 12 + 12
            elif 1 <= hour <= 7 and part is None:
                hour += 12  # "at 5" is five in the afternoon, not before dawn
        elif groups[5]:
            hour, minute = int(groups[5]), int(groups[6])
        else:
            hour, minute = (0, 0) if groups[7].lower() == "midnight" else (12, 0)
            if groups[7].lower() == "midnight" and day is None:
                day = now.date() + timedelta(days=1)
        clock = (hour, minute) if 0 <= hour <= 23 and 0 <= minute <= 59 else (-1, -1)
    return day, clock, (part or "").lower(), spans


def when_said(text: str, now: datetime) -> tuple[datetime | None, list[tuple[int, int]]]:
    """The time \a text names, from \a now, and where in it that was said."""
    found = _IN.search(text)
    if found:
        amount = _NUMBERS.get(found.group(1).lower())
        amount = float(found.group(1)) if amount is None else amount
        unit = found.group(2).lower()
        step = (timedelta(minutes=amount) if unit.startswith("m") else
                timedelta(hours=amount) if unit.startswith("h") else
                timedelta(weeks=amount) if unit.startswith("w") else timedelta(days=amount))
        return (now + step).replace(second=0, microsecond=0), [found.span()]

    day, clock, part, spans = day_and_time(text, now)
    if clock == (-1, -1) or (day is None and clock is None):
        return None, spans
    hour, minute = clock if clock is not None else (_PART_HOUR.get(part or "morning", 9), 0)
    when = datetime.combine(day or now.date(), datetime.min.time()).replace(hour=hour,
                                                                           minute=minute)
    if when <= now:
        if day is None or day == now.date():
            when += timedelta(days=1)  # "at 5" after five: tomorrow
        else:
            return None, spans
    return when, spans


def described(when: datetime, now: datetime | None = None) -> str:
    """\a when for a person: "today at 17:00", "tomorrow at 09:00", "Friday at 15:00"."""
    now = now or datetime.now()
    clock = when.strftime("%H:%M")
    days = (when.date() - now.date()).days
    if days == 0:
        if when - now < timedelta(hours=1):
            minutes = max(1, round((when - now).total_seconds() / 60))
            return f"in {minutes} minute{'' if minutes == 1 else 's'}, at {clock}"
        return f"today at {clock}"
    if days == 1:
        return f"tomorrow at {clock}"
    if days < 7:
        return f"{when.strftime('%A')} at {clock}"
    return f"{when.day} {when.strftime('%b')} at {clock}"


def answer(text: str) -> str:
    """"yes", "no", or "" for anything else."""
    if _NO.search(text):
        return "no"
    if _YES.search(text) and len(text.split()) <= 6:
        return "yes"
    return ""
