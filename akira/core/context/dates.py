"""How far away a date is, counted rather than guessed.

Asked "when is my MOT due, and how many days is that from today?", the model
found 14 November in the notes, knew today was 26 September, and said 50
days. It is 49. Chat has no tools to count with, and a small model counting
across month ends is off by one as often as not.

So when a message asks how long until or since something, the dates in the
message and in what was retrieved for it are counted here, against today, and
the counts go into the turn's context as facts. Nothing is read that the turn
did not already have; this only does sums on it.
"""

from __future__ import annotations

import re
from datetime import date

#: A message asking for a span: "how many days", "how long until", "weeks left".
_ASKS = re.compile(
    r"\bhow (?:many|much) (?:days|weeks|months|time)\b|\bhow long\b|\bhow soon\b|"
    r"\b(?:days|weeks|months) (?:until|till|to go|left|away|ago|since|from|before|after)\b|"
    r"\bcount ?down\b|\b(?:what|which) day\b|\bday of the week\b",
    re.IGNORECASE)

_MONTHS = {name: number for number, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
    ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
    ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
    ("dec", "december")), start=1) for name in names}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
#: 14 November 2026, 14th Nov, Saturday 10 Oct.
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})\.?(?:,?\s+(\d{{4}}))?\b",
                        re.IGNORECASE)
#: November 14, 2026; Nov 14th. Not "Oct 11:00", a time after "10 Oct".
_MONTH_DAY = re.compile(rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?![:.]\d)"
                        rf"(?:,?\s+(\d{{4}}))?", re.IGNORECASE)

#: Days known by name. Asked for the days until Christmas, the model counted to
#: Christmas Eve. Easter moves, so it is worked out (`_easter`).
#: Written without apostrophes; the text may have them or not.
_NAMED = {"christmas eve": (12, 24), "christmas day": (12, 25), "christmas": (12, 25),
          "boxing day": (12, 26), "new years eve": (12, 31), "new years day": (1, 1),
          "new year": (1, 1), "halloween": (10, 31), "bonfire night": (11, 5),
          "valentines day": (2, 14), "easter sunday": None, "easter": None}
_NAMED_DAY = re.compile(r"\b(" + "|".join(re.escape(name).replace("s\\ ", "['’]?s\\ ")
                                           for name in _NAMED) + r")\b", re.IGNORECASE)

#: At most this many dates are counted, so a long note does not flood the prompt.
MAX_DATES = 6


def asks_for_a_span(message: str) -> bool:
    return _ASKS.search(message) is not None


def dates_in(text: str, today: date) -> list[tuple[str, date]]:
    """Each date written in \a text, as written and as a date, in order.

    A date written without a year is taken as its next occurrence from today,
    which is what "the 10th of October" means in a note about what is coming.
    """
    found: list[tuple[int, str, date]] = []
    taken: list[range] = []

    def free(match: re.Match) -> bool:
        """Not part of a date already found: "10 Oct 2026" is not also "Oct 20"."""
        if any(match.start() in span or match.end() - 1 in span for span in taken):
            return False
        taken.append(range(match.start(), match.end()))
        return True

    for match in _ISO.finditer(text):
        day = _made(int(match[1]), int(match[2]), int(match[3]))
        if day is not None and free(match):
            found.append((match.start(), match[0], day))
    for pattern, day_group, month_group in ((_DAY_MONTH, 1, 2), (_MONTH_DAY, 2, 1)):
        for match in pattern.finditer(text):
            if not free(match):
                continue
            month = _MONTHS[match[month_group].lower()]
            number = int(match[day_group])
            if match[3]:
                day = _made(int(match[3]), month, number)
            else:
                day = _made(today.year, month, number)
                if day is not None and day < today:
                    day = _made(today.year + 1, month, number)
            if day is not None:
                found.append((match.start(), match[0].strip(), day))
    for match in _NAMED_DAY.finditer(text):
        if not free(match):
            continue
        day = _next(today, _NAMED[re.sub(r"['’]", "", match[1].lower())])
        if day is not None:
            found.append((match.start(), match[0], day))
    seen: set[date] = set()
    kept = []
    for _, written, day in sorted(found, key=lambda item: item[0]):
        if day not in seen:
            seen.add(day)
            kept.append((written, day))
    return kept


def _next(today: date, when: tuple[int, int] | None) -> date | None:
    """The next day on or after \a today that is \a when, or Easter when None."""
    for year in (today.year, today.year + 1):
        day = _easter(year) if when is None else _made(year, *when)
        if day is not None and day >= today:
            return day
    return None


def _easter(year: int) -> date:
    """Easter Sunday in the Gregorian calendar (the anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - the algorithm's own name
    m = (a + 11 * h + 19 * l) // 433
    month = (h + l - 7 * m + 90) // 25
    return date(year, month, (h + l - 7 * m + 33 * month + 19) % 32)


def _made(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def span_lines(message: str, texts: list[str], today: date) -> str:
    """The day counts for a message that asks for a span, or "".

    The message's own dates come first: they are what was asked about.
    """
    if not asks_for_a_span(message):
        return ""
    seen: set[date] = set()
    lines = []
    for text in [message, *texts]:
        for written, day in dates_in(text, today):
            if day in seen or len(lines) >= MAX_DATES:
                continue
            seen.add(day)
            lines.append(f"- {written} ({day:%A} {day.day} {day:%B %Y}): {_counted(day, today)}")
    if not lines:
        return ""
    return ("Counted exactly from today, for this question (use these numbers, do not "
            "count again):\n" + "\n".join(lines))


def _counted(day: date, today: date) -> str:
    days = (day - today).days
    if days == 0:
        return "today"
    weeks, rest = divmod(abs(days), 7)
    week_part = f", which is {weeks} week{'s' * (weeks != 1)}" + (
        f" and {rest} day{'s' * (rest != 1)}" if rest else "") if weeks else ""
    if days > 0:
        return f"in {days} day{'s' * (days != 1)}{week_part}"
    return f"{-days} day{'s' * (days != -1)} ago{week_part}"
