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
from datetime import date, datetime

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

#: What joins the two ends of a range: "March 3 and April 17", "3 March to 17 April".
_RANGE = re.compile(r"\s*(?:,\s*)?(?:and|to|through|until|till|-|–|—)\s*", re.IGNORECASE)

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
    written: list[tuple[re.Match, int, int, int | None]] = []
    for pattern, day_group, month_group in ((_DAY_MONTH, 1, 2), (_MONTH_DAY, 2, 1)):
        for match in pattern.finditer(text):
            if free(match):
                written.append((match, _MONTHS[match[month_group].lower()],
                                int(match[day_group]), int(match[3]) if match[3] else None))
    written.sort(key=lambda item: item[0].start())
    for index, (match, month, number, year) in enumerate(written):
        if year is None and index + 1 < len(written):
            # "Between March 3 and April 17, 2026": the year is said once, for both.
            after, month_after, number_after, year_after = written[index + 1]
            if year_after is not None and _RANGE.fullmatch(text[match.end():after.start()]):
                year = year_after - ((month, number) > (month_after, number_after))
        if year is not None:
            day = _made(year, month, number)
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
    asked = dates_in(message, today)
    if len(asked) >= 2:
        # "How many days between March 3 and April 17?" is the gap between them,
        # not each from today: given only those, a model subtracted wrongly.
        (first, start), (second, end) = asked[0], asked[1]
        gap = abs((end - start).days)
        weeks, days = divmod(gap, 7)
        in_weeks = (f", which is {weeks} week{'s' if weeks != 1 else ''}"
                    + (f" and {days} day{'s' if days != 1 else ''}" if days else "")
                    if weeks else "")
        lines.append(f"- Between {first} and {second}: {gap} day{'s' if gap != 1 else ''}"
                     f"{in_weeks}, counting from one to the other")
    return ("Counted exactly from today, for this question (use these numbers, do not "
            "count again):\n" + "\n".join(lines))


#: 6pm, 6 p.m., 6:30pm; 18:00; noon, midnight.
_CLOCK_12 = re.compile(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([ap])\.?\s?m\b\.?", re.IGNORECASE)
_CLOCK_24 = re.compile(r"(?<![\d:])\b([01]?\d|2[0-3]):([0-5]\d)\b(?![\d:])")
_CLOCK_NAMED = re.compile(r"\b(noon|midday|midnight)\b", re.IGNORECASE)

#: At most this many clock times are counted.
MAX_TIMES = 4


def clock_lines(message: str, now: datetime) -> str:
    """How long until, or since, each clock time the message names, or "".

    Told 17:11, asked whether a shop that shuts at 6pm is still open, the
    model said it had shut nine minutes before. Counted here instead, today,
    from \a now, which is the time the model was told.
    """
    found: list[tuple[int, str, int]] = []
    for match in _CLOCK_12.finditer(message):
        hour = int(match[1]) % 12 + (12 if match[3].lower() == "p" else 0)
        found.append((match.start(), match[0].strip(), hour * 60 + int(match[2] or 0)))
    for match in _CLOCK_24.finditer(message):
        if not _CLOCK_12.match(message, match.start()):
            found.append((match.start(), match[0], int(match[1]) * 60 + int(match[2])))
    for match in _CLOCK_NAMED.finditer(message):
        found.append((match.start(), match[0], 0 if match[1].lower() == "midnight" else 720))
    minutes_now = now.hour * 60 + now.minute
    seen: set[int] = set()
    lines = []
    for _, written, minutes in sorted(found):
        if minutes in seen or len(lines) >= MAX_TIMES:
            continue
        seen.add(minutes)
        lines.append(f"- {written} ({minutes // 60:02d}:{minutes % 60:02d}): "
                     f"{_minutes_apart(minutes - minutes_now)}")
    if not lines:
        return ""
    return (f"Clock times in the message, counted from now ({now:%H:%M}) for today (use these, "
            "do not count again):\n" + "\n".join(lines))


def _minutes_apart(minutes: int) -> str:
    if minutes == 0:
        return "now"
    hours, rest = divmod(abs(minutes), 60)
    span = " ".join(part for part in (
        f"{hours} hour{'s' * (hours != 1)}" if hours else "",
        f"{rest} minute{'s' * (rest != 1)}" if rest else "") if part)
    return f"in {span}" if minutes > 0 else f"{span} ago"


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
