"""Run ownership, restoration, actual tool provenance and revocable previews."""
from contextlib import contextmanager
import json
import threading
import time
from uuid import uuid4

import pytest
from PySide6.QtCore import QCoreApplication

from akira.core.agents import Trace, Kind
from akira.core.permissions import Policy, AuditLog, SecretStore
from akira.core.tools import default_registry, ToolRegistry
from akira.core.tools.schema import Tool, ToolResult, Parameter, Requirement
from akira.core.net import host_of
from akira.ui.bridge.agents import AgentsBridge
from akira.ui.run_archive import RunArchive, clean_record, MAX_RUNS
from akira.ui.run_sources import gathered_sources


class Router:
    def __init__(self, replies, gate=None):
        self.replies = list(replies)
        self.gate = gate

    @contextmanager
    def acquire(self, route):
        yield self

    def generate(self, messages, *, on_token=None, **kwargs):
        if self.gate:
            self.gate.wait(4)
        reply = self.replies.pop(0) if self.replies else "Done."
        on_token(reply)
        return reply


def wait(app, done):
    deadline = time.monotonic() + 6
    while not done() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert done()


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "config"))
    app = QCoreApplication.instance() or QCoreApplication([])
    policy = Policy()
    trace = Trace()
    project = {"id": "ocean", "name": "Ocean research"}
    def build(replies=(), registry=None, gate=None, archive=None):
        return AgentsBridge(Router(replies, gate), registry or default_registry(),
            policy=lambda: policy, audit=AuditLog(tmp_path / "audit.jsonl"),
            secret_store=SecretStore(tmp_path / "secrets"), trace=trace,
            project=lambda: project, archive=archive or RunArchive(tmp_path / "runs.json"))
    return app, policy, trace, project, build


def test_history_survives_a_second_run_and_restart_without_shared_trace_contamination(system):
    app, _, trace, project, build = system
    gate = threading.Event()
    bridge = build(["Material", "Analysis", "Check", "Final evidence."], gate=gate)
    assert bridge.runTeam("research", "Investigate migrations", "") == ""
    ident = bridge.currentRun["id"]
    trace.emit(Kind.STARTED, "nightly-writer", text="Unrelated scheduled work")
    gate.set(); wait(app, lambda: not bridge.busy)
    first = bridge.record(ident)
    assert first["status"] == "complete" and first["answer"] == "Final evidence."
    assert set(first["states"].values()) == {"Done"}
    assert "nightly-writer" not in json.dumps(first)
    assert any(e["to"] == "writer" for e in first["events"])
    assert trace.events(Kind.MESSAGE), "the shared activity view must still receive handoffs"
    project.update(id="software", name="New project")
    bridge.runAgent("reviewer", "Review implementation", "")
    wait(app, lambda: not bridge.busy)
    assert bridge.record(ident)["projectId"] == "ocean"
    restored = build()
    assert len(restored.runs) == 2
    assert restored.record(ident)["answer"] == "Final evidence."
    assert restored.record(ident)["kind"] == "team"


def test_read_file_preview_comes_from_real_tool_result_and_is_not_archived(system, tmp_path):
    app, policy, _, project, build = system
    path = tmp_path / "survey.txt"
    body = '<img src="https://outside.invalid/track"> Actual field observation.'
    path.write_text(body, encoding="utf-8")
    policy.grant("files.read", (str(tmp_path),))
    call = '<tool_call>' + json.dumps({"name": "read_file", "arguments": {"path": str(path)}}) + '</tool_call>'
    bridge = build([call, "Gathered", "Analysis", "Check", "Summary without raw observation."])
    bridge.runTeam("research", "Read the local survey", "")
    wait(app, lambda: not bridge.busy)
    run = bridge.currentRun
    assert len(run["sources"]) == 1
    source = run["sources"][0]
    assert source["kind"] == "File read" and source["title"] == path.name
    assert bridge.previewSource(run["id"], source["id"]) == ""
    assert body in bridge.sourcePreview["body"]
    saved = (tmp_path / "runs.json").read_text(encoding="utf-8")
    assert "Actual field observation" not in saved and '"checks"' not in saved
    assert '"arguments"' not in saved and '"body"' not in saved
    restored = build()
    assert "no longer in memory" in restored.previewSource(run["id"], source["id"])
    policy.revoke("files.read")
    bridge._check_preview()
    assert not bridge.sourcePreview
    assert bridge.previewSource(run["id"], source["id"])


def test_denied_read_is_never_presented_as_a_source(system, tmp_path):
    app, _, _, _, build = system
    call = '<tool_call>' + json.dumps({"name": "read_file", "arguments": {"path": str(tmp_path / "x")}}) + '</tool_call>'
    bridge = build([call, "I cannot read it."])
    bridge.runAgent("gatherer", "Read the survey", "")
    wait(app, lambda: not bridge.busy)
    assert bridge.currentRun["sources"] == []
    assert any(e["kind"] == "tool_result" and not e["ok"] for e in bridge.currentRun["events"])


def test_source_cache_checks_project_and_late_results_after_invalidation(system):
    app, policy, _, project, build = system
    bridge = build()
    bridge.runTeam("research", "Question", "")
    wait(app, lambda: not bridge.busy)
    ident = bridge.currentRun["id"]
    source = {"id": "source", "title": "Title", "body": "text", "checks": [("web.search", None)]}
    policy.grant("web.search")
    epoch = bridge._source_epoch
    bridge._on_source((ident, epoch, source))
    project["id"] = "different"
    assert "original project" in bridge.previewSource(ident, "source")
    project["id"] = "ocean"
    bridge.invalidateSources()
    bridge._on_source((ident, epoch, source))
    assert "no longer in memory" in bridge.previewSource(ident, "source")


def test_search_snippets_are_distinct_from_read_pages_and_redirect_permissions():
    registry = ToolRegistry()
    registry.register(Tool("web_search", "Search", (Parameter("query", "string", "Query"),),
                           (Requirement("web.search"),), lambda a, c: None))
    registry.register(Tool("fetch_page", "Read", (Parameter("url", "string", "URL"),),
                           (Requirement("net.http", scope_from="url", scope_of=host_of),), lambda a, c: None))
    hits = ToolResult.success("Search output", {"hits": [{"title": "Source", "url": "https://example.com", "snippet": "Only a snippet"}]})
    source = gathered_sources("web_search", {"query": "ocean"}, hits, registry)[0]
    assert source["kind"] == "Search result" and source["body"] == "Only a snippet"
    page = ToolResult.success("Actual page body", {"url": "https://redirected.example.org/page", "title": "A paper"})
    source = gathered_sources("fetch_page", {"url": "https://example.com"}, page, registry)[0]
    assert source["kind"] == "Page read" and source["body"] == "Actual page body"
    assert ("net.http", "example.com") in source["checks"]
    assert ("net.http", "redirected.example.org") in source["checks"]


def test_can_delete_saved_run_but_not_active_run(system):
    app, _, _, _, build = system
    gate = threading.Event()
    bridge = build(gate=gate)
    bridge.runTeam("research", "Question", "")
    ident = bridge.currentRun["id"]
    assert "Stop" in bridge.deleteRun(ident)
    gate.set(); wait(app, lambda: not bridge.busy)
    assert bridge.deleteRun(ident) == ""
    wait(app, lambda: not bridge.archiveBusy)
    assert not bridge.record(ident) and not build().record(ident)


def row(**kwargs):
    return clean_record({"id": str(uuid4()), "name": "research", "kind": "team", "task": "Question", "status": "complete", **kwargs})


def test_archive_handles_interruption_caps_and_preserves_unreadable_file(tmp_path):
    path = tmp_path / "runs.json"
    archive = RunArchive(path)
    running = row(started=10, status="running", states={"writer": "Thinking"})
    archive.save(running)
    restored = RunArchive(path)
    assert restored.records()[0]["status"] == "interrupted"
    assert restored.records()[0]["states"]["writer"] == "Interrupted"
    for i in range(MAX_RUNS + 2):
        archive.save(row(started=100 + i))
    assert len(RunArchive(path).records()) == MAX_RUNS
    assert all(r["id"] != running["id"] for r in archive.records())
    path.write_text("broken history", encoding="utf-8")
    broken = RunArchive(path)
    assert broken.error
    with pytest.raises(OSError, match="not been overwritten"):
        broken.save(row())
    assert path.read_text() == "broken history"


def test_save_failure_reports_result_without_claiming_persistence(system):
    app, _, _, _, build = system
    class BrokenArchive(RunArchive):
        def save(self, record):
            raise OSError("disk unavailable")
    bridge = build(["a", "b", "c", "The final answer."], archive=BrokenArchive())
    bridge.runTeam("research", "Question", "")
    wait(app, lambda: not bridge.busy)
    assert bridge.answer == "The final answer."
    assert "could not be saved" in bridge.historyError


def test_expired_grant_removes_visible_source(system):
    app, policy, _, _, build = system
    bridge = build()
    bridge.runTeam("research", "Question", "")
    wait(app, lambda: not bridge.busy)
    ident = bridge.currentRun["id"]
    policy.grant("web.search", expires=time.time() + 10)
    bridge._on_source((ident, bridge._source_epoch, {"id": "s", "body": "secret", "checks": [("web.search", None)]}))
    assert not bridge.previewSource(ident, "s")
    policy.grant("web.search", expires=time.time() - 1)
    bridge._check_preview()
    assert not bridge.sourcePreview


def test_model_assignment_snapshot_is_retained_when_settings_change(system):
    app, _, _, _, build = system
    bridge = build()
    model = {"route": "chat", "label": "Local-7B-Q4_K_M"}
    bridge._model_for = lambda route: dict(model)
    bridge.runTeam("research", "Question", "")
    wait(app, lambda: not bridge.busy)
    ident = bridge.currentRun["id"]
    model["label"] = "Another model"
    assert bridge.record(ident)["models"]["gatherer"]["label"] == "Local-7B-Q4_K_M"
    assert build().record(ident)["models"]["writer"]["route"] == "chat"


@pytest.mark.parametrize('approved', [True, False])
def test_artifacts_come_from_confirmed_successful_writes_and_survive_restart(system, tmp_path, approved):
    app, policy, _, _, build = system
    path = tmp_path / 'report.md'
    content = 'Private output body; not separately archived.'
    call = '<tool_call>' + json.dumps({'name': 'write_file', 'arguments': {'path': str(path), 'content': content}}) + '</tool_call>'
    bridge = build([call, 'Finished the task.'])
    policy.grant('files.write', (str(tmp_path),))
    confirmations = []
    bridge._confirm = lambda summary: confirmations.append(summary) or approved
    bridge.runAgent('implementer', 'Write a report', str(tmp_path))
    wait(app, lambda: not bridge.busy)
    assert len(confirmations) == 1
    run = bridge.currentRun
    assert len(run['artifacts']) == (1 if approved else 0)
    assert path.exists() == approved
    if approved:
        assert run['artifacts'][0]['path'] == str(path.resolve())
        assert build().record(run['id'])['artifacts'] == run['artifacts']
        assert content not in (tmp_path / 'runs.json').read_text(encoding='utf-8')
    assert not policy.granted('files.read'), 'Writing does not grant read access'
