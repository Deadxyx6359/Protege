"""Calendar and weather regressions that would otherwise show the wrong art."""
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine


@pytest.fixture(scope="module")
def world():
    app = QCoreApplication.instance() or QCoreApplication([])
    engine = QJSEngine()
    path = Path(__file__).resolve().parents[1] / "akira/ui/qml/Akira/scenes/world.js"
    source = path.read_text(encoding="utf-8").replace(".pragma library", "")
    result = engine.evaluate(source, str(path))
    assert not result.isError(), result.toString()
    yield engine
    del engine


@pytest.mark.parametrize("year,month,day,southern,expected", [
    (2026, 9, 10, False, "summer"),
    (2024, 9, 21, False, "summer"),
    (2024, 9, 22, False, "autumn"),
    (2026, 3, 19, False, "winter"),
    (2026, 3, 20, False, "spring"),
    (2024, 6, 20, False, "spring"),
    (2024, 6, 21, False, "summer"),
    (2026, 12, 21, False, "winter"),
    (2026, 9, 10, True, "winter"),
    (2026, 12, 25, True, "summer"),
])
def test_season_calendar(world, year, month, day, southern, expected):
    result = world.evaluate(f"season(new Date({year},{month-1},{day}),{str(southern).lower()})")
    assert result.toString() == expected


def test_dst_does_not_move_calendar_back_a_day(world):
    # Sept 10 is day 253 even at midnight in a daylight-saving timezone.
    assert world.evaluate("dayOfYear(new Date(2026,8,10,0,0))").toInt() == 253


def test_winter_progress_does_not_restart_on_new_year(world):
    before = world.evaluate("seasonProgress(new Date(2025,11,31))").toNumber()
    after = world.evaluate("seasonProgress(new Date(2026,0,1))").toNumber()
    assert 0 < before < after < 0.2


@pytest.mark.parametrize("raw,expected", [
    ("downpour", "downpour"), ("fair", "fair"), ("light rain", "drizzle"),
    ("heavy rain", "downpour"), ("Thunderstorm", "thunder"),
    ("blizzard", "blizzard"), ("windy", "windy"), ("fog", "fog"),
])
def test_weather_keeps_intensity(world, raw, expected):
    import json
    assert world.evaluate(f"normaliseWeather({json.dumps(raw)})").toString() == expected
