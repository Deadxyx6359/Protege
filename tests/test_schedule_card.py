"""A job that loads a model waits while the graphics card is wanted elsewhere.

While Akira's window is closed and a game has the card, an agent's job waits
for it; a reminder does not. Time is a fake clock, as in `test_schedule`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.schedule import (ActionRegistry, ActionResult, Daily, JobStore, Missed, OnEvent,
                                 Once, Scheduler)

START = datetime(2026, 3, 2, 8, 0)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


class Clock:
    def __init__(self):
        self.now = START.timestamp()

    def __call__(self):
        return self.now

    def set(self, when):
        self.now = when.timestamp()

    def advance(self, **delta):
        self.now += timedelta(**delta).total_seconds()


class Card:
    """Why the card is wanted elsewhere: "" when it is free."""

    def __init__(self):
        self.why = ""

    def __call__(self):
        return self.why


@pytest.fixture
def ran():
    return []


@pytest.fixture
def actions(ran):
    registry = ActionRegistry()
    registry.register("agent", lambda context: ran.append(("agent", context)) or
                      ActionResult(True, "answered"), uses_card=True)
    registry.register("notify", lambda context: ran.append(("notify", context)) or
                      ActionResult(True, "shown"))
    return registry


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def card():
    return Card()


@pytest.fixture
def build(tmp_path, clock, actions, card):
    def make():
        return Scheduler(actions, policy=Policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                         secret_store=SecretStore(tmp_path / "secrets"),
                         store=JobStore(tmp_path / "schedule.json"), clock=clock, card=card)
    return make


def test_only_actions_that_load_a_model_are_marked(actions):
    assert actions.uses_card("agent")
    assert not actions.uses_card("notify")


def test_a_model_job_waits_while_a_game_has_the_card_and_a_reminder_does_not(build, clock,
                                                                              card, ran):
    scheduler = build()
    agent = scheduler.add("Morning brief", "agent", Daily(9, 0))
    scheduler.add("Reminder", "notify", Daily(9, 0))
    card.why = "a game is running full screen"
    clock.set(START.replace(hour=9))

    scheduler.tick()

    assert [name for name, _ in ran] == ["notify"]
    assert scheduler.waiting() == {agent.id: "a game is running full screen"}
    row = next(j for j in scheduler.snapshot() if j["id"] == agent.id)
    assert row["waiting"] == "a game is running full screen"


def test_it_runs_once_the_card_is_free_and_says_how_long_it_waited(build, clock, card, ran):
    scheduler = build()
    scheduler.add("Morning brief", "agent", Daily(9, 0))
    card.why = "a game is running full screen"
    clock.set(START.replace(hour=9))
    scheduler.tick()
    clock.advance(minutes=40)
    scheduler.tick()
    assert ran == []

    card.why = ""
    clock.advance(minutes=5)
    records = scheduler.tick()

    assert [name for name, _ in ran] == ["agent"]
    assert records[0].status == "ok"
    assert "Waited 45 minutes for the graphics card, while a game is running full screen" in \
        records[0].summary
    assert scheduler.waiting() == {}


def test_a_job_still_waiting_when_it_comes_round_again_runs_once(build, clock, card, ran):
    scheduler = build()
    scheduler.add("Hourly", "agent", Daily(9, 0))
    card.why = "another program is using 4.1 GB of the graphics card"
    clock.set(START.replace(hour=9))
    scheduler.tick()
    clock.set(START.replace(hour=9) + timedelta(days=1))  # the next morning, still gaming
    scheduler.tick()
    card.why = ""
    scheduler.tick()

    assert len(ran) == 1


def test_the_reason_shown_follows_what_is_happening(build, clock, card):
    scheduler = build()
    agent = scheduler.add("Brief", "agent", Daily(9, 0))
    card.why = "a game is running full screen"
    clock.set(START.replace(hour=9))
    scheduler.tick()
    card.why = "another program is using 2.0 GB of the graphics card"
    clock.advance(minutes=1)
    scheduler.tick()

    assert scheduler.waiting()[agent.id] == "another program is using 2.0 GB of the graphics card"


def test_closing_while_it_waits_puts_it_back_due_for_next_time(build, clock, card, ran):
    scheduler = build()
    job = scheduler.add("Once", "agent", Once(START.replace(hour=9)), missed=Missed.RUN_LATE)
    card.why = "a game is running full screen"
    clock.set(START.replace(hour=9))
    scheduler.tick()
    assert scheduler.get(job.id).done   # claimed: its one time has been taken

    scheduler.interrupt()

    # Saved as due again, so the next start resolves it as a missed run.
    restarted = build()
    again = restarted.get(job.id)
    assert not again.done and again.next_run == START.replace(hour=9).timestamp()
    card.why = ""
    clock.advance(hours=3)
    records = restarted.tick()
    assert records and records[0].late and len(ran) == 1


def test_an_event_job_waiting_when_akira_closes_is_recorded_as_not_run(build, card, ran):
    scheduler = build()
    job = scheduler.add("On change", "agent", OnEvent("file.changed", {}))
    card.why = "a game is running full screen"
    scheduler.publish("file.changed", {})
    scheduler.tick()

    scheduler.interrupt()

    history = scheduler.history(job.id)
    assert ran == [] and history[0]["status"] == "skipped"
    assert "Akira closed before it was free" in history[0]["summary"]


def test_with_nothing_said_about_the_card_jobs_run_as_always(tmp_path, clock, actions, ran):
    scheduler = Scheduler(actions, policy=Policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                          secret_store=SecretStore(tmp_path / "secrets"),
                          store=JobStore(tmp_path / "schedule.json"), clock=clock)
    scheduler.add("Brief", "agent", Daily(9, 0))
    clock.set(START.replace(hour=9))
    scheduler.tick()
    assert len(ran) == 1
