"""Starting agents and teams from the interface — the `Agents` bridge.

What matters here: the work runs off the UI thread, one run at a time, with
the permissions the person holds when it starts; naming a folder grants
nothing; and a run can be stopped.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from protege.core.agents import Kind, Trace  # noqa: E402
from protege.core.permissions import AuditLog, Policy, SecretStore  # noqa: E402
from protege.core.tools import default_registry  # noqa: E402
from protege.ui.bridge.agents import MAX_TASK_CHARS, AgentsBridge  # noqa: E402


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


class Backend:
    """Scripted replies; optionally held at a gate, or streaming until stopped."""

    def __init__(self, replies=(), *, gate=None, endless=False):
        self.replies = list(replies)
        self.gate = gate
        self.endless = endless
        self.threads: list[int] = []
        self.prompts: list[list] = []

    def generate(self, messages, *, on_token=None, **_):
        self.threads.append(threading.get_ident())
        self.prompts.append(list(messages))
        if self.gate is not None:
            self.gate.wait(5)
        if self.endless:
            for _ in range(5000):
                on_token("more ")
                time.sleep(0.002)
            return "never finished"
        reply = self.replies.pop(0) if self.replies else "done"
        on_token(reply)
        return reply


class Router:
    def __init__(self, backend):
        self.backend = backend

    @contextmanager
    def acquire(self, route):
        yield self.backend


@pytest.fixture
def make(tmp_path):
    def build(backend, *, policy=None):
        live = policy if policy is not None else Policy()
        trace = Trace()
        bridge = AgentsBridge(Router(backend), default_registry(),
                              policy=lambda: live,
                              audit=AuditLog(tmp_path / "audit.jsonl"),
                              secret_store=SecretStore(tmp_path / "secrets"),
                              trace=trace)
        return bridge, trace, live
    return build


def system_prompt(backend) -> str:
    return backend.prompts[0][0].content


# -- what the interface is offered -------------------------------------------------


def test_the_teams_and_roles_are_listed(make):
    bridge, _, _ = make(Backend())
    teams = {t["name"]: t for t in bridge.teams}
    assert teams["research"]["members"] == ["gatherer", "analyst", "critic", "writer"]
    assert teams["software"]["members"] == ["architect", "implementer", "reviewer"]
    roles = {r["name"]: r for r in bridge.roles}
    assert roles["critic"]["tools"] == []
    assert roles["reviewer"]["summary"].endswith(".")


# -- running -------------------------------------------------------------------------


def test_a_team_runs_off_the_ui_thread_and_reports_back(app, make):
    backend = Backend(["found it", "it means this", "one objection", "The answer."])
    bridge, _, _ = make(backend)
    results = []
    bridge.finished.connect(lambda ok, answer: results.append((ok, answer)))

    assert bridge.runTeam("research", "What is going on?", "") == ""
    assert bridge.busy and bridge.running == "The research team"
    assert pump_until(app, lambda: not bridge.busy)

    assert results == [(True, "The answer.")]
    assert bridge.answer == "The answer." and bridge.ok and bridge.stopped == "answered"
    assert threading.get_ident() not in backend.threads


def test_the_run_shows_in_the_shared_trace(app, make):
    bridge, trace, _ = make(Backend(["a", "b", "c", "d"]))
    bridge.runTeam("research", "Look into it", "")
    assert pump_until(app, lambda: not bridge.busy)
    assert trace.events(Kind.MESSAGE), "no hand-offs reached the trace"


def test_a_second_run_while_one_is_going_is_refused_with_the_reason(app, make):
    gate = threading.Event()
    bridge, _, _ = make(Backend(["x"] * 8, gate=gate))
    assert bridge.runTeam("research", "first", "") == ""

    reason = bridge.runAgent("gatherer", "second", "")
    assert "research team" in reason and "still working" in reason

    gate.set()
    assert pump_until(app, lambda: not bridge.busy)


def test_a_run_can_be_stopped(app, make):
    bridge, _, _ = make(Backend(endless=True))
    assert bridge.runAgent("gatherer", "Look around", "") == ""
    time.sleep(0.05)
    bridge.stop()
    assert pump_until(app, lambda: not bridge.busy, timeout=10)
    assert bridge.stopped == "cancelled" and not bridge.ok


# -- permissions ------------------------------------------------------------------------


def test_naming_a_folder_grants_nothing(app, make, tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    backend = Backend(["nothing to see"])
    bridge, _, _ = make(backend)

    assert bridge.runAgent("gatherer", "Look in my notes", str(folder)) == ""
    assert pump_until(app, lambda: not bridge.busy)

    prompt = system_prompt(backend)
    assert str(folder.resolve()) in prompt, "the agent was not told where to work"
    assert "no tools" in prompt.lower(), "a folder name alone handed out tools"


def test_permissions_are_the_ones_held_when_the_run_starts(app, make, tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    backend = Backend(["ok"])
    bridge, _, live = make(backend)
    live.grant("files.read", (str(folder),))       # after the bridge was built

    bridge.runAgent("gatherer", "Look in my notes", str(folder))
    assert pump_until(app, lambda: not bridge.busy)
    assert "read_file" in system_prompt(backend)


# -- refusals ------------------------------------------------------------------------------


@pytest.mark.parametrize("call, arguments, expected", [
    ("runTeam", ("marketing", "x", ""), "no team called"),
    ("runAgent", ("wizard", "x", ""), "no role called"),
    ("runTeam", ("research", "   ", ""), "something to do"),
    ("runTeam", ("research", "x" * (MAX_TASK_CHARS + 1), ""), "characters"),
    ("runAgent", ("gatherer", "x", "Z:/no/such/folder/here"), "not a folder"),
])
def test_a_run_that_cannot_start_says_why(make, call, arguments, expected):
    bridge, _, _ = make(Backend())
    reason = getattr(bridge, call)(*arguments)
    assert expected in reason
    assert not bridge.busy
