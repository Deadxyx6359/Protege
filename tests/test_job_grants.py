"""A new scheduled job is given what it needs, from what the person allows now."""

from __future__ import annotations

import pytest

from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.schedule import ActionRegistry, ActionResult, JobStore, Scheduler
from akira.core.schedule.actions import suggested_grants
from akira.core.tools import default_registry


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


def held():
    policy = Policy()
    policy.grant("files.read", ("C:/Users/me/Documents",))
    policy.grant("web.search")
    policy.grant("net.http", ("en.wikipedia.org",))
    policy.grant("mail.send", ("me@example.com",))
    return policy


def test_an_agent_job_gets_what_its_tools_need_and_no_more():
    grants = {g["capability"]: g["scopes"]
              for g in suggested_grants("agent", {"role": "gatherer"}, held(), default_registry())}
    assert grants["files.read"] == ["C:/Users/me/Documents"]
    assert grants["net.http"] == ["en.wikipedia.org"] and grants["web.search"] == []
    # Held, but not needed by the gatherer's tools.
    assert "mail.send" not in grants


def test_nothing_the_person_does_not_hold_is_suggested():
    assert suggested_grants("agent", {"role": "gatherer"}, Policy(), default_registry()) == []
    assert suggested_grants("agent", {"role": "nobody"}, held(), default_registry()) == []


def test_a_team_job_gets_what_its_members_need():
    capabilities = {g["capability"] for g in
                    suggested_grants("team", {"team": "research"}, held(), default_registry())}
    assert {"files.read", "net.http", "web.search"} <= capabilities


def test_a_notice_job_gets_the_grant_it_cannot_run_without():
    assert suggested_grants("notify", {"text": "hi"}, Policy(), default_registry()) == [
        {"capability": "notify.send", "scopes": []}]


def test_a_job_made_without_grants_is_given_them(tmp_path):
    pytest.importorskip("PySide6.QtCore")
    from akira.ui.bridge.schedule import ScheduleBridge
    actions = ActionRegistry()
    actions.register("notify", lambda context: ActionResult(True, "sent"))
    actions.register("agent", lambda context: ActionResult(True, "done"))
    scheduler = Scheduler(actions, policy=held, audit=AuditLog(tmp_path / "audit.jsonl"),
                          secret_store=SecretStore(tmp_path / "secrets"),
                          store=JobStore(tmp_path / "schedule.json"))
    bridge = ScheduleBridge(scheduler)
    trigger = {"kind": "daily", "time": "07:30"}
    assert bridge.addJob({"name": "Look up", "action": "agent", "trigger": trigger,
                          "arguments": {"role": "gatherer", "task": "news"}}) == ""
    assert bridge.addJob({"name": "Tell me", "action": "notify", "trigger": trigger,
                          "arguments": {"text": "hi"}}) == ""
    (job, notice) = sorted(scheduler.jobs(), key=lambda j: j.name)
    assert {g.capability for g in job.grants} == {"files.read", "net.http", "web.search"}
    assert [g.capability for g in notice.grants] == ["notify.send"]
    # Given as an empty list, it is taken as given, and a notice without its grant refused.
    assert "needs" in bridge.addJob({"name": "Empty", "action": "notify", "trigger": trigger,
                                     "arguments": {"text": "hi"}, "grants": []})
    assert bridge.suggestedGrants("agent", {"role": "gatherer"})
