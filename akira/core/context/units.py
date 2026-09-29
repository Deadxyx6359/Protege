"""Amounts converted from one unit to another, worked out rather than recalled.

Asked to convert 72°F to Celsius, the model wrote the formula upside down,
(°F - 32) × 9/5, did that sum right, and said 72°F is 72°C. Another time the
same model got it right. A formula it half remembers is not something to leave
to chance.

So when a message asks for an amount in another unit, and names both, the
amount is converted here and the result goes into the turn's context as a fact,
the way `dates.span_lines` counts days. Only the common kinds are known:
temperature, length and distance, weight.
"""

from __future__ import annotations

import re

#: Each unit's spellings, longest first where one begins another.
_NAMES = {
    "F": r"°\s?F\b|degrees? (?:fahrenheit|f)\b|fahrenheit|F\b",
    "C": r"°\s?C\b|degrees? (?:celsius|centigrade|c)\b|celsius|centigrade|C\b",
    "km": r"kilomet(?:re|er)s?\b|kms?\b",
    "mi": r"miles?\b|mi\b",
    "m": r"met(?:re|er)s?\b|m\b",
    "cm": r"centimet(?:re|er)s?\b|cm\b",
    "mm": r"millimet(?:re|er)s?\b|mm\b",
    "ft": r"f(?:ee|oo)t\b|ft\b",
    "in": r"inch(?:es)?\b|in\.",
    "kg": r"kilo(?:gram)?s?\b|kgs?\b",
    "g": r"grams?\b|g\b",
    "lb": r"pounds?\b|lbs?\b",
    "oz": r"ounces?\b|oz\b",
    "st": r"stones?\b|st\b",
}
#: Lengths in metres and weights in kilograms, so that any two of a kind convert.
_SIZE = {"km": 1000, "mi": 1609.344, "m": 1, "cm": 0.01, "mm": 0.001, "ft": 0.3048,
         "in": 0.0254}
_WEIGHT = {"kg": 1, "g": 0.001, "lb": 0.45359237, "oz": 0.028349523125, "st": 6.35029318}
_TEMPERATURE = {"F": 0, "C": 0}
_SHOWN = {"F": "°F", "C": "°C"}

#: An amount with its unit: "72°F", "-4 C", "5 miles", "2.5kg". Not "£5 pounds".
_AMOUNT = re.compile(r"(?<![\w£$€.])(-?\d+(?:\.\d+)?)\s?(" + "|".join(
    f"(?P<{unit}>{spelling})" for unit, spelling in _NAMES.items()) + ")", re.IGNORECASE)
#: A message asking for another unit: "convert", "in Celsius", "to miles", "how many feet".
_ASKS = re.compile(r"\b(?:convert|conversion|in|into|to|how many|what is|what's)\b",
                   re.IGNORECASE)
#: Said with a lone F or C, which is then a temperature: "convert -40 F to C".
_TEMPERATURE_WORDS = re.compile(r"fahrenheit|celsius|centigrade|°|\bconvert", re.IGNORECASE)

#: At most this many amounts are converted.
MAX_AMOUNTS = 4


def unit_lines(message: str) -> str:
    """Each amount in \a message converted to the unit it asks for, or ""."""
    if not _ASKS.search(message):
        return ""
    lines: list[str] = []
    for found in _AMOUNT.finditer(message):
        unit = next(name for name in _NAMES if found.group(name) is not None)
        if unit in _TEMPERATURE and not ("°" in found[2] or len(found[2]) > 1
                                         or _TEMPERATURE_WORDS.search(message)):
            continue  # "plan B, 3 F to go" is not a temperature
        # Asked for: another unit of its kind is named in the message, apart from the amount.
        rest = message[:found.start()] + " " + message[found.end():]
        kind = next(table for table in (_SIZE, _WEIGHT, _TEMPERATURE) if unit in table)
        target = next((other for other in kind if other != unit and re.search(
            rf"(?<![\w°])(?:{_NAMES[other]})|°\s?{other}\b", rest, re.IGNORECASE)), None)
        if target is None:
            continue
        written = _number(float(found[1]))
        result, working = _converted(float(found[1]), written, unit, target)
        lines.append(f"- {written}{_unit(unit)} = {_number(round(result, 2))}{_unit(target)} "
                     f"({working})")
        if len(lines) >= MAX_AMOUNTS:
            break
    if not lines:
        return ""
    return ("Amounts in the message, converted (use these, do not work them out again):\n"
            + "\n".join(lines))


def _converted(value: float, written: str, unit: str, target: str) -> tuple[float, str]:
    """\a value in \a target, and the sum that gets there."""
    if unit == "F":
        return (value - 32) * 5 / 9, f"({written} - 32) × 5/9"
    if unit == "C":
        return value * 9 / 5 + 32, f"{written} × 9/5 + 32"
    table = _SIZE if unit in _SIZE else _WEIGHT
    ratio = table[unit] / table[target]
    if ratio >= 1:
        return value * ratio, f"{written} × {_number(ratio)}"
    return value * ratio, f"{written} ÷ {_number(1 / ratio)}"


def _unit(unit: str) -> str:
    return _SHOWN.get(unit, f" {unit}")


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"
