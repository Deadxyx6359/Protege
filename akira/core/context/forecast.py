"""The forecast for the days asked about, read from Open-Meteo rather than guessed.

Asked "what's the weather in Leeds tomorrow?", chat sent it to research, which
searched Wikipedia and found nothing about tomorrow. Open-Meteo, which the
person allowed for the weather, has the forecast. So when a message asks about
the weather, the place it names is found on Open-Meteo's geocoder and its
forecast read, and the days asked about go into the turn's context as facts,
the way `dates.span_lines` counts days.

Nothing is sent without `net.http` for open-meteo.com. A place the message
names is sent by name, as the person wrote it; with no place named, the
person's own is used, and only with `location.read`, to one decimal, as the
weather service does. Every request goes through the chokepoint.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Callable

from akira.core.net import NetError, host_of, with_query
from akira.core.net import fetch as net_fetch

from .weather import FORECAST, MAX_BYTES, SITE, Weather, WeatherError, _json, condition

#: Who the activity log records as asking.
ACTOR = "weather"

#: A message about the weather.
_ASKS = re.compile(
    r"\b(?:weather|forecast|rain(?:s|y|ing)?|snow(?:s|y|ing)?|sunny|umbrella|"
    r"how (?:hot|cold|warm)|temperature (?:in|at|for|today|tomorrow|on|this))\b",
    re.IGNORECASE)

_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
#: Words that end a place's name: "Leeds on Friday", "Paris tomorrow".
_NOT_PLACE = frozenset((*_DAYS, *_MONTHS, "today", "tonight", "tomorrow", "this", "next",
                        "the", "my", "our", "weekend", "week", "morning", "afternoon",
                        "evening", "now", "right"))
_JOINING = frozenset(("upon", "on", "de", "del", "la", "le", "am", "of", "the", "sur", "en"))
#: "in Leeds", "for New York", "at Stratford upon Avon", "in Paris, Texas".
_PLACE = re.compile(r"\b(?:in|at|for|near|around)\s+([A-Z][\w'’.-]*(?:[ -](?:[A-Z][\w'’.-]*|"
                    + "|".join(_JOINING) + r"))*(?:,\s*[A-Z][\w'’.-]*(?: [A-Z][\w'’.-]*)*)?)")

#: How many days are read, today first.
FORECAST_DAYS = 7


#: A question, or a request: "I love rainy days" asks nothing.
_ASKING = re.compile(r"\?|\b(?:weather|forecast)\b|^\s*(?:what|will|is|are|how|should|do|does|"
                     r"can|could|tell|check|give|show)\b", re.IGNORECASE)


def asks_about_weather(message: str) -> bool:
    return _ASKS.search(message) is not None and _ASKING.search(message) is not None


def place_named(message: str) -> tuple[str, str]:
    """The place \a message asks about, and what it was qualified by: ("Paris", "Texas")."""
    for found in _PLACE.finditer(message):
        name, _, qualifier = found[1].partition(",")
        words = name.split()
        for i, word in enumerate(words):
            if word.lower().strip(".'’") in _NOT_PLACE and not (i and word.lower() in _JOINING):
                words = words[:i]
                break
        while words and words[-1].lower() in _JOINING:
            words.pop()
        if words:
            qualifier = qualifier.strip() if len(words) == len(name.split()) else ""
            return " ".join(words), qualifier
    return "", ""


def days_asked(message: str, today: date) -> list[int]:
    """Which days \a message asks about, as days after \a today."""
    text = message.lower()
    if re.search(r"\b(?:this|next)? ?week\b|\bnext (?:few|several) days\b|\bweek ahead\b", text):
        return list(range(FORECAST_DAYS))
    wanted: set[int] = set()
    if re.search(r"\b(?:today|tonight|now|right now|this (?:morning|afternoon|evening))\b", text):
        wanted.add(0)
    if re.search(r"\btomorrow\b", text):
        wanted.add(1)
    if re.search(r"\bweekend\b", text):
        wanted.update(ahead for ahead in range(FORECAST_DAYS)
                      if (today + timedelta(days=ahead)).weekday() >= 5)
    for number, name in enumerate(_DAYS):
        if re.search(rf"\b{name}\b", text):
            wanted.add((number - today.weekday()) % 7)
    return sorted(wanted) or [0, 1]


def forecast_lines(message: str, policy, *, audit=None, today: date,
                   here: tuple[float, float] | None = None,
                   fetch: Callable | None = None) -> str:
    """The forecast for the place and days \a message asks about, or "".

    \a here is the person's own position, used when no place is named and only
    with `location.read`. Raises nothing: what went wrong is said instead.
    """
    if not asks_about_weather(message):
        return ""
    fetch = fetch if fetch is not None else net_fetch
    name, qualifier = place_named(message)
    if not policy.allows("net.http", host_of(FORECAST)):
        return (f"The forecast could not be read: reading {SITE} is not allowed. Say so, and "
                "do not guess the weather.")
    if name:
        finder = Weather(policy=lambda: policy, where=lambda: None, audit=audit, fetch=fetch)
        try:
            found = finder.find(name)
        except WeatherError as exc:
            return f"The forecast for {name} could not be read: {exc} Say so."
        best = next((place for place in found
                     if qualifier and qualifier.lower() in place.label.lower()), found[0])
        label, latitude, longitude = best.label, f"{best.latitude:.2f}", f"{best.longitude:.2f}"
    elif here is not None and policy.allows("location.read"):
        label, latitude, longitude = "where the person is", f"{here[0]:.1f}", f"{here[1]:.1f}"
    else:
        return ""
    address = with_query(FORECAST, {
        "latitude": latitude, "longitude": longitude,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,wind_speed_10m_max",
        "wind_speed_unit": "kmh", "timezone": "auto", "forecast_days": str(FORECAST_DAYS)})
    try:
        data = _json(fetch(address, policy=policy, audit=audit, actor=ACTOR,
                           max_bytes=MAX_BYTES))
        daily = data["daily"]
        days = [date.fromisoformat(day) for day in daily["time"]]
    except (NetError, WeatherError, KeyError, TypeError, ValueError) as exc:
        why = str(exc) if isinstance(exc, (NetError, WeatherError)) else "its answer was not a forecast."
        return f"The forecast for {label} could not be read: {why} Say so."
    lines = []
    for ahead in days_asked(message, days[0] if days else today):
        if ahead >= len(days):
            continue
        try:
            lines.append("- " + _day(days[ahead], ahead, daily))
        except (KeyError, TypeError, ValueError, IndexError, WeatherError):
            continue
    if not lines:
        return f"The forecast for {label} could not be read: it gave no days asked about. Say so."
    return (f"The forecast from {SITE} for {label}, read just now (give these figures as a "
            "forecast; do not add others):\n" + "\n".join(lines))


def _day(day: date, i: int, daily: dict) -> str:
    """Day \a i of \a daily, in words."""
    low, high = float(daily["temperature_2m_min"][i]), float(daily["temperature_2m_max"][i])
    wind = float(daily["wind_speed_10m_max"][i] or 0)
    _, words = condition(int(daily["weather_code"][i]), wind)
    rain = daily.get("precipitation_probability_max", [None] * (i + 1))[i]
    when = {0: " (today)", 1: " (tomorrow)"}.get(i, "")
    bits = [f"{words}", f"{low:.0f} to {high:.0f}°C ({low * 9 / 5 + 32:.0f} to "
            f"{high * 9 / 5 + 32:.0f}°F)"]
    if rain is not None:
        bits.append(f"{int(rain)}% chance of rain")
    bits.append(f"wind up to {wind:.0f} km/h")
    return f"{day:%A} {day.day} {day:%B}{when}: " + "; ".join(bits) + "."
