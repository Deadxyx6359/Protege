"""The weather (C7): read for the place's position only with `location.read`
and `net.http` for its site, sent approximately, turned into the scenes' own
names, kept fresh, and told to models only while it is fresh and only for the
place it was read for.

The fetcher is a stand-in unless a test says otherwise. Nothing here touches
the network.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from akira.core.context import weather as weather_module
from akira.core.context.place import PlaceStore, check_place, now_line
from akira.core.context.weather import (EVERY_S, STALE_S, WEATHER, Reading, Weather,
                                          WeatherError, WeatherStore, condition,
                                          forecast_address)
from akira.core.net import NetError, Response
from akira.core.net import client as net
from akira.core.permissions import AuditLog, Policy

from test_net import PUBLIC, Reply, Site

BRISTOL = (51.45, -2.59)
WORLD_JS = (Path(__file__).resolve().parents[1] / "akira" / "ui" / "qml" / "Akira" / "scenes"
            / "world.js")


class Web:
    """Stands in for the chokepoint, and keeps what was asked."""

    def __init__(self):
        self.answer = None
        self.asked = []

    def __call__(self, url, *, policy, audit=None, actor="assistant", max_bytes=None):
        self.asked.append(url)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now

    def later(self, seconds):
        self.now += seconds


def forecast(code=61, temperature=14.24, wind=12.3):
    body = json.dumps({"current": {"time": "2026-09-11T10:15", "temperature_2m": temperature,
                                   "weather_code": code, "wind_speed_10m": wind}}).encode()
    return Response(weather_module.FORECAST, 200, "OK", "application/json", body)


def places(*results):
    return Response(weather_module.GEOCODER, 200, "OK", "application/json",
                    json.dumps({"results": list(results)}).encode())


BRISTOL_FOUND = {"name": "Bristol", "latitude": 51.45523, "longitude": -2.59665,
                 "admin1": "England", "country": "United Kingdom"}


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def allowed():
    policy = Policy()
    policy.grant("location.read")
    policy.grant("net.http", ("open-meteo.com",))
    return policy


@pytest.fixture
def web():
    return Web()


@pytest.fixture
def clock():
    return Clock()


def reader(tmp_path, policy, web, clock, where=BRISTOL):
    return Weather(policy=lambda: policy, where=lambda: where,
                   store=WeatherStore(tmp_path / "weather.json"),
                   audit=AuditLog(tmp_path / "audit.jsonl"), fetch=web, clock=clock)


# -- the scenes' words --------------------------------------------------------------------------


def test_the_names_are_the_scenes_own():
    listed = re.search(r"var WEATHER = \[(.*?)\];", WORLD_JS.read_text(encoding="utf-8"), re.S)
    assert listed, "world.js no longer lists its weather"
    assert tuple(re.findall(r'"(\w+)"', listed.group(1))) == WEATHER
    produced = {condition(code, wind)[0] for code in weather_module._CODES for wind in (0, 45, 70)}
    assert produced <= set(WEATHER)


@pytest.mark.parametrize("code,wind,name", [
    (0, 5, "clear"), (1, 5, "fair"), (2, 45, "windy"), (3, 70, "gale"), (45, 50, "fog"),
    (51, 5, "drizzle"), (61, 10, "rain"), (65, 10, "downpour"), (63, 70, "gale"),
    (71, 10, "snow"), (75, 45, "blizzard"), (73, 70, "blizzard"), (95, 30, "thunder"),
])
def test_a_reading_becomes_a_scene(code, wind, name):
    assert condition(code, wind)[0] == name


def test_a_code_that_is_not_one_is_not_guessed_at():
    with pytest.raises(WeatherError, match="code 42"):
        condition(42, 0)


# -- reading ----------------------------------------------------------------------------------


def test_nothing_is_sent_without_a_position_and_both_grants(tmp_path, web, clock):
    location_only, site_only = Policy(), Policy()
    location_only.grant("location.read")
    site_only.grant("net.http", ("open-meteo.com",))
    for policy, where, reason in [(location_only, None, "Set where you are"),
                                  (site_only, BRISTOL, "uses where you are"),
                                  (location_only, BRISTOL, "read from open-meteo.com")]:
        weather = reader(tmp_path, policy, web, clock, where)
        with pytest.raises(WeatherError, match=reason):
            weather.refresh()
        weather.poll()
        assert reason in weather.note
    assert web.asked == []


def test_the_position_is_sent_approximately_and_the_reading_kept(tmp_path, allowed, web, clock):
    web.answer = forecast(61, 14.24, 12.3)
    weather = reader(tmp_path, allowed, web, clock)
    reading = weather.refresh()
    [address] = web.asked
    assert address.startswith("https://api.open-meteo.com/v1/forecast?")
    assert "latitude=51.5" in address and "longitude=-2.6" in address
    assert "51.45" not in address, "the position was sent more precisely than it needs"
    assert (reading.condition, reading.description, reading.temperature, reading.wind) == \
        ("rain", "light rain", 14.2, 12.3)
    assert reading.summary == "14°C, light rain"
    assert weather.current() == reading
    assert WeatherStore(tmp_path / "weather.json").load() == reading


@pytest.mark.parametrize("body,reason", [
    (b"not json", "could not be read"),
    (json.dumps({"hourly": {}}).encode(), "did not say"),
    (json.dumps({"current": {"weather_code": 42, "temperature_2m": 10,
                             "wind_speed_10m": 1}}).encode(), "code 42"),
    (b'{"current": {"weather_code": 0, "temperature_2m": NaN, "wind_speed_10m": 1}}',
     "did not make sense"),
])
def test_an_answer_that_cannot_be_read_is_not_used(tmp_path, allowed, web, clock, body, reason):
    web.answer = Response(weather_module.FORECAST, 200, "OK", "application/json", body)
    weather = reader(tmp_path, allowed, web, clock)
    with pytest.raises(WeatherError, match=reason):
        weather.refresh()
    assert weather.current() is None


def test_readings_are_kept_fresh_a_failure_waits_and_stale_is_not_now(tmp_path, allowed, web,
                                                                        clock):
    weather = reader(tmp_path, allowed, web, clock)
    heard = []
    weather.set_on_change(lambda: heard.append(1))
    web.answer = NetError("Could not reach api.open-meteo.com: timed out")
    weather.poll()
    assert weather.note == "Could not reach api.open-meteo.com: timed out" and heard
    weather.poll()
    assert len(web.asked) == 1, "a service that was down was asked again at once"

    clock.later(EVERY_S)
    web.answer = forecast()
    weather.poll()
    assert weather.note == "" and weather.current().condition == "rain" and len(web.asked) == 2
    clock.later(60)
    weather.poll()
    assert len(web.asked) == 2, "a fresh reading was read again"

    web.answer = NetError("down again")
    clock.later(STALE_S)
    heard.clear()
    weather.poll()
    assert weather.current() is None and weather.note == "down again" and heard


def test_forgetting_drops_the_reading(tmp_path, allowed, web, clock):
    web.answer = forecast()
    weather = reader(tmp_path, allowed, web, clock)
    weather.refresh()
    weather.forget()
    assert weather.current() is None and not (tmp_path / "weather.json").exists()


# -- what models hear ---------------------------------------------------------------------------


def test_models_hear_the_weather_only_while_located_fresh_and_for_that_place(tmp_path):
    kept = PlaceStore(tmp_path / "place.json")
    kept.save(check_place("Bristol, UK", "", *BRISTOL))
    readings = WeatherStore(tmp_path / "weather.json")
    moment = datetime(2026, 9, 11, 10, 20, tzinfo=timezone.utc)
    readings.save(Reading("rain", "light rain", 14.2, 12.3, moment.timestamp() - 600, *BRISTOL))
    policy = Policy()

    def line(at=moment):
        return now_line(policy, store=kept, clock=lambda: at, weather=readings)

    assert "rain" not in line()
    policy.grant("location.read")
    assert "was light rain, 14°C, with the wind at 12 km/h." in line()
    assert "rain" not in line(moment + timedelta(seconds=STALE_S + 1)), \
        "stale weather was given as the weather now"
    kept.save(check_place("Sydney", "", -33.87, 151.21))
    assert "rain" not in line(), "Bristol's weather was given for Sydney"


# -- looking a place up -----------------------------------------------------------------------


def test_a_place_is_looked_up_on_the_geocoder(tmp_path, allowed, web, clock):
    web.answer = places(BRISTOL_FOUND,
                        {"name": "Bristol", "latitude": 41.67176, "longitude": -72.94927,
                         "admin1": "Connecticut", "country": "United States"},
                        {"name": "Nowhere", "latitude": 200, "longitude": 0},
                        "not a place")
    weather = reader(tmp_path, allowed, web, clock)
    found = weather.find("  Bristol ")
    assert [f.label for f in found] == ["Bristol, England, United Kingdom",
                                        "Bristol, Connecticut, United States"]
    assert (found[0].latitude, found[0].longitude) == (51.46, -2.6)
    [address] = web.asked
    assert address.startswith("https://geocoding-api.open-meteo.com/v1/search?")
    assert "name=Bristol&" in address

    web.answer = Response(weather_module.GEOCODER, 200, "OK", "application/json", b"{}")
    with pytest.raises(WeatherError, match="No place called Atlantis"):
        weather.find("Atlantis")


def test_a_lookup_needs_the_site_but_not_the_location(tmp_path, web, clock):
    site_only = Policy()
    site_only.grant("net.http", ("open-meteo.com",))
    web.answer = places(BRISTOL_FOUND)
    assert reader(tmp_path, site_only, web, clock).find("Bristol")
    with pytest.raises(WeatherError, match="Not permitted"):
        reader(tmp_path, Policy(), web, clock).find("Bristol")
    assert len(web.asked) == 1


# -- through the real door ----------------------------------------------------------------------


def test_through_the_chokepoint_the_log_keeps_no_position(tmp_path, allowed, monkeypatch):
    path = forecast_address(*BRISTOL).split("open-meteo.com", 1)[1]
    site = Site({("api.open-meteo.com", path): Reply(200, forecast().body,
                                                     {"Content-Type": "application/json"})})
    monkeypatch.setattr(net, "_resolve", lambda host, port: [PUBLIC])
    monkeypatch.setattr(net, "_open", site.open)
    weather = Weather(policy=lambda: allowed, where=lambda: BRISTOL,
                      store=WeatherStore(tmp_path / "weather.json"),
                      audit=AuditLog(tmp_path / "audit.jsonl"))
    assert weather.refresh().condition == "rain"
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "api.open-meteo.com" in log and '"weather"' in log
    assert "51.5" not in log and "-2.6" not in log, "the position reached the activity log"
