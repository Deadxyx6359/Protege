"""The permission screen, the trace view, and the confirmation across threads.

The confirmation tests are the reason this file exists. `ToolContext.confirm`
is synchronous and runs on a worker thread; the dialog answering it runs on the
main one. Every way that arrangement fails — a deadlock, a wait nobody ends, an
answer for a request that is already gone — fails *quietly* in production, so
it is pinned down here instead.
"""

from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("PySide6.QtCore")

from akira.core.agents import Kind, Trace  # noqa: E402
from akira.core.permissions import CATALOGUE, AuditLog, Policy  # noqa: E402
from akira.ui.bridge.permissions import (  # noqa: E402
    ConfirmBridge,
    PermissionsBridge,
)
from akira.ui.bridge.trace import TraceBridge  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


# -- the confirmation -------------------------------------------------------


@pytest.fixture
def app():
    """A bare Qt application, so queued signals have somewhere to arrive."""
    from PySide6.QtCore import QCoreApplication

    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, predicate, timeout=5.0) -> bool:
    """Run the event loop by hand until  predicate holds.

    The real application pumps continuously; here it is done explicitly so the
    test can interleave with a worker thread deterministically.
    """
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return predicate()


def ask_in_background(bridge, summary="write_file /a.txt"):
    """Call `ask` off the UI thread, as the tool registry does."""
    box: dict = {}
    thread = threading.Thread(
        target=lambda: box.update(answer=bridge.ask(summary)), daemon=True)
    thread.start()
    return thread, box


def ask_on_a_worker(bridge, summary="write_file /a.txt"):
    """For the cases where no answer is coming and none needs pumping."""
    thread, box = ask_in_background(bridge, summary)
    thread.join(timeout=10)
    return box.get("answer")


def test_approving_from_the_interface_lets_the_action_through(app):
    bridge = ConfirmBridge()
    tokens: list[str] = []
    bridge.requested.connect(lambda token, summary: tokens.append(token))

    thread, box = ask_in_background(bridge)
    assert pump_until(app, lambda: bool(tokens)), "the request never arrived"
    bridge.answer(tokens[0], True)
    thread.join(timeout=5)

    assert box.get("answer") is True


def test_declining_refuses_it(app):
    bridge = ConfirmBridge()
    tokens: list[str] = []
    bridge.requested.connect(lambda token, summary: tokens.append(token))

    thread, box = ask_in_background(bridge)
    assert pump_until(app, lambda: bool(tokens))
    bridge.answer(tokens[0], False)
    thread.join(timeout=5)

    assert box.get("answer") is False


def test_the_request_carries_the_summary_it_was_given(app):
    """"Run a tool?" is not a question anybody can answer."""
    bridge = ConfirmBridge()
    seen: list[str] = []
    bridge.requested.connect(lambda token, summary: seen.append(summary))

    thread, _ = ask_in_background(bridge, "write_file to C:/notes/plan.md")
    assert pump_until(app, lambda: bool(seen))
    bridge.close()
    thread.join(timeout=5)

    assert "plan.md" in seen[0]


def test_a_second_answer_is_ignored(app):
    """A double-click must not approve the next request as well."""
    bridge = ConfirmBridge()
    tokens: list[str] = []
    bridge.requested.connect(lambda token, summary: tokens.append(token))

    thread, box = ask_in_background(bridge, "x")
    assert pump_until(app, lambda: bool(tokens))

    bridge.answer(tokens[0], True)
    bridge.answer(tokens[0], False)      # the stale one
    thread.join(timeout=5)

    assert box.get("answer") is True
    assert bridge.pendingCount == 0


def test_nobody_answering_expires_to_no(monkeypatch):
    """A dismissed dialog must not park an agent forever holding a model."""
    monkeypatch.setattr(
        "akira.ui.bridge.permissions.CONFIRM_TIMEOUT_S", 0.15)
    bridge = ConfirmBridge()
    started = time.monotonic()
    assert ask_on_a_worker(bridge) is False
    assert time.monotonic() - started < 5, "it waited far longer than the timeout"


def test_asking_from_the_ui_thread_refuses_instead_of_deadlocking():
    """Waiting here would block the loop that has to draw the dialog.

    The application would freeze until the timeout expired. A denied write is
    the only answer that leaves a usable window.
    """
    bridge = ConfirmBridge()
    started = time.monotonic()
    assert bridge.ask("write_file /a.txt") is False
    assert time.monotonic() - started < 1.0, "it blocked rather than refusing"


def test_an_answer_for_an_unknown_request_does_nothing():
    bridge = ConfirmBridge()
    bridge.answer("not-a-real-token", True)   # must not raise


def test_closing_wakes_every_waiter_with_a_refusal():
    """Shutting down while an agent is mid-run must not hang the process."""
    bridge = ConfirmBridge()
    box = {}
    worker = threading.Thread(target=lambda: box.update(a=bridge.ask("x")))
    worker.start()

    deadline = time.monotonic() + 5
    while bridge.pendingCount == 0 and time.monotonic() < deadline:
        time.sleep(0.005)
    bridge.close()
    worker.join(timeout=5)

    assert not worker.is_alive(), "the worker was left blocked"
    assert box.get("a") is False


def test_asking_after_close_is_refused_without_waiting():
    bridge = ConfirmBridge()
    bridge.close()
    started = time.monotonic()
    assert ask_on_a_worker(bridge) is False
    assert time.monotonic() - started < 1.0


def test_the_bridge_satisfies_the_tool_context_contract(tmp_path):
    """It has to be usable as `confirm` without adaptation."""
    from akira.core.permissions import SecretStore
    from akira.core.tools import ToolContext, default_registry

    bridge = ConfirmBridge()
    bridge.close()   # so the refusal is immediate

    policy = Policy()
    policy.grant("files.write", (str(tmp_path),))
    context = ToolContext(policy=policy, audit=AuditLog(tmp_path / "a.jsonl"),
                          secrets=SecretStore(tmp_path / "s"),
                          confirm=bridge.ask)

    result = default_registry().invoke(
        "write_file", {"path": str(tmp_path / "n.txt"), "content": "x"}, context)
    assert not result.ok
    assert not (tmp_path / "n.txt").exists()


# -- the permission screen --------------------------------------------------


def test_the_catalogue_reaches_qml_whole():
    bridge = PermissionsBridge(Policy(), AuditLog())
    rows = bridge.catalogue
    assert len(rows) == len(CATALOGUE)
    assert {"id", "title", "summary", "leavesMachine", "scopeKind"} <= set(rows[0])


def test_leaving_the_machine_is_carried_separately_from_risk():
    """It is the property most people care about and does not follow from risk."""
    bridge = PermissionsBridge(Policy(), AuditLog())
    rows = {row["id"]: row for row in bridge.catalogue}
    assert rows["web.search"]["leavesMachine"] is True
    assert rows["files.read"]["leavesMachine"] is False


def test_granting_and_revoking_from_the_interface(tmp_path):
    bridge = PermissionsBridge(Policy(), AuditLog())
    assert bridge.grant("files.read", [str(tmp_path)]) == ""
    assert [g["id"] for g in bridge.grants] == ["files.read"]

    bridge.revoke("files.read")
    assert bridge.grants == []


def test_a_scoped_capability_without_a_scope_is_refused_with_a_reason():
    """Granting it everywhere instead would be the exact mistake scopes prevent."""
    bridge = PermissionsBridge(Policy(), AuditLog())
    reason = bridge.grant("files.read", [])
    assert reason, "it must say why, not fail silently"
    assert bridge.grants == []


def test_an_invented_capability_is_refused():
    bridge = PermissionsBridge(Policy(), AuditLog())
    assert bridge.grant("root.everything", ["/"]) != ""
    assert bridge.grants == []


def test_revoking_everything_leaves_nothing(tmp_path):
    bridge = PermissionsBridge(Policy(), AuditLog())
    bridge.grant("files.read", [str(tmp_path)])
    bridge.grant("web.search", [])
    bridge.revokeAll()
    assert bridge.grants == []


def test_the_activity_view_shows_refusals_too(tmp_path):
    """The pattern of what an agent tried is the part worth looking at."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.tool_call("agent", "read_file", {"path": "/a"}, allowed=True)
    log.tool_call("agent", "write_file", {"path": "/etc/passwd"},
                  allowed=False, error="not permitted")

    rows = PermissionsBridge(Policy(), log).recentActivity(50)
    assert [row["allowed"] for row in rows] == [False, True]   # newest first


def test_an_unreadable_log_yields_an_empty_view_not_a_crash(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    bridge = PermissionsBridge(Policy(), AuditLog(blocker / "audit.jsonl"))
    assert bridge.recentActivity(10) == []


# -- the trace view ---------------------------------------------------------


def test_events_reach_the_model():
    trace = Trace()
    bridge = TraceBridge(trace)
    trace.emit(Kind.STARTED, "gatherer", text="find it")
    assert bridge.events.count == 1


def test_a_view_attaching_late_sees_what_already_happened():
    trace = Trace()
    trace.emit(Kind.STARTED, "gatherer", text="before the window opened")
    bridge = TraceBridge(trace)
    assert bridge.events.count == 1


def test_active_agents_track_who_is_working():
    trace = Trace()
    bridge = TraceBridge(trace)
    trace.emit(Kind.STARTED, "gatherer")
    assert bridge.activeAgents == ["gatherer"]
    trace.emit(Kind.ANSWER, "gatherer", text="found it")
    assert bridge.activeAgents == []


def test_a_failed_agent_stops_being_active():
    trace = Trace()
    bridge = TraceBridge(trace)
    trace.emit(Kind.STARTED, "gatherer")
    trace.emit(Kind.FAILED, "gatherer", text="fell over")
    assert bridge.activeAgents == []


def test_the_handoff_edge_survives_the_crossing():
    """MESSAGE + recipient is what the interface draws between two agents."""
    from PySide6.QtCore import Qt

    trace = Trace()
    bridge = TraceBridge(trace)
    trace.emit(Kind.MESSAGE, "gatherer", to="analyst", text="here is what I found")

    model = bridge.events
    index = model.index(model.count - 1, 0)
    assert model.data(index, model.AgentRole) == "gatherer"
    assert model.data(index, model.ToRole) == "analyst"
    assert model.data(index, model.KindRole) == "message"


def test_the_model_is_capped_so_a_long_run_does_not_grow_forever(monkeypatch):
    monkeypatch.setattr("akira.ui.bridge.trace.MAX_ROWS", 10)
    trace = Trace()
    bridge = TraceBridge(trace)
    for number in range(40):
        trace.emit(Kind.NOTE, "a", text=str(number))
    assert bridge.events.count == 10

    model = bridge.events
    newest = model.data(model.index(model.count - 1, 0), model.TextRole)
    assert newest == "39", "the newest events are the ones kept"


def test_detaching_stops_the_feed():
    trace = Trace()
    bridge = TraceBridge(trace)
    bridge.detach()
    trace.emit(Kind.NOTE, "a", text="after detach")
    assert bridge.events.count == 0


def test_attaching_to_another_trace_replaces_the_view():
    first, second = Trace(), Trace()
    first.emit(Kind.NOTE, "a", text="old")
    bridge = TraceBridge(first)
    second.emit(Kind.NOTE, "b", text="new")

    bridge.attach(second)
    assert bridge.events.count == 1
    model = bridge.events
    assert model.data(model.index(0, 0), model.TextRole) == "new"


def test_events_from_a_worker_thread_do_not_touch_the_model_directly():
    """Mutating a QAbstractListModel off-thread corrupts it, usually later.

    The event has to arrive through the private signal, so on a bare Trace with
    no running event loop the model stays empty until one is pumped.
    """
    trace = Trace()
    bridge = TraceBridge(trace)
    before = bridge.events.count

    done = threading.Event()

    def worker():
        trace.emit(Kind.NOTE, "worker", text="from off-thread")
        done.set()

    thread = threading.Thread(target=worker)
    thread.start()
    done.wait(timeout=5)
    thread.join(timeout=5)

    # Queued across the boundary: it is waiting in this object's event queue,
    # not already written into the model.
    assert bridge.events.count == before

    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    app.processEvents()
    assert bridge.events.count == before + 1


def test_permission_changes_made_in_the_interface_are_recorded(tmp_path):
    """The review reports changes, so a grant nobody remembers making is noticed."""
    log = AuditLog(tmp_path / "audit.jsonl")
    bridge = PermissionsBridge(Policy(), log)
    bridge.grant("files.read", [str(tmp_path)])
    bridge.revoke("files.read")
    bridge.revoke("files.read")          # nothing held any more: nothing to record
    assert [(e.kind, e.action) for e in log.read()] == [
        ("grant", "files.read"), ("revoke", "files.read")]
