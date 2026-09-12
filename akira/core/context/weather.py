"""The weather where the person is (C7): for the scenes to draw, and for models
to be told.

It is read from Open-Meteo, which needs no account and no key, so nothing of the
person's is sent but an approximate position. The request goes through the
chokepoint like any page, and only while two grants hold, both checked before
every reading: `location.read`, because it uses where the person is, and
`net.http` for open-meteo.com, because it asks a site. Without either, nothing
is sent, and `note` says which is missing.

**Approximate by construction.** A place's position is kept to two decimals,
about a kilometre, and sent to one, about eleven: enough to know whether it is
raining, not enough to find a street. The activity log keeps the request
without its query, so the position is not written there either.

**In the scenes' words.** A reading becomes one of the scenes' weather names
(`WEATHER`, the same list as `scenes/world.js`), so the renderer never has to
interpret a forecast. A reading more than `STALE_S` old is not the weather now,
and is not reported as if it were.

Finding a place's position from its name is a lookup on Open-Meteo's geocoder,
which the person asks for, under `net.http` for the same site.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from akira.core.config import config_dir
from akira.core.net import NetError, host_of, with_query
from akira.core.net import fetch as net_fetch
from akira.core.permissions import AuditLog, Policy

#: The grant to ask for: it covers the forecast and the geocoder.
SITE = "open-meteo.com"
FORECAST = "https://api.open-meteo.com/v1/forecast"
GEOCODER = "https://geocoding-api.open-meteo.com/v1/search"

#: How often the weather is read, and how old a reading may be and still be now.
EVERY_S = 30 * 60
STALE_S = 3 * 3600
POLL_S = 60.0

MAX_BYTES = 200_000
MAX_FOUND = 5
MAX_QUERY_CHARS = 80
MAX_LABEL_CHARS = 80

#: Who the activity log records as asking.
ACTOR = "weather"

#: The scenes' names for the weather, as in `scenes/world.js`. A test keeps the two the same.
WEATHER = ("clear", "fair", "cloudy", "overcast", "fog", "drizzle", "rain", "downpour",
           "thunder", "windy", "gale", "snow", "blizzard")

WINDY_KMH = 40.0
GALE_KMH = 62.0

#: WMO weather codes, as Open-Meteo reports them: the scenes' name, and words for people.
_CODES = {
    0: ("clear", "clear sky"),
    1: ("fair", "mainly clear"),
    2: ("cloudy", "partly cloudy"),
    3: ("overcast", "overcast"),
    45: ("fog", "fog"),
    48: ("fog", "freezing fog"),
    51: ("drizzle", "light drizzle"),
    53: ("drizzle", "drizzle"),
    55: ("drizzle", "heavy drizzle"),
    56: ("drizzle", "freezing drizzle"),
    57: ("drizzle", "heavy freezing drizzle"),
    61: ("rain", "light rain"),
    63: ("rain", "rain"),
    65: ("downpour", "heavy rain"),
    66: ("rain", "freezing rain"),
    67: ("downpour", "heavy freezing rain"),
    71: ("snow", "light snow"),
    73: ("snow", "snow"),
    75: ("snow", "heavy snow"),
    77: ("snow", "snow grains"),
    80: ("rain", "light showers"),
    81: ("rain", "showers"),
    82: ("downpour", "violent showers"),
    85: ("snow", "snow showers"),
    86: ("snow", "heavy snow showers"),
    95: ("thunder", "a thunderstorm"),
    96: ("thunder", "a thunderstorm with hail"),
    99: ("thunder", "a thunderstorm with heavy hail"),
}

_CALM = frozenset({"clear", "fair", "cloudy", "overcast"})
_WET = frozenset({"drizzle", "rain", "downpour"})


class WeatherError(RuntimeError):
    """No reading, with a reason for the person."""


def condition(code: int, wind_kmh: float) -> tuple[str, str]:
    """The scenes' name for the weather, and words for it, from a WMO code and
    the wind. Raises `WeatherError` for a code that is not one."""
    try:
        name, words = _CODES[code]
    except KeyError:
        raise WeatherError(f"{SITE} reported weather code {code}, which is not one Akira "
                           "knows.") from None
    if name == "snow" and (wind_kmh >= GALE_KMH or (code in (75, 86) and wind_kmh >= WINDY_KMH)):
        name = "blizzard"
    elif wind_kmh >= GALE_KMH and (name in _CALM or name in _WET):
        name = "gale"
    elif wind_kmh >= WINDY_KMH and name in _CALM:
        name = "windy"
    return name, words


@dataclass(frozen=True)
class Reading:
    condition: str
    """One of `WEATHER`."""

    description: str
    temperature: float
    """Degrees Celsius."""

    wind: float
    """Kilometres an hour."""

    at: float
    """When it was read, in epoch seconds."""

    latitude: float
    longitude: float

    @property
    def summary(self) -> str:
        return f"{int(round(self.temperature))}°C, {self.description}"

    def sentence(self) -> str:
        """For a model."""
        when = datetime.fromtimestamp(self.at).strftime("%H:%M")
        return (f"The weather there at {when} was {self.description}, "
                f"{int(round(self.temperature))}°C, with the wind at "
                f"{int(round(self.wind))} km/h.")

    def near(self, coordinates: tuple[float, float] | None) -> bool:
        """Whether this was read for \a coordinates, to the precision it was asked at."""
        return coordinates is not None and (
            (round(self.latitude, 1), round(self.longitude, 1))
            == (round(coordinates[0], 1), round(coordinates[1], 1)))


@dataclass(frozen=True)
class Found:
    """A place a lookup found: how to name it, and where it is."""

    label: str
    latitude: float
    longitude: float


class WeatherStore:
    """`weather.json`: the last reading, so the scenes and models have it straight after a start."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_dir() / "weather.json"

    def load(self) -> Reading | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            reading = Reading(str(raw["condition"]), str(raw["description"]),
                              float(raw["temperature"]), float(raw["wind"]), float(raw["at"]),
                              float(raw["latitude"]), float(raw["longitude"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return reading if reading.condition in WEATHER else None

    def save(self, reading: Reading) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(asdict(reading), stream, ensure_ascii=False)
            os.replace(temporary, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()

    def current(self, coordinates: tuple[float, float] | None, now: float) -> Reading | None:
        """The last reading, if it was for \a coordinates and is not stale at \a now."""
        reading = self.load()
        if reading is None or not reading.near(coordinates):
            return None
        return reading if 0 <= now - reading.at <= STALE_S else None


def forecast_address(latitude: float, longitude: float) -> str:
    """Where the reading for a position is asked for: the position to one decimal,
    about eleven kilometres, and nothing else about the person."""
    return with_query(FORECAST, {"latitude": f"{latitude:.1f}", "longitude": f"{longitude:.1f}",
                                 "current": "temperature_2m,weather_code,wind_speed_10m",
                                 "wind_speed_unit": "kmh"})


def _json(response) -> object:
    if not response.ok:
        raise WeatherError(f"{SITE} answered {response.status} {response.reason}.")
    if response.truncated:
        raise WeatherError(f"{SITE}'s answer was too large to read.")
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise WeatherError(f"{SITE}'s answer could not be read.") from None


def _reading(data, coordinates: tuple[float, float], at: float) -> Reading:
    try:
        current = data["current"]
        code = int(current["weather_code"])
        temperature = float(current["temperature_2m"])
        wind = float(current["wind_speed_10m"])
    except (KeyError, TypeError, ValueError):
        raise WeatherError(f"{SITE}'s answer did not say what the weather is.") from None
    if not (-90.0 < temperature < 60.0 and 0.0 <= wind < 400.0):
        raise WeatherError(f"{SITE}'s answer did not make sense, so it was not used.")
    name, words = condition(code, wind)
    return Reading(name, words, round(temperature, 1), round(wind, 1), at, *coordinates)


class Weather:
    """Keeps a reading for the person's place, while the grants allow."""

    def __init__(self, *, policy: Callable[[], Policy],
                 where: Callable[[], tuple[float, float] | None],
                 store: WeatherStore | None = None, audit: AuditLog | None = None,
                 fetch: Callable | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        self._policy = policy
        self._where = where
        self._store = store if store is not None else WeatherStore()
        self._audit = audit
        # The chokepoint, unless a test stands in for it.
        self._fetch = fetch if fetch is not None else net_fetch
        self._clock = clock if clock is not None else time.time
        self._busy = threading.Lock()
        self._on_change: Callable[[], None] | None = None
        self._tried = 0.0
        self._shown = False
        self.note = ""
        """Why there is no current reading, written for the person, or ""."""

    @property
    def store(self) -> WeatherStore:
        return self._store

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        """Called, from any thread, when the reading or the note changes."""
        self._on_change = callback

    def _changed(self) -> None:
        callback = self._on_change
        if callback is not None:
            with contextlib.suppress(Exception):
                callback()

    def current(self) -> Reading | None:
        """The reading for the place as it is now, if there is a fresh one."""
        return self._store.current(self._where(), self._clock())

    def ready(self) -> str:
        """Why the weather cannot be read now, or "" if it can. Nothing is sent to find out."""
        if self._where() is None:
            return "Set where you are, with its position, to see the weather there."
        policy = self._policy()
        decision = policy.allows("location.read")
        if not decision:
            return f"Not permitted: {decision.reason}. Reading the weather uses where you are."
        decision = policy.allows("net.http", host_of(FORECAST))
        if not decision:
            return f"Not permitted: {decision.reason}. The weather is read from {SITE}."
        return ""

    def refresh(self) -> Reading:
        """Read the weather now and keep it. Raises `WeatherError` with the reason."""
        problem = self.ready()
        coordinates = self._where()
        if problem or coordinates is None:
            raise WeatherError(problem or "There is no position to read the weather for.")
        try:
            response = self._fetch(forecast_address(*coordinates), policy=self._policy(),
                                   audit=self._audit, actor=ACTOR, max_bytes=MAX_BYTES)
        except NetError as exc:
            raise WeatherError(str(exc)) from None
        reading = _reading(_json(response), coordinates, self._clock())
        try:
            self._store.save(reading)
        except OSError as exc:
            raise WeatherError(f"The weather could not be kept: {exc}") from None
        return reading

    def poll(self) -> None:
        """For the service thread: read the weather when it is due, and say so."""
        if not self._busy.acquire(blocking=False):
            return
        try:
            self._poll()
        finally:
            self._busy.release()

    def _poll(self) -> None:
        now, problem = self._clock(), self.ready()
        reading = None if problem else self.current()
        due = not problem and (reading is None or now - reading.at >= EVERY_S)
        # A failed reading waits its turn like any other, so a service that is
        # down is not asked again every minute.
        if due and not (self._tried and 0 <= now - self._tried < EVERY_S):
            self._tried = now
            try:
                self.refresh()
                problem = ""
            except WeatherError as exc:
                problem = str(exc)
        self._settle(problem)

    def refresh_now(self) -> None:
        """For a worker the person started: read the weather now, whatever the time."""
        if not self._busy.acquire(blocking=False):
            return
        try:
            self._tried = self._clock()
            try:
                self.refresh()
                problem = ""
            except WeatherError as exc:
                problem = str(exc)
            self._settle(problem, always=True)
        finally:
            self._busy.release()

    def _settle(self, note: str, *, always: bool = False) -> None:
        """Take \a note, and tell the interface if it or what is shown changed,
        including a reading that has just gone stale."""
        shown = self.current() is not None
        if always or note != self.note or shown != self._shown:
            self.note, self._shown = note, shown
            self._changed()

    def forget(self) -> None:
        """The place moved or went, so its reading, and any problem with it, no longer apply."""
        with contextlib.suppress(OSError):
            self._store.clear()
        self.note, self._tried, self._shown = "", 0.0, False
        self._changed()

    def find(self, text: str) -> list[Found]:
        """Places called \a text, best first. Raises `WeatherError` with the reason."""
        query = " ".join((text or "").split())
        if not query:
            raise WeatherError("Type the name of a place to look for.")
        if len(query) > MAX_QUERY_CHARS:
            raise WeatherError(f"A place to look for is at most {MAX_QUERY_CHARS} characters.")
        policy = self._policy()
        decision = policy.allows("net.http", host_of(GEOCODER))
        if not decision:
            raise WeatherError(f"Not permitted: {decision.reason}. Looking a place up asks {SITE}.")
        address = with_query(GEOCODER, {"name": query, "count": str(MAX_FOUND),
                                        "language": "en", "format": "json"})
        try:
            response = self._fetch(address, policy=policy, audit=self._audit, actor=ACTOR,
                                   max_bytes=MAX_BYTES)
        except NetError as exc:
            raise WeatherError(str(exc)) from None
        data = _json(response)
        results = data.get("results") if isinstance(data, dict) else None
        found: list[Found] = []
        for item in results if isinstance(results, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                latitude, longitude = float(item["latitude"]), float(item["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
                continue
            parts = (" ".join(str(item.get(key) or "").split())
                     for key in ("name", "admin1", "country"))
            label = ", ".join(dict.fromkeys(part for part in parts if part))
            if label:
                found.append(Found(label[:MAX_LABEL_CHARS], round(latitude, 2),
                                   round(longitude, 2)))
            if len(found) >= MAX_FOUND:
                break
        if not found:
            raise WeatherError(f"No place called {query} was found.")
        return found


class WeatherService:
    """The thread that keeps the reading fresh."""

    def __init__(self, weather: Weather, *, interval_s: float = POLL_S) -> None:
        self._weather = weather
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="weather", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            # The thread must outlive any one reading.
            with contextlib.suppress(Exception):
                self._weather.poll()
            self._stop.wait(self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
