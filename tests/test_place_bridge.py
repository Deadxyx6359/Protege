"""The `Place` bridge: the person's place, checked and kept, the hemisphere the
scenes turn their seasons by, a lookup for its position, and the weather there
in the scenes' own words.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from akira.core.context.place import PlaceStore  # noqa: E402
from akira.core.context.weather import Found, Reading, WeatherError  # noqa: E402
from akira.ui.bridge.place import PlaceBridge  # noqa: E402


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return predicate()


class FakeWeather:
    """Stands in for the reader: no thread of its own, no network."""

    def __init__(self):
        self.note, self.reading, self.found = "", None, []
        self.refreshed = self.forgotten = 0
        self.callback = None

    def set_on_change(self, callback):
        self.callback = callback

    def current(self):
        return self.reading

    def ready(self):
        return ""

    def refresh_now(self):
        self.refreshed += 1

    def forget(self):
        self.forgotten += 1
        self.reading = None

    def find(self, text):
        if isinstance(self.found, Exception):
            raise self.found
        return list(self.found)


def test_a_place_is_set_checked_and_cleared(tmp_path):
    store = PlaceStore(tmp_path / "place.json")
    bridge = PlaceBridge(store)
    changes = []
    bridge.placeChanged.connect(lambda: changes.append(1))

    assert (bridge.name, bridge.hemisphere, bridge.southernHemisphere) == ("", "", False)
    assert bridge.setPlace("Sydney", "west") != "" and not changes
    assert bridge.setPlace("Sydney, Australia", "south") == ""
    assert bridge.name == "Sydney, Australia" and bridge.southernHemisphere and changes
    assert bridge.season in {"winter", "spring", "summer", "autumn"}
    assert PlaceBridge(store).name == "Sydney, Australia", "the place was not kept"

    bridge.clearPlace()
    assert (bridge.name, bridge.southernHemisphere) == ("", False)


def test_the_weather_is_in_the_scenes_words_and_says_why_when_missing(tmp_path, app):
    weather = FakeWeather()
    bridge = PlaceBridge(PlaceStore(tmp_path / "place.json"), weather)
    assert (bridge.weather, bridge.weatherSummary, bridge.weatherAt) == ("", "", 0.0)
    assert bridge.weatherSite == "open-meteo.com"
    weather.note = "Set where you are, with its position, to see the weather there."
    assert bridge.weatherNote == weather.note

    weather.reading = Reading("rain", "light rain", 14.2, 12.3, 1_800_000_000.0, 51.45, -2.59)
    assert (bridge.weather, bridge.weatherSummary, bridge.weatherNote) == \
        ("rain", "14°C, light rain", "")
    assert PlaceBridge(PlaceStore(tmp_path / "other.json")).weatherNote == \
        "Weather is not available here."


def test_a_position_decides_the_hemisphere_and_forgets_the_old_reading(tmp_path, app):
    weather = FakeWeather()
    bridge = PlaceBridge(PlaceStore(tmp_path / "place.json"), weather)
    assert bridge.setPosition(-33.87, 151.21) == ""
    assert bridge.hasPosition and bridge.southernHemisphere and bridge.latitude == -33.87
    assert weather.forgotten == 1
    assert pump_until(app, lambda: weather.refreshed == 1), "a new position did not read its weather"

    assert bridge.setPosition(100, 0) != "" and bridge.latitude == -33.87
    assert bridge.setPlace("", "south") == "" and bridge.hasPosition, \
        "keeping the name dropped the position"
    assert bridge.setPlace("Sydney", "") == "" and not bridge.hasPosition, \
        "a new name kept the old one's position"


def test_a_place_is_looked_up_on_a_worker_and_chosen(tmp_path, app):
    weather = FakeWeather()
    weather.found = [Found("Bristol, England, United Kingdom", 51.46, -2.6)]
    bridge = PlaceBridge(PlaceStore(tmp_path / "place.json"), weather)
    assert bridge.findPlace("   ") != ""
    assert bridge.findPlace("Bristol") == ""
    assert pump_until(app, lambda: bridge.candidates)
    assert bridge.candidates == [{"label": "Bristol, England, United Kingdom",
                                  "latitude": 51.46, "longitude": -2.6}]
    assert not bridge.lookingUp

    assert bridge.choosePlace(5) != ""
    assert bridge.choosePlace(0) == ""
    assert (bridge.name, bridge.latitude, bridge.hemisphere) == \
        ("Bristol, England, United Kingdom", 51.46, "north")
    assert bridge.candidates == []

    weather.found = WeatherError("No place called Atlantis was found.")
    assert bridge.findPlace("Atlantis") == ""
    assert pump_until(app, lambda: bridge.lookupNote)
    assert bridge.lookupNote == "No place called Atlantis was found." and bridge.candidates == []
