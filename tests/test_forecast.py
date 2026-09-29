"""The forecast is read from Open-Meteo for the place and days asked about, not guessed."""

from __future__ import annotations

import json
from datetime import date

import pytest

from akira.core.context.forecast import days_asked, forecast_lines, place_named
from akira.core.net import NetError
from akira.core.permissions import Policy

TUESDAY = date(2026, 9, 29)


class Reply:
    def __init__(self, data):
        self.ok, self.status, self.reason, self.truncated = True, 200, "OK", False
        self.body = json.dumps(data).encode("utf-8")


class OpenMeteo:
    """Answers the geocoder and the forecast, and keeps what was asked."""

    def __init__(self):
        self.asked = []

    def __call__(self, url, *, policy, audit=None, actor="", max_bytes=0, **_):
        self.asked.append(url)
        if not policy.allows("net.http", url.split("/")[2]):
            raise NetError("not allowed")
        if "geocoding-api" in url:
            return Reply({"results": [
                {"name": "Paris", "admin1": "Île-de-France", "country": "France",
                 "latitude": 48.85, "longitude": 2.35},
                {"name": "Paris", "admin1": "Texas", "country": "United States",
                 "latitude": 33.66, "longitude": -95.56}]})
        days = [f"2026-09-{29 + i}" if i < 2 else f"2026-10-0{i - 1}" for i in range(7)]
        return Reply({"daily": {"time": days, "weather_code": [61] * 7,
                                "temperature_2m_min": [9.2] * 7,
                                "temperature_2m_max": [15.4] * 7,
                                "precipitation_probability_max": [70] * 7,
                                "wind_speed_10m_max": [24.6] * 7}})


def weather_allowed(*more):
    policy = Policy()
    policy.grant("net.http", ("open-meteo.com",))
    for capability in more:
        policy.grant(capability)
    return policy


@pytest.mark.parametrize("message, place", [
    ("What's the weather in Leeds tomorrow?", ("Leeds", "")),
    ("weather for New York this weekend", ("New York", "")),
    ("Will it rain in Stratford upon Avon on Friday?", ("Stratford upon Avon", "")),
    ("weather in Paris, Texas today", ("Paris", "Texas")),
    ("What's the forecast for Saturday?", ("", "")),
])
def test_the_place_is_read_from_the_message(message, place):
    assert place_named(message) == place


@pytest.mark.parametrize("message, days", [
    ("What's the weather in Leeds tomorrow?", [1]),
    ("Is it sunny on Friday?", [3]),
    ("weather this weekend", [4, 5]),
    ("forecast for the week", [0, 1, 2, 3, 4, 5, 6]),
    ("What's the weather in Leeds?", [0, 1]),
])
def test_the_days_are_counted_from_today(message, days):
    assert days_asked(message, TUESDAY) == days


def test_the_forecast_for_a_named_place_goes_to_the_model():
    """Sent to research, "weather in Leeds tomorrow?" searched Wikipedia and found nothing."""
    site = OpenMeteo()
    lines = forecast_lines("Will it rain in Paris, Texas tomorrow?", weather_allowed(),
                           today=TUESDAY, fetch=site)
    assert lines.startswith("The forecast from open-meteo.com for Paris, Texas, United States")
    assert ("- Wednesday 30 September (tomorrow): light rain; 9 to 15°C (49 to 60°F); "
            "70% chance of rain; wind up to 25 km/h.") in lines
    assert "latitude=33.66" in site.asked[1]


def test_the_persons_own_place_is_used_only_with_location_read():
    site = OpenMeteo()
    assert forecast_lines("Will it rain tomorrow?", weather_allowed(), today=TUESDAY,
                          here=(53.81, -1.55), fetch=site) == ""
    assert site.asked == []
    lines = forecast_lines("Will it rain tomorrow?", weather_allowed("location.read"),
                           today=TUESDAY, here=(53.81, -1.55), fetch=site)
    assert "for where the person is" in lines
    # To one decimal, as the weather service sends it.
    assert "latitude=53.8&longitude=-1.6" in site.asked[0]


def test_without_open_meteo_nothing_is_sent_and_the_model_is_told_not_to_guess():
    site = OpenMeteo()
    lines = forecast_lines("What's the weather in Leeds tomorrow?", Policy(), today=TUESDAY,
                           fetch=site)
    assert "not allowed" in lines and "do not guess" in lines and site.asked == []


@pytest.mark.parametrize("message", ["I love rainy days", "What is the capital of France?", ""])
def test_other_messages_read_nothing(message):
    site = OpenMeteo()
    assert forecast_lines(message, weather_allowed("location.read"), today=TUESDAY,
                          here=(53.81, -1.55), fetch=site) == ""
    assert site.asked == []
