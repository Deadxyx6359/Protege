"""The calendar kept on this computer: events, repeats, and reminders that are due."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from akira.core import planner
from akira.core.planner import PlannerError, PlannerStore, draft, occurrences


@pytest.fixture
def store(tmp_path):
    return PlannerStore(tmp_path / "calendar.json")


def days(found):
    return [turn.first_day.isoformat() for turn in found]


# -- what the person says ---------------------------------------------------------------------------


def test_an_event_is_kept_as_it_was_said():
    event = draft("  Dentist  ", "2026-10-02T15:00", where="Leeds", notes="Bring the form.",
                  remind=30)
    assert (event.title, event.start, event.end) == (
        "Dentist", datetime(2026, 10, 2, 15, 0), datetime(2026, 10, 2, 16, 0))
    assert not event.all_day and event.remind == 30 and len(event.id) == 16
    day = draft("Holiday", "2026-10-05", "2026-10-09")
    assert day.all_day and (day.start, day.end) == (date(2026, 10, 5), date(2026, 10, 9))
    assert draft("Bins", "2026-10-05").end == date(2026, 10, 5)


def test_a_time_with_a_zone_is_turned_to_this_computers_own():
    event = draft("Call", "2026-10-02T15:00:30+00:00")
    assert event.start.tzinfo is None and event.start.second == 0


@pytest.mark.parametrize("arguments, why", [
    (("", "2026-10-02"), "needs a title"),
    (("Dentist", ""), "Give a start"),
    (("Dentist", "next Friday"), "not a date"),
    (("Dentist", "2026-10-02T15:00", "2026-10-02"), "both dates"),
    (("Dentist", "2026-10-02T15:00", "2026-10-02T14:00"), "before the start"),
    (("Dentist", "2026-10-02T15:00", "2026-10-02T15:00"), "same as the start"),
    (("Dentist", "2026-10-02", "2026-12-25"), "at most 31 days"),
])
def test_what_cannot_be_kept_is_refused_with_the_reason(arguments, why):
    with pytest.raises(PlannerError, match=why):
        draft(*arguments)


@pytest.mark.parametrize("more, why", [
    ({"repeat": "hourly"}, "not a way to repeat"),
    ({"until": "2026-11-01"}, "for an event that repeats"),
    ({"repeat": "weekly", "until": "2026-09-01"}, "before it starts"),
    ({"remind": "soon"}, "number of minutes"),
    ({"remind": 60 * 24 * 40}, "four weeks"),
])
def test_repeats_and_reminders_are_checked(more, why):
    with pytest.raises(PlannerError, match=why):
        draft("Dentist", "2026-10-02T15:00", **more)
    with pytest.raises(PlannerError, match="longer than the gap"):
        draft("Trip", "2026-10-02", "2026-10-04", repeat="daily")


# -- when it happens ----------------------------------------------------------------------------------


def test_an_event_is_found_on_each_day_it_covers():
    trip = draft("Trip", "2026-10-30", "2026-11-02")
    assert days(occurrences(trip, date(2026, 11, 1), date(2026, 11, 30))) == ["2026-10-30"]
    assert occurrences(trip, date(2026, 11, 3), date(2026, 11, 30)) == []
    late = draft("Party", "2026-10-31T22:00", "2026-11-01T00:00")
    # Ending at midnight, it does not reach into the day it ends on.
    assert occurrences(late, date(2026, 11, 1), date(2026, 11, 1)) == []


def test_repeats_are_found_however_long_they_have_run():
    weekly = draft("Bins", "2020-01-06", repeat="weekly")            # a Monday
    assert days(occurrences(weekly, date(2026, 10, 1), date(2026, 10, 31))) == [
        "2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"]
    daily = draft("Pills", "2026-09-28T08:00", repeat="daily", until="2026-10-02")
    assert days(occurrences(daily, date(2026, 10, 1), date(2026, 10, 31))) == [
        "2026-10-01", "2026-10-02"]
    fortnight = draft("Pay", "2026-09-04", repeat="fortnightly")
    assert days(occurrences(fortnight, date(2026, 10, 1), date(2026, 10, 31))) == [
        "2026-10-02", "2026-10-16", "2026-10-30"]


def test_the_31st_falls_on_a_short_months_last_day():
    rent = draft("Rent", "2026-01-31", repeat="monthly")
    assert days(occurrences(rent, date(2026, 2, 1), date(2026, 4, 30))) == [
        "2026-02-28", "2026-03-31", "2026-04-30"]
    leap = draft("Birthday", "2024-02-29", repeat="yearly")
    assert days(occurrences(leap, date(2026, 1, 1), date(2028, 12, 31))) == [
        "2026-02-28", "2027-02-28", "2028-02-29"]


# -- kept ----------------------------------------------------------------------------------------------


def test_the_calendar_is_kept_in_one_file_and_read_back_in_order(store):
    later = store.add(draft("Dentist", "2026-10-02T15:00", remind=30, where="Leeds"))
    first = store.add(draft("Bins", "2026-10-01", repeat="weekly"))
    assert [e.title for e in store.events()] == ["Bins", "Dentist"]
    assert PlannerStore(store.path).get(later.id) == later
    kept = json.loads(store.path.read_text(encoding="utf-8"))
    assert kept["version"] == 1 and kept["events"][0]["start"] == "2026-10-02T15:00"
    found = store.between(date(2026, 10, 1), date(2026, 10, 8))
    # All-day first in its day, then by time.
    assert [(t.event.title, t.first_day.day) for t in found] == [
        ("Bins", 1), ("Dentist", 2), ("Bins", 8)]
    assert store.remove(first.id).title == "Bins"
    with pytest.raises(PlannerError, match="no event with that id"):
        store.get(first.id)


def test_a_change_keeps_when_it_was_made_and_tells_whoever_listens(store):
    told = []
    store.set_on_change(lambda: told.append(1))
    event = store.add(draft("Dentist", "2026-10-02T15:00"))
    moved = store.change(draft("Dentist", "2026-10-03T10:00", ident=event.id))
    assert moved.created == event.created and store.get(event.id).start == datetime(2026, 10, 3, 10)
    store.remove(event.id)
    assert len(told) == 3
    with pytest.raises(PlannerError):
        store.change(draft("Gone", "2026-10-03", ident=event.id))


def test_a_damaged_event_is_left_out_and_a_missing_file_is_an_empty_calendar(store):
    assert store.events() == []
    store.path.write_text(json.dumps({"events": [
        {"id": "a", "title": "Fine", "start": "2026-10-02"},
        {"id": "b", "title": "", "start": "2026-10-02"},
        {"id": "c", "title": "No start"}, "not an event"]}), encoding="utf-8")
    assert [e.title for e in store.events()] == ["Fine"]
    store.path.write_text("{not json", encoding="utf-8")
    assert store.events() == []


# -- reminders -----------------------------------------------------------------------------------------


def test_a_reminder_is_due_from_its_time_until_the_event_is_over_and_once(store):
    event = store.add(draft("Dentist", "2026-10-02T15:00", remind=30))
    assert store.due(datetime(2026, 10, 2, 14, 29)) == []
    (turn,) = store.due(datetime(2026, 10, 2, 14, 30))
    assert turn.event.id == event.id and turn.remind_at == datetime(2026, 10, 2, 14, 30)
    # Akira opened late, with the appointment still on: it is given late.
    assert len(store.due(datetime(2026, 10, 2, 15, 45))) == 1
    # Opened after it was over: not given.
    assert store.due(datetime(2026, 10, 2, 16, 0)) == []
    store.reminded(turn)
    assert store.due(datetime(2026, 10, 2, 14, 45)) == []


def test_each_turn_of_a_repeating_event_is_reminded_of(store):
    store.add(draft("Pills", "2026-10-01T08:00", repeat="daily", remind=0))
    (first,) = store.due(datetime(2026, 10, 1, 8, 5))
    store.reminded(first)
    assert store.due(datetime(2026, 10, 1, 8, 30)) == []
    (second,) = store.due(datetime(2026, 10, 2, 8, 5))
    assert second.start == datetime(2026, 10, 2, 8, 0)


def test_an_all_day_event_is_reminded_of_from_nine_and_a_move_makes_it_due_again(store):
    event = store.add(draft("Mum's birthday", "2026-10-02", remind=1440))
    assert store.due(datetime(2026, 10, 1, 8, 59)) == []
    (turn,) = store.due(datetime(2026, 10, 1, 9, 0))
    store.reminded(turn)
    store.change(draft("Mum's birthday", "2026-10-02", remind=60, ident=event.id))
    assert len(store.due(datetime(2026, 10, 2, 8, 0))) == 1


def test_times_and_repeats_are_said_for_people():
    assert planner.when(datetime(2026, 10, 2, 15), datetime(2026, 10, 2, 16)) == \
        "Fri 2 Oct 2026, 15:00 to 16:00"
    assert planner.when(date(2026, 10, 5), date(2026, 10, 9), year=False) == \
        "Mon 5 Oct to Fri 9 Oct, all day"
    assert planner.when(date(2026, 10, 5), date(2026, 10, 5)) == "Mon 5 Oct 2026, all day"
    assert planner.repeats(draft("Bins", "2026-10-05", repeat="weekly", until="2026-12-28")) == \
        "every week until 28 Dec 2026"
    assert [planner.reminder(m) for m in (None, 0, 30, 60, 120, 1440, 10080)] == [
        "", "at the start", "30 minutes before", "1 hour before", "2 hours before",
        "1 day before", "1 week before"]
