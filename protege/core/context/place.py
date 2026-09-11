"""Now and here: what agents and the conversation are told about the world (C7).

A model has no clock. Asked what is new this week, or how long until Friday, it
guesses from its training data, confidently and wrongly. So every turn and every
agent is told the date and the time.

**Where is `location.read`.** The date and time say nothing about where the
person is; a time zone and a place do. Those are added only while
`location.read` is granted, checked each time. The place is one the person
sets: Windows will not say where the computer is without packages this project
does not ship, and a guess from the time zone is not a place.

**One season, two readers.** The scenes already work out the season from the
clock (`scenes/world.js`), flipping it for the southern hemisphere. The rule is
mirrored here exactly, so the scenery and the assistant never disagree about
what time of year it is. The hemisphere comes from the place, which is also what
the scenes' `southernHemisphere` has been waiting for.

Weather is a network reading, and waits for the network chokepoint (C1).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from protege.core.config import config_dir

MAX_NAME_CHARS = 80
HEMISPHERES = ("north", "south", "")

_FLIP = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}


class PlaceError(ValueError):
    """A place that cannot be kept, with a reason for the person."""


def season(day: date, southern: bool = False) -> str:
    """The season on \a day, by the scenes' rule: about the 20th of March, June,
    September and December, flipped in the southern hemisphere."""
    stamp = day.month * 100 + day.day
    if stamp < 320:
        name = "winter"
    elif stamp < 621:
        name = "spring"
    elif stamp < 922:
        name = "summer"
    elif stamp < 1221:
        name = "autumn"
    else:
        name = "winter"
    return _FLIP[name] if southern else name


def part_of_day(moment: datetime) -> str:
    """The scenes' names for the light: night, dawn, morning, day, golden hour, dusk."""
    hours = moment.hour + moment.minute / 60
    if hours < 5.0:
        return "night"
    if hours < 7.5:
        return "dawn"
    if hours < 10.0:
        return "morning"
    if hours < 16.5:
        return "day"
    if hours < 19.0:
        return "golden hour"
    if hours < 21.0:
        return "dusk"
    return "night"


@dataclass(frozen=True)
class Place:
    name: str = ""
    """As the person wrote it, e.g. "Bristol, UK"."""

    hemisphere: str = ""
    """`north`, `south`, or "" when not given."""

    @property
    def southern(self) -> bool:
        return self.hemisphere == "south"


def check_place(name: str, hemisphere: str) -> Place:
    cleaned = " ".join((name or "").split())
    if len(cleaned) > MAX_NAME_CHARS:
        raise PlaceError(f"A place is at most {MAX_NAME_CHARS} characters.")
    if name and "\n" in name:
        raise PlaceError("A place is one line.")
    side = (hemisphere or "").strip().lower()
    if side not in HEMISPHERES:
        raise PlaceError("The hemisphere is north or south, or left empty.")
    return Place(cleaned, side)


class PlaceStore:
    """`place.json` in the configuration folder."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_dir() / "place.json"

    def load(self) -> Place:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return check_place(str(raw.get("name") or ""), str(raw.get("hemisphere") or ""))
        except (OSError, ValueError, AttributeError, TypeError):
            # Missing or damaged: no place, rather than a guessed one.
            return Place()

    def save(self, place: Place) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"name": place.name, "hemisphere": place.hemisphere}, stream)
            os.replace(temporary, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


def describe_now(now: datetime, *, place: Place | None = None, located: bool = False) -> str:
    """When it is, and where if \a located, for a model to read."""
    local = now if now.tzinfo is not None else now.astimezone()
    text = (f"It is {local.strftime('%A')} {local.day} {local.strftime('%B %Y')}, "
            f"{local.strftime('%H:%M')} ({part_of_day(local)}).")
    if not located:
        return text
    bits = [text]
    offset = local.strftime("%z")
    zone = local.tzname() or ""
    if offset:
        label = f"UTC{offset[:3]}:{offset[3:]}"
        bits.append(f"The local time zone is {zone} ({label})." if zone and zone != label
                    else f"The local time zone is {label}.")
    if place is not None and place.name:
        bits.append(f"The person is in {place.name}.")
    if place is not None and place.hemisphere:
        bits.append(f"That is in the {place.hemisphere}ern hemisphere, where it is "
                    f"{season(local.date(), place.southern)}.")
    return " ".join(bits)


def now_line(policy, *, store: PlaceStore | None = None,
             clock: Callable[[], datetime] | None = None) -> str:
    """`describe_now` for \a policy: the place and time zone only with `location.read`."""
    located = bool(policy.allows("location.read"))
    place = (store if store is not None else PlaceStore()).load() if located else None
    moment = clock() if clock is not None else datetime.now().astimezone()
    return describe_now(moment, place=place, located=located)
