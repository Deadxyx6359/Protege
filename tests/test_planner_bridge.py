"""The calendar as the window sees it, and its reminders as notices."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from akira.core import planner
from akira.core.permissions import Policy
from akira.core.planner import PlannerStore, Reminders, draft

pytest.importorskip("PySide6")

TODAY = date(2026, 9, 30)               # a Wednesday


@pytest.fixture
def bridge(tmp_path):
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    from akira.ui.bridge import PlannerBridge

    policy = Policy()
    made = PlannerBridge(PlannerStore(tmp_path / "calendar.json"), policy=lambda: policy,
                         today=lambda: TODAY)
    made.policy = policy
    return made


def test_a_month_is_six_weeks_of_days_with_what_is_on_each(bridge):
    bridge.store.add(draft("Dentist", "2026-10-02T15:00", where="Leeds"))
    bridge.store.add(draft("Trip", "2026-10-30", "2026-11-02"))
    days = bridge.month(2026, 10)
    assert len(days) == 42 and days[0]["date"] == "2026-09-28" and days[0]["weekday"] == "Mon"
    assert [d["inMonth"] for d in days[:4]] == [False, False, False, True]
    assert days[2]["today"] and days[5]["weekend"]
    (dentist,) = days[4]["events"]
    assert (dentist["title"], dentist["time"], dentist["endTime"], dentist["allDay"]) == (
        "Dentist", "15:00", "16:00", False)
    assert (dentist["startMinute"], dentist["endMinute"]) == (900, 960)
    # A trip over four days is on each of them, and says where it starts and ends.
    trip = [(d["date"], d["events"][0]["first"], d["events"][0]["last"])
            for d in days if d["events"] and d["events"][0]["title"] == "Trip"]
    assert trip == [("2026-10-30", True, False), ("2026-10-31", False, False),
                    ("2026-11-01", False, False), ("2026-11-02", False, True)]
    # With Sunday first, the same month starts a day earlier.
    assert bridge.month(2026, 10, True)[0]["date"] == "2026-09-27"
    assert bridge.month(2026, 13) == []


def test_a_week_and_a_day(bridge):
    bridge.store.add(draft("Late", "2026-10-02T23:00", "2026-10-03T01:00"))
    bridge.store.add(draft("Bins", "2026-09-28", repeat="weekly"))
    week = bridge.week("2026-10-01")
    assert [d["date"] for d in week] == [f"2026-09-{n}" for n in (28, 29, 30)] + [
        f"2026-10-0{n}" for n in (1, 2, 3, 4)]
    assert week[0]["events"][0]["repeats"] and week[0]["events"][0]["repeatWords"] == "every week"
    # Past midnight, it is clipped to each day it is on, and says its time once.
    friday, saturday = week[4]["events"][0], week[5]["events"][0]
    assert (friday["startMinute"], friday["endMinute"], friday["time"]) == (1380, 1440, "23:00")
    assert (saturday["startMinute"], saturday["endMinute"], saturday["time"]) == (0, 60, "")
    assert [e["title"] for e in bridge.day("2026-10-02")] == ["Late"]
    assert bridge.day("not a day") == [] and bridge.week("") == []
    assert [e["date"] for e in bridge.upcoming(7)] == ["2026-10-02", "2026-10-05"]


def test_the_person_adds_changes_moves_and_removes_without_any_grant(bridge):
    told, added = [], []
    bridge.changed.connect(lambda: told.append(1))
    bridge.added.connect(added.append)
    assert bridge.add({"title": "", "start": "2026-10-02"}) == "An event needs a title."
    assert bridge.add({"title": "Dentist", "start": "2026-10-02T15:00", "remind": 30,
                       "where": "Leeds", "repeat": "yearly"}) == ""
    (ident,) = added
    event = bridge.event(ident)
    assert (event["title"], event["remind"], event["remindWords"], event["repeatWords"]) == (
        "Dentist", 30, "30 minutes before", "every year")
    assert event["when"] == "Fri 2 Oct 2026, 15:00 to 16:00" and bridge.count == 1

    assert bridge.change(ident, dict(event, title="Hygienist", remind=-1, repeat="")) == ""
    assert (bridge.event(ident)["title"], bridge.event(ident)["remind"]) == ("Hygienist", -1)
    # Dragged to another day, it keeps its time and its length.
    assert bridge.move(ident, "2026-10-05") == ""
    assert bridge.event(ident)["start"] == "2026-10-05T15:00"
    assert bridge.move(ident, "2026-10-05T09:30") == ""
    assert bridge.event(ident)["end"] == "2026-10-05T10:30"
    assert bridge.change("nothing", {"title": "x", "start": "2026-10-02"}).startswith("There is no")
    assert bridge.remove(ident) == "" and bridge.event(ident) == {} and bridge.count == 0
    assert bridge.remove(ident).startswith("There is no event")
    assert len(told) == 5 and bridge.revision == 5


def test_a_change_made_by_an_agent_reaches_the_window(bridge):
    told = []
    bridge.changed.connect(lambda: told.append(1))
    # As a tool does it: straight to the store, not through the bridge.
    bridge.store.add(draft("Dentist", "2026-10-02T15:00"))
    assert told == [1] and bridge.count == 1


def test_a_typed_line_fills_the_editor(bridge):
    read = bridge.read("Dentist 5 October 2027 3pm")
    assert (read["title"], read["start"], read["end"], read["allDay"]) == (
        "Dentist", "2027-10-05T15:00", "2027-10-05T16:00", False)
    assert bridge.read("Holiday")["start"] == ""


def test_the_editors_choices_and_what_agents_may_do(bridge):
    assert [r["id"] for r in bridge.repeats] == list(planner.REPEATS)
    assert bridge.repeats[0]["label"] == "Does not repeat"
    assert bridge.reminders[0] == {"minutes": -1, "label": "No reminder"}
    assert {"minutes": 1440, "label": "1 day before"} in bridge.reminders
    assert not (bridge.agentsRead or bridge.agentsChange or bridge.noticesAllowed)
    changed = []
    bridge.accessChanged.connect(lambda: changed.append(1))
    bridge.policy.grant("planner.read")
    bridge.policy.grant("notify.send")
    bridge.refresh_access()
    assert bridge.agentsRead and bridge.noticesAllowed and not bridge.agentsChange and changed


# -- reminders as notices --------------------------------------------------------------------------


def test_a_reminder_is_shown_once_and_only_while_notices_are_allowed(tmp_path):
    store = PlannerStore(tmp_path / "calendar.json")
    store.add(draft("Dentist", "2026-10-02T15:00", where="Leeds", remind=30))
    shown, recorded = [], []
    allowed = {"notices": False}
    now = {"at": datetime(2026, 10, 2, 14, 30)}
    reminders = Reminders(store, notify=lambda title, text: shown.append((title, text)),
                          allowed=lambda: allowed["notices"], clock=lambda: now["at"],
                          record=recorded.append)
    # Not allowed: nothing is shown, and it is kept for when they are.
    assert reminders.poll() == 0 and shown == []
    allowed["notices"] = True
    now["at"] = datetime(2026, 10, 2, 14, 40)
    assert reminders.poll() == 1
    assert shown == [("Calendar", "Dentist, in 20 minutes: Fri 2 Oct, 15:00 to 16:00, at Leeds.")]
    assert recorded == ["Dentist"]
    assert reminders.poll() == 0 and len(shown) == 1


def test_the_app_wires_the_calendar_to_the_window_the_chat_and_notices(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    from akira.ui.shell import build_context

    ctx = build_context(persist=False)
    try:
        assert ctx.as_context()["Planner"] is ctx.planner
        ctx.chat.send("Add dentist to my calendar on 5 October 2027 at 3pm")
        ctx.chat.send("yes")
        assert ctx.planner.count == 1
        assert (tmp_path / "cfg" / "calendar.json").is_file()
        # Notices are not allowed in a new setup, so a reminder waits.
        assert ctx.reminders is not None and ctx.reminders.poll() == 0
    finally:
        ctx.close()
    del app
