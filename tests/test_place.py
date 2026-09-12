"""Now and here (C7, local half): the season by the scenes' own rule, the date
and time for every model, and the place and time zone only with `location.read`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from akira.core.agents import Agent, Trace
from akira.core.agents.roles import GATHERER
from akira.core.context.place import (Place, PlaceError, PlaceStore, check_place,
                                        describe_now, now_line, part_of_day, season)
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import ToolContext, default_registry


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


BST = timezone(timedelta(hours=1), "BST")
FRIDAY = datetime(2026, 9, 11, 14, 5, tzinfo=BST)


@pytest.mark.parametrize("day,north", [
    ((1, 5), "winter"), ((3, 19), "winter"), ((3, 20), "spring"), ((6, 20), "spring"),
    ((6, 21), "summer"), ((9, 21), "summer"), ((9, 22), "autumn"), ((12, 20), "autumn"),
    ((12, 21), "winter"),
])
def test_the_season_follows_the_scenes_rule(day, north):
    moment = date(2026, *day)
    assert season(moment) == north
    flipped = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}
    assert season(moment, southern=True) == flipped[north]


@pytest.mark.parametrize("clock,name", [
    ((4, 59), "night"), ((5, 0), "dawn"), ((7, 30), "morning"), ((10, 0), "day"),
    ((16, 30), "golden hour"), ((19, 0), "dusk"), ((21, 0), "night"),
])
def test_the_part_of_day_follows_the_scenes_names(clock, name):
    assert part_of_day(datetime(2026, 9, 11, *clock)) == name


def test_every_model_is_told_the_date_and_time():
    assert describe_now(FRIDAY) == "It is Friday 11 September 2026, 14:05 (day)."


def test_the_place_and_zone_only_when_location_may_be_known():
    here = Place("Bristol, UK", "north")
    assert describe_now(FRIDAY, place=here) == describe_now(FRIDAY)
    located = describe_now(FRIDAY, place=here, located=True)
    assert "The local time zone is BST (UTC+01:00)." in located
    assert "The person is in Bristol, UK." in located
    assert "northern hemisphere, where it is summer" in located
    assert "The person is in" not in describe_now(FRIDAY, place=Place(), located=True)


def test_a_place_is_checked_kept_and_forgotten(tmp_path):
    with pytest.raises(PlaceError):
        check_place("Bristol", "east")
    with pytest.raises(PlaceError):
        check_place("x" * 81, "")
    store = PlaceStore(tmp_path / "place.json")
    assert store.load() == Place()
    store.save(check_place("  Sydney,   Australia ", "South"))
    assert store.load() == Place("Sydney, Australia", "south")
    (tmp_path / "place.json").write_text("{broken", encoding="utf-8")
    assert store.load() == Place(), "a damaged place was guessed at"
    store.save(Place("Sydney", "south"))
    store.clear()
    assert store.load() == Place()


def test_a_position_is_checked_rounded_and_decides_the_hemisphere(tmp_path):
    place = check_place("Sydney", "north", -33.86785, 151.20732)
    assert place == Place("Sydney", "south", -33.87, 151.21)
    assert place.coordinates == (-33.87, 151.21)
    for latitude, longitude in [(91, 0), (0, 181), (float("nan"), 0), ("north", 0)]:
        with pytest.raises(PlaceError):
            check_place("x", "", latitude, longitude)
    with pytest.raises(PlaceError, match="both"):
        check_place("x", "", 10, None)
    store = PlaceStore(tmp_path / "place.json")
    store.save(place)
    assert store.load() == place


def test_location_permission_decides_what_the_model_hears(tmp_path):
    store = PlaceStore(tmp_path / "place.json")
    store.save(Place("Bristol, UK", "north"))
    policy = Policy()
    assert "Bristol" not in now_line(policy, store=store, clock=lambda: FRIDAY)
    policy.grant("location.read")
    assert "Bristol" in now_line(policy, store=store, clock=lambda: FRIDAY)


def test_agents_are_told_when_it_is(tmp_path):
    PlaceStore().save(Place("Bristol, UK", "north"))
    policy = Policy()
    context = ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                          secrets=SecretStore(tmp_path / "secrets"))
    agent = Agent(GATHERER, router=None, registry=default_registry(), context=context,
                  trace=Trace())
    prompt = agent.system_prompt()
    assert "It is " in prompt and "Bristol" not in prompt
    policy.grant("location.read")
    assert "Bristol" in agent.system_prompt()
