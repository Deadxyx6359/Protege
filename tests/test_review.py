"""The routine security review (A7).

Each finding is exercised both ways: the state that should raise it, and the
nearby state that should not. A review that cries wolf gets ignored, and then
it is worse than none, so the quiet cases matter as much as the loud ones.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

import pytest

from akira.core import review as review_module
from akira.core.permissions import CATALOGUE, AuditLog, Policy
from akira.core.permissions.audit import Event as AuditEvent
from akira.core.permissions.capabilities import Risk, ScopeKind, get
from akira.core.review import (
    REVIEW_ACTION,
    Finding,
    Review,
    ReviewStore,
    declare_secret_owner,
    ensure_review_job,
    register_review_action,
    review,
)
from akira.core.schedule import ActionRegistry, JobStore, Scheduler

DAY = 86400


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(review_module, "_SECRET_OWNERS", {})


@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


def run(policy, log, tmp_path, **kwargs):
    kwargs.setdefault("permissions_file", tmp_path / "missing-permissions.json")
    return review(policy=policy, audit=log, **kwargs)


def codes(result):
    return {f.code for f in result.findings}


def tool_event(log, *, at, actor="agent", action="read_file", allowed=True,
               capability="files.read", scope="", path=""):
    detail = {"capability": capability, "arguments": {"path": path or scope}}
    if scope:
        detail["scope"] = scope
    log.record(AuditEvent(at, "tool", actor, action, allowed, detail))


# -- the quiet case ----------------------------------------------------------


def test_a_modest_setup_has_nothing_to_report(log, tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    policy = Policy()
    policy.grant("files.read", (str(folder),))
    result = run(policy, log, tmp_path)
    assert result.findings == []
    assert result.summary() == "Nothing to report"


# -- broad grants ------------------------------------------------------------


def test_write_access_to_a_whole_drive_is_critical(log, tmp_path):
    drive = tmp_path.anchor
    policy = Policy()
    policy.grant("files.write", (drive,))
    result = run(policy, log, tmp_path)
    broad = [f for f in result.findings if f.code == "broad-path"]
    assert broad and broad[0].severity == "critical"
    assert result.worst == "critical"


def test_reading_the_whole_user_folder_is_a_warning(log, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    policy = Policy()
    policy.grant("files.read", (str(home),))
    broad = [f for f in run(policy, log, tmp_path).findings if f.code == "broad-path"]
    assert broad and broad[0].severity == "warn"


def test_a_folder_inside_home_is_not_broad(log, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Documents" / "project").mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    policy = Policy()
    policy.grant("files.write", (str(home / "Documents" / "project"),))
    assert "broad-path" not in codes(run(policy, log, tmp_path))


# -- data leaving the machine ------------------------------------------------


def _leaving_high_risk():
    for capability_id in sorted(CATALOGUE):
        capability = get(capability_id)
        if capability.risk is Risk.HIGH and capability.leaves_machine:
            return capability


def _scope_for(capability, tmp_path):
    return {
        ScopeKind.NONE: (),
        ScopeKind.PATH: (str(tmp_path),),
        ScopeKind.HOST: ("example.com",),
        ScopeKind.ACCOUNT: ("me@example.com",),
        ScopeKind.PROVIDER: ("example",),
    }[capability.scope]


def test_a_high_risk_permission_that_leaves_the_machine_should_expire(log, tmp_path):
    capability = _leaving_high_risk()
    policy = Policy()
    policy.grant(capability.id, _scope_for(capability, tmp_path))
    result = run(policy, log, tmp_path)
    assert "no-expiry" in codes(result)
    assert "leaves-machine" in codes(result)


def test_the_same_permission_with_an_end_date_is_fine(log, tmp_path):
    capability = _leaving_high_risk()
    policy = Policy()
    policy.grant(capability.id, _scope_for(capability, tmp_path),
                 expires=time.time() + 7 * DAY)
    assert "no-expiry" not in codes(run(policy, log, tmp_path))


# -- use ---------------------------------------------------------------------


def test_a_grant_nothing_has_used_all_window_is_noted(log, tmp_path):
    policy = Policy()
    policy.grant("web.search")
    later = time.time() + 40 * DAY
    assert "unused" in codes(run(policy, log, tmp_path, now=later))


def test_a_grant_that_was_used_is_not_called_unused(log, tmp_path):
    policy = Policy()
    policy.grant("web.search")
    later = time.time() + 40 * DAY
    tool_event(log, at=later - DAY, action="web_search", capability="web.search")
    assert "unused" not in codes(run(policy, log, tmp_path, now=later))


def test_a_new_grant_is_not_unused_yet(log, tmp_path):
    policy = Policy()
    policy.grant("web.search")
    assert "unused" not in codes(run(policy, log, tmp_path))


def test_a_grant_used_only_in_one_subfolder_could_be_narrower(log, tmp_path):
    root = tmp_path / "work"
    src = root / "project" / "src"
    src.mkdir(parents=True)
    policy = Policy()
    policy.grant("files.read", (str(root),))
    now = time.time()
    for name in ("a.py", "b.py", "c.py"):
        tool_event(log, at=now - 60, scope=str(src / name))

    narrower = [f for f in run(policy, log, tmp_path).findings if f.code == "narrower"]
    assert narrower and str(src) in narrower[0].suggestion


def test_two_uses_are_not_a_pattern(log, tmp_path):
    root = tmp_path / "work"
    src = root / "src"
    src.mkdir(parents=True)
    policy = Policy()
    policy.grant("files.read", (str(root),))
    for name in ("a.py", "b.py"):
        tool_event(log, at=time.time() - 60, scope=str(src / name))
    assert "narrower" not in codes(run(policy, log, tmp_path))


# -- the grant file ----------------------------------------------------------


def test_signs_of_the_grant_file_being_edited_are_reported(log, tmp_path):
    grants = tmp_path / "permissions.json"
    grants.write_text(json.dumps({"grants": [
        {"capability": "root.everything", "scopes": ["/"]},
        {"capability": "web.search", "scopes": [], "granted": 1.0, "expires": 2.0},
    ]}), encoding="utf-8")
    result = run(Policy(), log, tmp_path, permissions_file=grants)
    assert {"unknown-capability", "expired-entries"} <= codes(result)
    unknown = [f for f in result.findings if f.code == "unknown-capability"][0]
    assert "root.everything" in unknown.detail


def test_an_unreadable_grant_file_is_reported(log, tmp_path):
    grants = tmp_path / "permissions.json"
    grants.write_text("{ not json", encoding="utf-8")
    assert "grants-unreadable" in codes(run(Policy(), log, tmp_path, permissions_file=grants))


# -- what agents reached for ---------------------------------------------------


def test_reaching_for_protege_settings_is_critical_even_when_refused(log, tmp_path):
    protected = tmp_path / "cfg"
    tool_event(log, at=time.time() - 60, allowed=False, action="write_file",
               capability="files.write", path=str(protected / "permissions.json"))
    result = run(Policy(), log, tmp_path, protected=protected)
    found = [f for f in result.findings if f.code == "akira-state"]
    assert found and found[0].severity == "critical"
    assert "refused" in found[0].detail


def test_reading_an_ssh_key_is_critical_if_it_was_allowed(log, tmp_path):
    key = tmp_path / "home" / ".ssh" / "id_ed25519"
    tool_event(log, at=time.time() - 60, allowed=True, path=str(key))
    found = [f for f in run(Policy(), log, tmp_path).findings
             if f.code == "sensitive-path"]
    assert found and found[0].severity == "critical"


def test_an_attempt_on_an_ssh_key_that_was_refused_is_a_warning(log, tmp_path):
    key = tmp_path / "home" / ".ssh" / "id_ed25519"
    tool_event(log, at=time.time() - 60, allowed=False, path=str(key))
    found = [f for f in run(Policy(), log, tmp_path).findings
             if f.code == "sensitive-path"]
    assert found and found[0].severity == "warn"


def test_an_ordinary_file_is_not_sensitive(log, tmp_path):
    tool_event(log, at=time.time() - 60, path=str(tmp_path / "notes" / "ssh-notes.md"))
    assert not {"sensitive-path", "akira-state"} & codes(run(Policy(), log, tmp_path))


def test_a_burst_of_refusals_from_one_agent_is_flagged(log, tmp_path):
    now = time.time()
    for offset in range(6):
        tool_event(log, at=now - 300 + offset * 30, actor="gatherer", allowed=False,
                   path=str(tmp_path / f"f{offset}"))
    found = [f for f in run(Policy(), log, tmp_path).findings if f.code == "refusal-burst"]
    assert found and "gatherer" in found[0].title


def test_refusals_spread_over_hours_are_not_a_burst(log, tmp_path):
    now = time.time()
    for offset in range(6):
        tool_event(log, at=now - offset * 3600, actor="gatherer", allowed=False,
                   path=str(tmp_path / f"f{offset}"))
    assert "refusal-burst" not in codes(run(Policy(), log, tmp_path))


def test_permission_changes_in_the_window_are_listed(log, tmp_path):
    log.permission_change("files.read", granted=True, scopes=(str(tmp_path),))
    found = [f for f in run(Policy(), log, tmp_path).findings
             if f.code == "permission-changes"]
    assert found and "files.read" in found[0].detail


# -- secrets -----------------------------------------------------------------


class Names:
    def __init__(self, *names):
        self._names = list(names)

    def names(self):
        return list(self._names)


def test_a_credential_nothing_owns_is_reported(log, tmp_path):
    result = run(Policy(), log, tmp_path, secret_store=Names("old_api_key"))
    found = [f for f in result.findings if f.code == "orphaned-secret"]
    assert found and "old_api_key" in found[0].detail


def test_a_credential_with_an_owner_is_not(log, tmp_path):
    declare_secret_owner("canvas_", "Canvas connector")
    result = run(Policy(), log, tmp_path, secret_store=Names("canvas_token"))
    assert "orphaned-secret" not in codes(result)


# -- the log itself ------------------------------------------------------------


def test_damage_inside_the_log_is_a_warning(log, tmp_path):
    tool_event(log, at=time.time() - 60, path=str(tmp_path / "a"))
    with log.path.open("a", encoding="utf-8") as stream:
        stream.write("{ scribbled over\n")
    tool_event(log, at=time.time() - 30, path=str(tmp_path / "b"))
    assert "log-damaged" in codes(run(Policy(), log, tmp_path))


def test_only_the_last_line_damaged_is_just_an_interrupted_write(log, tmp_path):
    tool_event(log, at=time.time() - 60, path=str(tmp_path / "a"))
    with log.path.open("a", encoding="utf-8") as stream:
        stream.write('{"at": 1, "kind": "to')
    result = run(Policy(), log, tmp_path)
    assert "log-truncated" in codes(result) and "log-damaged" not in codes(result)


# -- shape of the result ---------------------------------------------------------


def test_the_worst_findings_come_first(log, tmp_path):
    policy = Policy()
    policy.grant("files.write", (tmp_path.anchor,))
    policy.grant("web.search")
    result = run(policy, log, tmp_path)
    ranks = [review_module._RANK[f.severity] for f in result.findings]
    assert ranks == sorted(ranks)


def test_the_review_changes_nothing(log, tmp_path):
    """A review that edited permissions would be one more actor editing them."""
    grants = tmp_path / "permissions.json"
    grants.write_text(json.dumps({"grants": [
        {"capability": "web.search", "scopes": [], "granted": 1.0, "expires": 2.0}]}),
        encoding="utf-8")
    before = grants.read_text(encoding="utf-8")
    policy = Policy()
    policy.grant("files.write", (tmp_path.anchor,))

    run(policy, log, tmp_path, permissions_file=grants)

    assert grants.read_text(encoding="utf-8") == before
    assert [g.capability for g in policy.active()] == ["files.write"]


def test_reviews_are_kept_and_the_oldest_fall_off(tmp_path, monkeypatch):
    monkeypatch.setattr(review_module, "MAX_STORED_REVIEWS", 3)
    store = ReviewStore(tmp_path / "reviews.json")
    for number in range(5):
        store.save(Review(float(number), 30, [Finding("info", "x", f"n{number}")]))
    assert [r.at for r in store.history()] == [2.0, 3.0, 4.0]
    assert store.latest().findings[0].title == "n4"


def test_a_damaged_review_store_reads_as_empty(tmp_path):
    path = tmp_path / "reviews.json"
    path.write_text("nonsense", encoding="utf-8")
    assert ReviewStore(path).history() == []


# -- on the schedule -------------------------------------------------------------


def test_the_daily_review_is_scheduled_once_and_runs(tmp_path, log):
    actions = ActionRegistry()
    seen = []
    store = ReviewStore(tmp_path / "reviews.json")
    register_review_action(actions, policy=Policy, audit=log, store=store,
                           on_review=seen.append)
    scheduler = Scheduler(actions, policy=Policy, audit=log,
                          store=JobStore(tmp_path / "schedule.json"),
                          clock=lambda: datetime(2026, 3, 2, 8, 0).timestamp())

    job = ensure_review_job(scheduler)
    assert ensure_review_job(scheduler).id == job.id, "a second review job was made"

    record = scheduler.run_now(job.id)

    assert record.status == "ok"
    assert seen and store.latest() is not None
    assert [e.action for e in log.read(kind="audit")] == ["review"]
    assert scheduler.get(job.id).action == REVIEW_ACTION
