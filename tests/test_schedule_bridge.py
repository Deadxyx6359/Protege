"""Scheduled jobs and the review, as the interface sees them — and the wiring
that finally puts every A5–A7 bridge in front of QML.
"""

from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from protege.core.permissions import AuditLog, Policy, SecretStore  # noqa: E402
from protege.core.review import (  # noqa: E402
    Finding,
    Review,
    ReviewStore,
    ensure_review_job,
    register_review_action,
)
from protege.core.schedule import (  # noqa: E402
    ActionRegistry,
    ActionResult,
    Daily,
    JobStore,
    Scheduler,
)
from protege.ui.bridge.schedule import ScheduleBridge  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return predicate()


@pytest.fixture
def ran_on():
    return []


@pytest.fixture
def parts(tmp_path, ran_on):
    actions = ActionRegistry()

    def note(context):
        ran_on.append(threading.get_ident())
        return ActionResult(True, "noted")

    actions.register("note", note)
    audit = AuditLog(tmp_path / "audit.jsonl")
    scheduler = Scheduler(actions, policy=Policy, audit=audit,
                          secret_store=SecretStore(tmp_path / "secrets"),
                          store=JobStore(tmp_path / "schedule.json"))
    store = ReviewStore(tmp_path / "reviews.json")
    return actions, scheduler, ScheduleBridge(scheduler, store), audit, store


# -- jobs --------------------------------------------------------------------


def test_jobs_appear_in_the_view(parts):
    _, scheduler, bridge, _, _ = parts
    scheduler.add("Morning", "note", Daily(9, 0))
    assert [j["name"] for j in bridge.jobs] == ["Morning"]
    assert bridge.jobs[0]["when"] == "Every day at 09:00"


def test_a_change_on_the_schedulers_thread_arrives_through_the_event_loop(app, parts):
    """Touching bound properties from the scheduler's thread corrupts the view."""
    _, scheduler, bridge, _, _ = parts
    worker = threading.Thread(target=lambda: scheduler.add("Evening", "note", Daily(18, 0)))
    worker.start()
    worker.join(5)

    assert bridge.jobs == [], "the view was changed directly from another thread"
    assert pump_until(app, lambda: bool(bridge.jobs))


def test_running_a_job_by_hand_happens_off_the_ui_thread(app, parts, ran_on):
    """A job reaching a confirmation on the UI thread would deadlock."""
    _, scheduler, bridge, _, _ = parts
    job = scheduler.add("Morning", "note", Daily(9, 0))
    bridge.runNow(job.id)
    assert pump_until(app, lambda: bool(ran_on))
    assert ran_on[0] != threading.get_ident()


def test_pausing_resuming_and_removing(parts):
    _, scheduler, bridge, _, _ = parts
    job = scheduler.add("Morning", "note", Daily(9, 0))
    bridge.pause(job.id)
    assert not bridge.jobs[0]["enabled"]
    bridge.resume(job.id)
    assert bridge.jobs[0]["enabled"]
    bridge.remove(job.id)
    assert bridge.jobs == []


def test_history_is_available_per_job(parts):
    _, scheduler, bridge, _, _ = parts
    job = scheduler.add("Morning", "note", Daily(9, 0))
    scheduler.run_now(job.id)
    assert bridge.history(job.id)[0]["status"] == "ok"


# -- the review ----------------------------------------------------------------


def test_a_critical_finding_is_announced_not_left_in_a_list(app, parts):
    _, _, bridge, _, _ = parts
    announced = []
    bridge.criticalFound.connect(announced.append)
    review = Review(time.time(), 30, [
        Finding("critical", "protege-state", "An agent reached for Protégé's own settings")])

    worker = threading.Thread(target=bridge.on_review, args=(review,))
    worker.start()
    worker.join(5)

    assert pump_until(app, lambda: bool(announced))
    assert announced == [1] and bridge.criticalCount == 1
    assert bridge.findings[0]["code"] == "protege-state"


def test_a_quiet_review_raises_no_alarm(app, parts):
    _, _, bridge, _, _ = parts
    announced = []
    bridge.criticalFound.connect(announced.append)
    bridge.on_review(Review(time.time(), 30, []))
    app.processEvents()
    assert announced == []
    assert bridge.reviewSummary == "Nothing to report"


def test_asking_for_a_review_runs_the_review_job(app, parts):
    actions, scheduler, bridge, audit, store = parts
    register_review_action(actions, policy=Policy, audit=audit, store=store,
                           on_review=bridge.on_review)
    ensure_review_job(scheduler)
    bridge.runReview()
    assert pump_until(app, lambda: bridge.lastReviewAt > 0)


def test_the_latest_review_is_shown_after_a_restart(parts):
    _, scheduler, _, _, store = parts
    store.save(Review(123.0, 30, [Finding("warn", "unused", "Old grant")]))
    reopened = ScheduleBridge(scheduler, store)
    assert reopened.lastReviewAt == 123.0 and reopened.findings[0]["code"] == "unused"


def test_before_any_review_it_says_so(parts):
    _, _, bridge, _, _ = parts
    assert bridge.reviewSummary == "Not reviewed yet" and bridge.findings == []


# -- the application -------------------------------------------------------------


def test_the_application_puts_every_bridge_in_front_of_qml(app):
    """Built but unregistered, a bridge is invisible to QML — which is where
    A5's three bridges sat until this wiring existed."""
    from protege.ui.shell import build_context

    ctx = build_context(persist=False)
    try:
        exposed = ctx.as_context()
        assert {"Chat", "Settings", "Permissions", "Confirm",
                "AgentTrace", "Schedule", "Agents", "Memory", "Projects",
                "Graph"} <= set(exposed)
        assert ctx.service is None, "building the context must not start threads"
        names = set(ctx.scheduler.actions.names())
        assert {"security_review", "agent", "team", "distil_memory"} <= names
    finally:
        ctx.close()


# -- creating jobs from the interface ------------------------------------------------


def _with_agent_actions(actions):
    from protege.core.schedule.actions import register_agent_actions
    from protege.core.tools import default_registry

    register_agent_actions(actions, router=None, registry=default_registry())


def test_a_job_can_be_created_from_the_interface(parts):
    actions, _, bridge, _, _ = parts
    _with_agent_actions(actions)
    reason = bridge.addJob({
        "name": "Morning research", "action": "team",
        "trigger": {"kind": "daily", "time": "07:30"},
        "arguments": {"team": "research", "task": "What changed in my notes?"},
        "missed": "skip",
    })
    assert reason == ""
    assert bridge.jobs[0]["when"] == "Every day at 07:30"
    assert bridge.jobs[0]["missed"] == "skip"


@pytest.mark.parametrize("change, expected", [
    ({"action": "summon"}, "no action named 'summon'"),
    ({"arguments": {"team": "research"}}, "needs a task"),
    ({"arguments": {"team": "marketing", "task": "x"}}, "no team named"),
    ({"trigger": {"kind": "daily", "time": "25:00"}}, "not a time of day"),
    ({"trigger": {"kind": "lunar"}}, "unknown trigger kind"),
    ({"missed": "sometimes"}, "run late or be skipped"),
    ({"grants": [{"capability": "files.read", "scopes": []}]}, "must be limited"),
    ({"action": "security_review"}, "schedules itself"),
    ({"name": "   "}, "needs a name"),
])
def test_a_job_that_could_not_run_is_refused_with_a_reason(parts, change, expected):
    actions, _, bridge, _, _ = parts
    _with_agent_actions(actions)
    spec = {"name": "Nightly", "action": "team",
            "trigger": {"kind": "daily", "time": "02:00"},
            "arguments": {"team": "research", "task": "Summarise the day"}}
    spec.update(change)
    reason = bridge.addJob(spec)
    assert expected in reason
    assert bridge.jobs == []
