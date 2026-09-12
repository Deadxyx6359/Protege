"""Where the person is, and the weather there — the `Place` bridge.

Setting a place grants nothing. Models are told it, with the time zone and the
weather, only while `location.read` is granted; see
`akira.core.context.place`. The scenes use its hemisphere to turn the seasons
the right way round, and its weather to draw the sky, which needs no permission
of its own because nothing leaves the screen. Reading the weather does:
`location.read` and `net.http` for its site, checked before every reading (see
`akira.core.context.weather`).

Looking a place up and reading the weather happen on worker threads, and their
results cross back on queued signals.
"""

from __future__ import annotations

import threading
from datetime import date

from PySide6.QtCore import Property, QObject, Signal, Slot

from akira.core.context.place import (MAX_NAME_CHARS, PlaceError, PlaceStore, check_place,
                                        season)
from akira.core.context.weather import SITE, Found, Weather, WeatherError

NO_WEATHER = "Weather is not available here."


class PlaceBridge(QObject):
    """The place the person set, its hemisphere, and its weather."""

    placeChanged = Signal()
    weatherChanged = Signal()
    lookupChanged = Signal()

    #: Private: from a worker, or the weather's thread, to this one.
    _weatherUpdated = Signal()
    _looked = Signal(object, str)

    def __init__(self, store: PlaceStore | None = None, weather: Weather | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store if store is not None else PlaceStore()
        self._place = self._store.load()
        self._weather = weather
        self._candidates: list[Found] = []
        self._lookup_note = ""
        self._looking = False
        self._weatherUpdated.connect(self.weatherChanged)
        self._looked.connect(self._on_looked)
        if weather is not None:
            weather.set_on_change(self._weatherUpdated.emit)

    @property
    def store(self) -> PlaceStore:
        return self._store

    @property
    def reader(self) -> Weather | None:
        """What reads the weather, for the shell to keep fresh."""
        return self._weather

    # -- the place ----------------------------------------------------------------------------

    @Property(str, notify=placeChanged)
    def name(self) -> str:
        return self._place.name

    @Property(str, notify=placeChanged)
    def hemisphere(self) -> str:
        """`north`, `south`, or "" when not given."""
        return self._place.hemisphere

    @Property(bool, notify=placeChanged)
    def southernHemisphere(self) -> bool:
        """For `SceneHost.southernHemisphere`."""
        return self._place.southern

    @Property(str, notify=placeChanged)
    def season(self) -> str:
        """Today's season in that hemisphere, by the scenes' own rule."""
        return season(date.today(), self._place.southern)

    @Property(bool, notify=placeChanged)
    def hasPosition(self) -> bool:
        """Whether the place has a position, which the weather needs."""
        return self._place.coordinates is not None

    @Property(float, notify=placeChanged)
    def latitude(self) -> float:
        """0 when there is no position; see `hasPosition`."""
        return self._place.latitude if self._place.latitude is not None else 0.0

    @Property(float, notify=placeChanged)
    def longitude(self) -> float:
        return self._place.longitude if self._place.longitude is not None else 0.0

    @Slot(str, str, result=str)
    def setPlace(self, name: str, hemisphere: str) -> str:
        """Keep where the person is. Returns "" or why not. A new name forgets
        the position that went with the old one."""
        same = " ".join((name or "").split()) == self._place.name
        latitude, longitude = self._place.coordinates if same and self._place.coordinates \
            else (None, None)
        return self._keep(name, hemisphere, latitude, longitude)

    @Slot(float, float, result=str)
    def setPosition(self, latitude: float, longitude: float) -> str:
        """Give the place a position, for its weather. It decides the hemisphere.
        Returns "" or why not."""
        return self._keep(self._place.name, "", latitude, longitude)

    @Slot()
    def clearPlace(self) -> None:
        self._store.clear()
        self._place = self._store.load()
        if self._weather is not None:
            self._weather.forget()
        self.placeChanged.emit()
        self.weatherChanged.emit()

    def _keep(self, name: str, hemisphere: str, latitude, longitude) -> str:
        try:
            place = check_place(name, hemisphere, latitude, longitude)
            self._store.save(place)
        except PlaceError as exc:
            return str(exc)
        except OSError as exc:
            return f"The place could not be saved: {exc}"
        moved = place.coordinates != self._place.coordinates
        self._place = place
        self.placeChanged.emit()
        if moved:
            if self._weather is not None:
                # The old reading was for somewhere else.
                self._weather.forget()
                if not self._weather.ready():
                    self._refresh()
            self.weatherChanged.emit()
        return ""

    # -- looking a place up ---------------------------------------------------------------------

    @Property("QVariantList", notify=lookupChanged)
    def candidates(self) -> list:
        """What the last lookup found, best first: `label`, `latitude`, `longitude`."""
        return [{"label": found.label, "latitude": found.latitude, "longitude": found.longitude}
                for found in self._candidates]

    @Property(str, notify=lookupChanged)
    def lookupNote(self) -> str:
        """Why the last lookup found nothing, or ""."""
        return self._lookup_note

    @Property(bool, notify=lookupChanged)
    def lookingUp(self) -> bool:
        return self._looking

    @Slot(str, result=str)
    def findPlace(self, text: str) -> str:
        """Look a place up by name, on a worker. Returns "" once started, or why
        not. `candidates` fills, or `lookupNote` says why nothing was found."""
        if self._weather is None:
            return NO_WEATHER
        if self._looking:
            return "Still looking."
        query = " ".join((text or "").split())
        if not query:
            return "Type the name of a place to look for."
        self._looking, self._lookup_note = True, ""
        self.lookupChanged.emit()
        threading.Thread(target=self._find, args=(query,), name="place-lookup",
                         daemon=True).start()
        return ""

    def _find(self, query: str) -> None:
        """Worker thread. Emits a signal; touches no Qt property."""
        try:
            found, note = self._weather.find(query), ""
        except WeatherError as exc:
            found, note = [], str(exc)
        except Exception as exc:  # noqa: BLE001 - a crashed lookup must still report back
            found, note = [], f"The lookup failed: {exc}"
        self._looked.emit(found, note)

    @Slot(object, str)
    def _on_looked(self, found, note: str) -> None:
        self._candidates, self._lookup_note, self._looking = list(found), note, False
        self.lookupChanged.emit()

    @Slot(int, result=str)
    def choosePlace(self, index: int) -> str:
        """Keep one of `candidates` as the place, with its position. "" or why not."""
        if not 0 <= index < len(self._candidates):
            return "Choose one of the places found."
        found = self._candidates[index]
        problem = self._keep(found.label[:MAX_NAME_CHARS], "", found.latitude, found.longitude)
        if not problem:
            self._candidates, self._lookup_note = [], ""
            self.lookupChanged.emit()
        return problem

    # -- the weather --------------------------------------------------------------------------

    def _reading(self):
        return self._weather.current() if self._weather is not None else None

    @Property(str, notify=weatherChanged)
    def weather(self) -> str:
        """**For `SceneHost.weather`**: one of the scenes' names, or "" when there
        is no current reading, so the scene keeps its own default."""
        reading = self._reading()
        return reading.condition if reading is not None else ""

    @Property(str, notify=weatherChanged)
    def weatherSummary(self) -> str:
        """e.g. "14°C, light rain", or "" when there is no current reading."""
        reading = self._reading()
        return reading.summary if reading is not None else ""

    @Property(float, notify=weatherChanged)
    def weatherAt(self) -> float:
        """When the reading was taken, in epoch seconds. 0 when there is none."""
        reading = self._reading()
        return reading.at if reading is not None else 0.0

    @Property(str, notify=weatherChanged)
    def weatherNote(self) -> str:
        """Why there is no current reading, written for the person, or ""."""
        if self._weather is None:
            return NO_WEATHER
        return self._weather.note if self._reading() is None else ""

    @Property(str, constant=True)
    def weatherSite(self) -> str:
        """The site to allow with `net.http` for the weather and for lookups."""
        return SITE

    @Slot(result=str)
    def refreshWeather(self) -> str:
        """Read the weather now, on a worker. Returns "" once started, or why not."""
        if self._weather is None:
            return NO_WEATHER
        problem = self._weather.ready()
        if problem:
            return problem
        self._refresh()
        return ""

    def _refresh(self) -> None:
        threading.Thread(target=self._weather.refresh_now, name="weather-now",
                         daemon=True).start()
