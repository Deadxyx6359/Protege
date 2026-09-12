"""Five-field cron expressions, parsed and searched locally.

Standard semantics, including the one everybody forgets: when both the
day-of-month and day-of-week fields are restricted, a day matches if *either*
does. `0 9 1 * 1` is "9am on the 1st, and every Monday", not "9am on Mondays
that happen to be the 1st". Getting that wrong produces a job that runs a
handful of times a year instead of weekly, and nobody notices for months.

A field counts as unrestricted when it starts with `*`, so `*/2` in the day
field still takes the AND path. That is what vixie cron does, and matching the
cron everyone has muscle memory for matters more than tidiness.

Deliberately no seconds field and no year field. A minute is the scheduler's
grain; anything finer belongs to an event trigger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

#: How far ahead to search before concluding an expression can never match.
#: Five years covers every leap-day expression, and `0 0 30 2 *` still returns
#: nothing promptly instead of spinning.
SEARCH_DAYS = 366 * 5

_MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_WEEKDAYS = {name: number for number, name in enumerate(
    ("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}

_MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


class CronError(ValueError):
    """The expression is not one this parser accepts."""


def _number(text: str, names: dict[str, int], label: str) -> int:
    token = text.strip().lower()
    if token in names:
        return names[token]
    if not token.isdigit():
        raise CronError(f"{label}: {text!r} is not a number")
    return int(token)


def _field(text: str, low: int, high: int, names: dict[str, int],
           label: str) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"{label}: empty entry in a list")
        step = 1
        stepped = "/" in part
        if stepped:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"{label}: a step must be a positive number")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            first, last = part.split("-", 1)
            start, end = _number(first, names, label), _number(last, names, label)
        else:
            start = _number(part, names, label)
            end = high if stepped else start
        if not (low <= start <= high and low <= end <= high):
            raise CronError(f"{label}: {part!r} is outside {low}-{high}")
        if start > end:
            raise CronError(f"{label}: the range {part!r} runs backwards")
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True, slots=True)
class CronExpr:
    """A parsed expression. Build with `CronExpr.parse`."""

    text: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    """0 is Sunday, as in cron. 7 is accepted and folded onto 0."""
    any_day: bool
    any_weekday: bool

    @classmethod
    def parse(cls, text: str) -> "CronExpr":
        source = text.strip()
        fields = _MACROS.get(source.lower(), source).split()
        if len(fields) != 5:
            raise CronError(
                "expected five fields (minute hour day month weekday), "
                f"got {len(fields)}")
        minute, hour, day, month, weekday = fields
        weekdays = _field(weekday, 0, 7, _WEEKDAYS, "weekday")
        if 7 in weekdays:
            weekdays = (weekdays - {7}) | {0}
        return cls(
            text=source,
            minutes=_field(minute, 0, 59, {}, "minute"),
            hours=_field(hour, 0, 23, {}, "hour"),
            days=_field(day, 1, 31, {}, "day"),
            months=_field(month, 1, 12, _MONTHS, "month"),
            weekdays=frozenset(weekdays),
            any_day=day.startswith("*"),
            any_weekday=weekday.startswith("*"),
        )

    def matches_day(self, day: date) -> bool:
        if day.month not in self.months:
            return False
        in_days = day.day in self.days
        # Python counts Monday as 0; cron counts Sunday as 0.
        in_weekdays = (day.weekday() + 1) % 7 in self.weekdays
        if self.any_day or self.any_weekday:
            return in_days and in_weekdays
        return in_days or in_weekdays

    def next_after(self, after: datetime) -> datetime | None:
        """The first matching minute strictly after \a after, or None."""
        start = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
        hours = sorted(self.hours)
        minutes = sorted(self.minutes)
        for offset in range(SEARCH_DAYS):
            day = start.date() + timedelta(days=offset)
            if not self.matches_day(day):
                continue
            today = offset == 0
            for hour in hours:
                if today and hour < start.hour:
                    continue
                for minute in minutes:
                    if today and hour == start.hour and minute < start.minute:
                        continue
                    return datetime(day.year, day.month, day.day, hour, minute)
        return None
