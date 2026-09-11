"""The scheduler: when jobs run, what they may touch, and what happens when
things go wrong.

Time is never real here. A `FakeClock` drives every tick, so "the machine was
asleep for a night" is one line, and nothing depends on when the suite runs.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta

import pytest

from protege.core.permissions import AuditLog, Policy, SecretStore
from protege.core.schedule import (
    ActionRegistry,
    ActionResult,
    Cron,
    CronError,
    CronExpr,
    Daily,
    Every,
    JobGrant,
    JobPolicy,
    JobStore,
    Missed,
    Monthly,
    OnEvent,
    Once,
    Scheduler,
    SchedulerService,
    TriggerError,
    Weekly,
    narrow_policy,
    trigger_from_json,
)
from protege.core.schedule import scheduler as scheduler_module

#: A Monday morning, local time.
START = datetime(2026, 3, 2, 8, 0)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


class FakeClock:
    def __init__(self, when: datetime = START) -> None:
        self.now = when.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta).total_seconds()

    def set(self, when: datetime) -> None:
        self.now = when.timestamp()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def calls():
    return []


@pytest.fixture
def actions(calls):
    registry = ActionRegistry()

    def note(context):
        calls.append(context)
        return ActionResult(True, "noted")

    registry.register("note", note)
    return registry


@pytest.fixture
def build(tmp_path, clock, actions):
    """A scheduler over a store in tmp_path. Call again to simulate a restart."""
    def make(*, policy=None, registry=None, confirm=None):
        live = policy if policy is not None else Policy()
        return Scheduler(
            registry or actions,
            policy=lambda: live,
            audit=AuditLog(tmp_path / "audit.jsonl"),
            secret_store=SecretStore(tmp_path / "secrets"),
            store=JobStore(tmp_path / "schedule.json"),
            confirm=confirm,
            clock=clock,
        )
    return make


# -- cron --------------------------------------------------------------------


def test_a_cron_expression_finds_the_next_matching_minute():
    expr = CronExpr.parse("*/15 9-17 * * 1-5")
    assert expr.next_after(START) == datetime(2026, 3, 2, 9, 0)
    assert expr.next_after(datetime(2026, 3, 2, 9, 7)) == datetime(2026, 3, 2, 9, 15)


def test_the_next_match_is_strictly_after_the_given_time():
    expr = CronExpr.parse("0 9 * * *")
    assert expr.next_after(datetime(2026, 3, 2, 9, 0)) == datetime(2026, 3, 3, 9, 0)


def test_cron_skips_to_a_weekday_across_a_weekend():
    friday_evening = datetime(2026, 3, 6, 18, 0)
    assert CronExpr.parse("0 9 * * mon-fri").next_after(friday_evening) == \
        datetime(2026, 3, 9, 9, 0)


def test_day_of_month_or_day_of_week_when_both_are_restricted():
    """`0 9 1 * 1` is the 1st *and* every Monday — the rule everybody forgets."""
    expr = CronExpr.parse("0 9 1 * 1")
    tuesday = datetime(2026, 3, 3, 12, 0)
    assert expr.next_after(tuesday) == datetime(2026, 3, 9, 9, 0)      # a Monday
    march_31 = datetime(2026, 3, 31, 12, 0)
    assert expr.next_after(march_31) == datetime(2026, 4, 1, 9, 0)


def test_a_starred_step_in_the_day_field_still_means_and():
    """Vixie cron treats a field starting with * as unrestricted."""
    expr = CronExpr.parse("0 9 */2 * 1")
    assert not expr.matches_day(datetime(2026, 3, 3).date())   # 3rd, a Tuesday
    assert not expr.matches_day(datetime(2026, 3, 2).date())   # the 2nd: a Monday, but even
    assert expr.matches_day(datetime(2026, 3, 9).date())       # 9th, a Monday


def test_seven_is_sunday_too():
    assert CronExpr.parse("0 0 * * 7").weekdays == frozenset({0})


def test_macros_and_names_are_understood():
    assert CronExpr.parse("@daily").next_after(START) == datetime(2026, 3, 3, 0, 0)
    assert CronExpr.parse("0 0 1 jan *").months == frozenset({1})


def test_an_expression_that_can_never_match_returns_nothing_promptly():
    started = time.monotonic()
    assert CronExpr.parse("0 0 30 2 *").next_after(START) is None
    assert time.monotonic() - started < 2


@pytest.mark.parametrize("bad", [
    "* * * *", "60 * * * *", "* 24 * * *", "5-1 * * * *", "*/0 * * * *",
    "1,,2 * * * *", "x * * * *",
])
def test_malformed_cron_is_refused(bad):
    with pytest.raises(CronError):
        CronExpr.parse(bad)


# -- triggers ----------------------------------------------------------------


def test_daily_runs_today_if_the_time_is_still_ahead():
    assert Daily(9, 30).next_after(START) == datetime(2026, 3, 2, 9, 30)
    assert Daily(7, 0).next_after(START) == datetime(2026, 3, 3, 7, 0)


def test_weekly_picks_the_next_listed_day():
    trigger = Weekly(frozenset({2, 4}), 9)            # Wednesday, Friday
    assert trigger.next_after(START) == datetime(2026, 3, 4, 9, 0)


def test_weekly_describes_itself_plainly():
    assert Weekly(frozenset(range(5)), 9).describe() == "Weekdays at 09:00"
    assert Weekly(frozenset({0, 2, 4}), 9, 30).describe() == "Mon, Wed, Fri at 09:30"


def test_monthly_on_the_31st_still_runs_in_february():
    """Nobody asking for "the 31st" wants it skipped five months a year."""
    assert Monthly(31, 8).next_after(datetime(2026, 2, 1)) == datetime(2026, 2, 28, 8, 0)
    assert Monthly(31, 8).next_after(datetime(2028, 2, 1)) == datetime(2028, 2, 29, 8, 0)


def test_every_counts_from_its_anchor_so_it_never_drifts():
    anchor = START.timestamp()
    trigger = Every(3600, anchor)
    late = START + timedelta(hours=2, minutes=40)
    assert trigger.next_after(late) == START + timedelta(hours=3)


def test_a_repeating_job_cannot_be_a_busy_loop():
    with pytest.raises(TriggerError):
        Every(5)


def test_once_in_the_past_has_no_next():
    assert Once(START - timedelta(days=1)).next_after(START) is None


def test_event_triggers_match_names_prefixes_and_payload():
    exact = OnEvent("file.changed", {"folder": "notes"})
    assert exact.matches("file.changed", {"folder": "notes", "name": "a.md"})
    assert not exact.matches("file.changed", {"folder": "other"})
    assert not exact.matches("file.created", {"folder": "notes"})
    assert OnEvent("file.*").matches("file.created", {})


def test_an_event_trigger_needs_a_cooldown():
    """Without one, a burst of a thousand events is a thousand agent runs."""
    with pytest.raises(TriggerError):
        OnEvent("file.changed", cooldown_s=0)


@pytest.mark.parametrize("trigger", [
    Once(datetime(2027, 1, 1, 9, 0)), Every(900, 12345.0), Daily(7, 30),
    Weekly(frozenset({1, 3}), 18, 5), Monthly(15, 6), Cron("*/10 * * * *"),
    OnEvent("mail.received", {"from": "x"}, 120),
])
def test_every_trigger_survives_a_round_trip(trigger):
    assert trigger_from_json(json.loads(json.dumps(trigger.to_json()))) == trigger


@pytest.mark.parametrize("raw", [
    {"kind": "sometimes"}, {"kind": "daily"}, {"kind": "daily", "time": "25:00"},
    {"kind": "cron", "expr": "nonsense"}, "not even an object",
])
def test_an_unreadable_trigger_is_refused_not_guessed(raw):
    with pytest.raises(TriggerError):
        trigger_from_json(raw)


# -- adding jobs ---------------------------------------------------------------


def test_adding_a_job_schedules_its_first_run(build):
    job = build().add("Morning", "note", Daily(9, 0))
    assert job.next_run == datetime(2026, 3, 2, 9, 0).timestamp()


def test_a_job_must_name_an_action_that_exists(build):
    with pytest.raises(KeyError):
        build().add("Mystery", "summon", Daily(9, 0))


def test_a_one_off_in_the_past_is_refused(build):
    with pytest.raises(ValueError):
        build().add("Yesterday", "note", Once(START - timedelta(days=1)))


def test_a_schedule_that_never_comes_round_is_refused(build):
    with pytest.raises(ValueError):
        build().add("Never", "note", Cron("0 0 30 2 *"))


def test_a_job_cannot_ask_for_a_capability_that_does_not_exist(build):
    with pytest.raises(KeyError):
        build().add("Greedy", "note", Daily(9, 0), grants=[("root.everything", ())])


def test_a_scoped_grant_on_a_job_needs_its_scope(build):
    with pytest.raises(ValueError):
        build().add("Vague", "note", Daily(9, 0), grants=[("files.read", ())])


# -- running on time -----------------------------------------------------------


def test_a_due_job_runs_and_its_clock_moves_on(build, clock, calls):
    scheduler = build()
    job = scheduler.add("Morning", "note", Daily(9, 0))
    clock.set(datetime(2026, 3, 2, 9, 0, 20))

    records = scheduler.tick()

    assert [r.status for r in records] == ["ok"]
    assert len(calls) == 1
    assert job.next_run == datetime(2026, 3, 3, 9, 0).timestamp()


def test_nothing_runs_before_it_is_due(build, clock, calls):
    scheduler = build()
    scheduler.add("Morning", "note", Daily(9, 0))
    clock.set(datetime(2026, 3, 2, 8, 59))
    assert scheduler.tick() == []
    assert calls == []


def test_a_one_off_runs_once_and_is_done(build, clock, calls):
    scheduler = build()
    job = scheduler.add("Once", "note", Once(datetime(2026, 3, 2, 9, 0)))
    clock.set(datetime(2026, 3, 2, 9, 1))
    scheduler.tick()
    clock.advance(days=3)
    scheduler.tick()
    assert len(calls) == 1
    assert job.done


# -- surviving a restart ---------------------------------------------------------


def test_jobs_and_their_history_survive_a_restart(build, clock):
    first = build()
    job = first.add("Morning", "note", Daily(9, 0))
    clock.set(datetime(2026, 3, 2, 9, 0, 30))
    first.tick()

    second = build()
    restored = second.get(job.id)
    assert restored is not None and restored.name == "Morning"
    assert [r.status for r in restored.history] == ["ok"]


def test_a_damaged_schedule_is_moved_aside_not_run_and_not_deleted(build, tmp_path):
    (tmp_path / "schedule.json").write_text("{ this is not json", encoding="utf-8")
    scheduler = build()
    assert scheduler.jobs() == []
    assert scheduler.warnings and "damaged" in scheduler.warnings[0]
    assert list(tmp_path.glob("schedule.json.damaged-*")), "the user's file was lost"


def test_a_job_that_cannot_be_read_is_kept_but_never_run(build, tmp_path, calls, clock):
    """Dropping it destroys what the user set up; running it acts on a guess."""
    strange = {"id": "x1", "name": "From the future", "action": "note",
               "trigger": {"kind": "lunar", "phase": "full"}}
    (tmp_path / "schedule.json").write_text(
        json.dumps({"jobs": [strange]}), encoding="utf-8")

    scheduler = build()
    assert scheduler.jobs() == []
    assert any("From the future" in w for w in scheduler.warnings)

    scheduler.add("Morning", "note", Daily(9, 0))       # forces a save
    saved = json.loads((tmp_path / "schedule.json").read_text(encoding="utf-8"))
    assert strange in saved["jobs"], "the unreadable job was dropped on save"

    clock.advance(days=2)
    scheduler.tick()
    assert all(c.job.name != "From the future" for c in calls)


# -- missed runs ---------------------------------------------------------------


def test_a_missed_run_is_run_once_on_return_and_says_so(build, clock, calls):
    scheduler = build()
    scheduler.add("Morning", "note", Daily(9, 0), missed=Missed.RUN_LATE)
    clock.set(datetime(2026, 3, 5, 8, 0))       # Mon, Tue, Wed slept through

    records = scheduler.tick()

    assert len(calls) == 1, "three missed mornings must coalesce into one run"
    assert records[0].late
    assert "3 scheduled runs" in records[0].summary


def test_a_job_set_to_skip_does_not_run_late(build, clock, calls):
    scheduler = build()
    job = scheduler.add("Standup", "note", Daily(9, 0), missed=Missed.SKIP)
    clock.set(datetime(2026, 3, 2, 15, 0))

    records = scheduler.tick()

    assert calls == []
    assert [r.status for r in records] == ["skipped"]
    assert "skipped" in records[0].summary
    assert job.next_run == datetime(2026, 3, 3, 9, 0).timestamp()


def test_an_hourly_job_does_not_fire_twenty_times_after_a_night_off(build, clock, calls):
    scheduler = build()
    scheduler.add("Hourly", "note", Every(3600))
    clock.advance(hours=20, minutes=10)

    records = scheduler.tick()

    assert len(calls) == 1
    assert "20 scheduled runs" in records[0].summary


def test_a_little_lateness_is_just_on_time(build, clock, calls):
    """The service ticks every half minute; two minutes late is not "missed"."""
    scheduler = build()
    scheduler.add("Morning", "note", Daily(9, 0))
    clock.set(datetime(2026, 3, 2, 9, 2))
    records = scheduler.tick()
    assert records[0].status == "ok" and not records[0].late


# -- containment -------------------------------------------------------------


def test_a_job_that_raises_is_recorded_and_the_rest_still_run(build, clock, calls, actions):
    def explode(context):
        raise ZeroDivisionError("boom")

    actions.register("explode", explode)
    scheduler = build()
    scheduler.add("Broken", "explode", Daily(9, 0))
    scheduler.add("Fine", "note", Daily(9, 0))
    clock.set(datetime(2026, 3, 2, 9, 0, 30))

    statuses = {r.status for r in scheduler.tick()}

    assert statuses == {"ok", "failed"}
    assert len(calls) == 1


def test_repeated_failure_pauses_the_job_with_the_reason(build, clock, actions):
    actions.register("flaky", lambda context: ActionResult(False, "the disk is full"))
    scheduler = build()
    job = scheduler.add("Flaky", "flaky", Every(3600))

    for _ in range(scheduler_module.MAX_CONSECUTIVE_FAILURES):
        clock.advance(hours=1)
        scheduler.tick()

    assert not job.enabled
    assert "the disk is full" in job.paused_reason


def test_a_success_resets_the_failure_count(build, clock, actions):
    results = iter([ActionResult(False, "no")] * 3 + [ActionResult(True, "yes")])
    actions.register("wobbly", lambda context: next(results))
    scheduler = build()
    job = scheduler.add("Wobbly", "wobbly", Every(3600))
    for _ in range(4):
        clock.advance(hours=1)
        scheduler.tick()
    assert job.failures == 0 and job.enabled


def test_an_action_that_is_not_loaded_fails_visibly_and_the_job_is_kept(build, clock):
    first = build()
    job = first.add("Morning", "note", Daily(9, 0))

    second = build(registry=ActionRegistry())     # "note" is not registered now
    clock.set(datetime(2026, 3, 2, 9, 0, 30))
    records = second.tick()

    assert records[0].status == "failed"
    assert "may not be loaded" in records[0].summary
    assert second.get(job.id) is not None


def test_a_job_is_not_started_again_on_top_of_itself(build, clock, actions):
    seen = []

    def reentrant(context):
        seen.append(scheduler.run_now(context.job.id))
        return ActionResult(True, "outer")

    actions.register("reentrant", reentrant)
    scheduler = build()
    job = scheduler.add("Reentrant", "reentrant", Daily(9, 0))
    scheduler.run_now(job.id)

    assert seen[0].status == "overlap"


# -- permissions -------------------------------------------------------------


def test_a_job_gets_the_intersection_of_what_it_asked_for_and_what_is_held(tmp_path):
    notes = tmp_path / "notes"
    (notes / "daily").mkdir(parents=True)
    live = Policy()
    live.grant("files.read", (str(notes),))

    narrowed = narrow_policy(live, (JobGrant("files.read", (str(notes / "daily"),)),))

    assert narrowed.allows("files.read", str(notes / "daily" / "a.md"))
    assert not narrowed.allows("files.read", str(notes / "other.md"))


def test_a_scope_the_user_never_granted_is_dropped(tmp_path):
    inside, outside = tmp_path / "in", tmp_path / "out"
    inside.mkdir()
    outside.mkdir()
    live = Policy()
    live.grant("files.read", (str(inside),))

    narrowed = narrow_policy(live, (JobGrant("files.read", (str(outside),)),))
    assert not narrowed.allows("files.read", str(outside / "x.txt"))


def test_scheduling_a_job_grants_nothing(build, clock, calls, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    scheduler = build(policy=Policy())                   # the user holds nothing
    scheduler.add("Reader", "note", Daily(9, 0),
                  grants=[("files.read", (str(folder),))])
    clock.set(datetime(2026, 3, 2, 9, 0, 30))
    scheduler.tick()
    assert not calls[0].tools.policy.allows("files.read", str(folder / "a.txt"))


def test_revoking_in_settings_takes_effect_on_the_next_run(build, clock, calls, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    live = Policy()
    live.grant("files.read", (str(folder),))
    scheduler = build(policy=live)
    scheduler.add("Reader", "note", Every(3600),
                  grants=[("files.read", (str(folder),))])

    clock.advance(hours=1)
    scheduler.tick()
    live.revoke("files.read")
    clock.advance(hours=1)
    scheduler.tick()

    assert calls[0].tools.policy.allows("files.read", str(folder / "a"))
    assert not calls[1].tools.policy.allows("files.read", str(folder / "a"))


def test_a_jobs_narrowed_policy_refuses_to_be_saved():
    """Saving it would overwrite the user's permissions with one job's subset."""
    with pytest.raises(RuntimeError):
        JobPolicy().save()


def test_an_unattended_run_cannot_approve_anything_irreversible(build, clock, actions, tmp_path):
    from protege.core.tools import default_registry

    folder = tmp_path / "work"
    folder.mkdir()
    live = Policy()
    live.grant("files.write", (str(folder),))

    def write(context):
        result = default_registry().invoke(
            "write_file", {"path": str(folder / "out.txt"), "content": "x"},
            context.tools)
        return ActionResult(result.ok, result.content)

    actions.register("write", write)
    scheduler = build(policy=live)
    scheduler.add("Writer", "write", Daily(9, 0),
                  grants=[("files.write", (str(folder),))])
    clock.set(datetime(2026, 3, 2, 9, 0, 30))
    scheduler.tick()

    assert not (folder / "out.txt").exists()


def test_a_real_prompt_can_be_handed_in_once_an_interface_exists(build, clock, actions, tmp_path):
    from protege.core.tools import default_registry

    folder = tmp_path / "work"
    folder.mkdir()
    live = Policy()
    live.grant("files.write", (str(folder),))
    asked = []

    def write(context):
        result = default_registry().invoke(
            "write_file", {"path": str(folder / "out.txt"), "content": "x"},
            context.tools)
        return ActionResult(result.ok, result.content)

    actions.register("write", write)
    scheduler = build(policy=live, confirm=lambda s: asked.append(s) or True)
    scheduler.add("Writer", "write", Daily(9, 0),
                  grants=[("files.write", (str(folder),))])
    clock.set(datetime(2026, 3, 2, 9, 0, 30))
    scheduler.tick()

    assert asked and (folder / "out.txt").exists()


# -- events ------------------------------------------------------------------


def test_a_published_event_runs_a_matching_job_with_its_payload(build, calls):
    scheduler = build()
    scheduler.add("On change", "note", OnEvent("file.changed", {"folder": "notes"}))
    scheduler.publish("file.changed", {"folder": "notes", "name": "a.md"})
    scheduler.publish("file.changed", {"folder": "elsewhere"})

    scheduler.tick()

    assert len(calls) == 1
    assert calls[0].event["name"] == "a.md"
    assert calls[0].event_name == "file.changed"


def test_a_burst_of_events_is_one_run_and_the_rest_are_reported(build, clock, calls):
    scheduler = build()
    scheduler.add("On change", "note", OnEvent("file.changed", cooldown_s=60))
    for _ in range(5):
        scheduler.publish("file.changed", {})
    first = scheduler.tick()
    assert len(calls) == 1
    assert "4 further events" in first[0].summary

    clock.advance(seconds=61)
    scheduler.publish("file.changed", {})
    second = scheduler.tick()

    assert len(calls) == 2, "the cooldown had passed, so this one runs"
    assert "further event" not in second[0].summary


def test_the_event_queue_is_bounded(build, monkeypatch):
    monkeypatch.setattr(scheduler_module, "MAX_QUEUED_EVENTS", 10)
    scheduler = build()
    for _ in range(25):
        scheduler.publish("noise", {})
    assert scheduler.dropped_events == 15


# -- the job table -------------------------------------------------------------


def test_resuming_counts_forward_rather_than_catching_up(build, clock, calls):
    """The runs inside a pause were declined, not missed."""
    scheduler = build()
    job = scheduler.add("Morning", "note", Daily(9, 0))
    scheduler.pause(job.id)
    clock.set(datetime(2026, 3, 6, 12, 0))
    scheduler.tick()
    scheduler.resume(job.id)
    scheduler.tick()

    assert calls == []
    assert job.next_run == datetime(2026, 3, 7, 9, 0).timestamp()


def test_removing_a_job(build):
    scheduler = build()
    job = scheduler.add("Morning", "note", Daily(9, 0))
    assert scheduler.remove(job.id)
    assert scheduler.get(job.id) is None


def test_every_run_is_audited(build, clock, tmp_path):
    scheduler = build()
    scheduler.add("Morning", "note", Daily(9, 0))
    clock.set(datetime(2026, 3, 2, 9, 0, 30))
    scheduler.tick()
    events = AuditLog(tmp_path / "audit.jsonl").read(kind="schedule")
    assert [e.action for e in events] == ["note"]


def test_a_snapshot_is_plain_data_for_the_interface(build):
    scheduler = build()
    scheduler.add("Morning", "note", Daily(9, 0))
    row = scheduler.snapshot()[0]
    assert row["when"] == "Every day at 09:00" and row["enabled"]
    json.dumps(row)     # must cross a thread boundary and a QML one


# -- the service ---------------------------------------------------------------


def test_the_service_runs_an_event_job_promptly_and_stops_cleanly(tmp_path, actions, calls):
    scheduler = Scheduler(actions, policy=Policy,
                          audit=AuditLog(tmp_path / "a.jsonl"),
                          secret_store=SecretStore(tmp_path / "s"),
                          store=JobStore(tmp_path / "schedule.json"))
    scheduler.add("On ping", "note", OnEvent("ping"))
    service = SchedulerService(scheduler, interval_s=30.0)
    service.start()
    try:
        scheduler.publish("ping", {})
        deadline = time.monotonic() + 5
        while not calls and time.monotonic() < deadline:
            time.sleep(0.02)
        assert calls, "publishing did not wake the service"
    finally:
        service.stop()
    assert not service.running


# -- the agent actions -------------------------------------------------------


def test_a_scheduled_agent_runs_under_the_jobs_narrowed_permissions(tmp_path, clock):
    from contextlib import contextmanager

    from protege.core.schedule.actions import register_agent_actions
    from protege.core.tools import default_registry

    class Backend:
        def __init__(self):
            self.prompts = []

        def generate(self, messages, *, on_token=None, **_):
            self.prompts.append(messages)
            on_token("All quiet.")
            return "All quiet."

    class Router:
        def __init__(self):
            self.backend = Backend()

        @contextmanager
        def acquire(self, route):
            yield self.backend

    folder = tmp_path / "notes"
    folder.mkdir()
    live = Policy()
    live.grant("files.read", (str(folder),))
    live.grant("files.write", (str(folder),))

    router = Router()
    registry = ActionRegistry()
    register_agent_actions(registry, router=router, registry=default_registry())
    scheduler = Scheduler(registry, policy=lambda: live,
                          audit=AuditLog(tmp_path / "a.jsonl"),
                          secret_store=SecretStore(tmp_path / "s"),
                          store=JobStore(tmp_path / "schedule.json"), clock=clock)
    scheduler.add("Nightly look", "agent", Daily(9, 0),
                  arguments={"role": "gatherer", "task": "Anything new?"},
                  grants=[("files.read", (str(folder),))])
    clock.set(datetime(2026, 3, 2, 9, 0, 30))

    records = scheduler.tick()

    assert records[0].status == "ok" and "All quiet." in records[0].summary
    system = router.backend.prompts[0][0].content
    assert "read_file" in system
    assert "write_file" not in system, "the job was never granted writing"


def test_a_scheduled_team_that_does_not_exist_fails_plainly(tmp_path, clock):
    from protege.core.schedule.actions import register_agent_actions
    from protege.core.tools import default_registry

    registry = ActionRegistry()
    register_agent_actions(registry, router=None, registry=default_registry())
    scheduler = Scheduler(registry, policy=Policy,
                          audit=AuditLog(tmp_path / "a.jsonl"),
                          secret_store=SecretStore(tmp_path / "s"),
                          store=JobStore(tmp_path / "schedule.json"), clock=clock)
    job = scheduler.add("Odd", "team", Daily(9, 0),
                        arguments={"team": "marketing", "task": "x"})
    record = scheduler.run_now(job.id)
    assert record.status == "failed" and "marketing" in record.summary
