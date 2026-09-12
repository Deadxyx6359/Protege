"""Skill authoring, approval, and execution."""

from __future__ import annotations

import json

import pytest

from akira.lock.pipeline import OutputGate
from akira.lock.tripwires import TripwireSet
from akira.models import ModelManager, ModelSpec, Role
from akira.models.scripted import ScriptedBackend
from akira.projects import ensure_project
from akira.schemas import Manifest, Settings
from akira.security.paths import PathPolicy
from akira.skills.author import (
    SkillAuthor,
    SkillAuthoringError,
    check_syntax,
    scan_imports,
    strip_fences,
)
from akira.skills.sandbox import (
    SkillError,
    approval_for,
    approve,
    digest_of,
    revoke,
    run_skill,
)
from akira.store import bootstrap_vault, tripwire_dir

GOOD_SKILL = '"""Adds numbers."""\n\nprint(2 + 2)\n'


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    bootstrap_vault(root)
    ensure_project(root, "default")
    return root


def put_tripwires(vault, topic, keywords=()):
    (tripwire_dir(vault) / f"{topic}.json").write_text(
        json.dumps({"topic": topic, "keywords": list(keywords)}), encoding="utf-8"
    )


def make(vault, *, unlocked=("python_basics",), tier=2, main_reply=GOOD_SKILL, auditor_reply="VERDICT: PASS"):
    manifest = Manifest.initial()
    for topic in unlocked:
        manifest = manifest.with_unlocked(topic)
    manifest = manifest.with_trust_tier(tier)
    settings = Settings.from_json(
        {"models": {"main_path": "m.gguf", "auditor_path": "a.gguf", "loading": "concurrent"}}
    )
    main = ScriptedBackend(ModelSpec(path="m.gguf", role=Role.MAIN), patterns=[(r".*", main_reply)])
    auditor = ScriptedBackend(ModelSpec(path="a.gguf", role=Role.AUDITOR), patterns=[(r".*", auditor_reply)])
    manager = ModelManager(settings, factory=lambda s: main if s.role is Role.MAIN else auditor)
    gate = OutputGate(manifest, settings, TripwireSet.load(vault), manager)
    policy = PathPolicy.build(vault, trust_tier=tier)
    author = SkillAuthor(vault, "default", manifest, settings, manager, gate)
    return author, manifest, policy


# --- helpers ---------------------------------------------------------------


def test_strip_fences_removes_markdown():
    assert strip_fences("```python\nprint(1)\n```") == "print(1)"
    assert strip_fences("print(1)") == "print(1)"


def test_check_syntax_catches_errors():
    assert check_syntax("print(1)") == ""
    assert "line" in check_syntax("def broken(:\n  pass")


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import socket", ("socket",)),
        ("from urllib.request import urlopen", ("urllib",)),
        ("import os, sys", ()),
        ("import subprocess\nimport ctypes", ("ctypes", "subprocess")),
        ("print('socket')", ()),
    ],
)
def test_scan_imports(source, expected):
    assert scan_imports(source) == expected


# --- authoring -------------------------------------------------------------


def test_authors_a_skill_for_an_unlocked_topic(vault):
    author, _, _ = make(vault)
    skill = author.author("python_basics", "add two numbers")
    assert skill.usable
    assert "print(2 + 2)" in skill.source


def test_locked_topic_authoring_is_refused(vault):
    # A skill is durable, executable knowledge; authoring one for a locked topic
    # writes down what the model should not know, in a form that later runs.
    author, _, _ = make(vault, unlocked=[])
    with pytest.raises(SkillAuthoringError, match="locked"):
        author.author("python_basics", "add two numbers")


def test_tier_zero_authoring_is_refused(vault):
    author, _, _ = make(vault, tier=0)
    with pytest.raises(SkillAuthoringError, match="not available"):
        author.author("python_basics", "add numbers")


def test_generated_source_with_forbidden_import_is_blocked(vault):
    author, _, _ = make(vault, main_reply="import socket\nprint(1)\n")
    skill = author.author("python_basics", "fetch a page")
    assert skill.blocked
    assert "socket" in skill.block_reason


def test_generated_source_that_does_not_parse_is_blocked(vault):
    author, _, _ = make(vault, main_reply="def broken(:\n    pass\n")
    skill = author.author("python_basics", "do a thing")
    assert skill.blocked
    assert "does not parse" in skill.block_reason


def test_skill_source_goes_through_the_gate(vault):
    # A leak in a comment is still a leak.
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    author, _, _ = make(
        vault, main_reply='"""Reference."""\n# sodium reacts violently with water\nprint(1)\n'
    )
    skill = author.author("python_basics", "print something")
    assert skill.blocked
    assert "tripwires" in skill.block_reason


def test_blocked_skill_cannot_be_saved(vault):
    author, _, policy = make(vault, main_reply="import socket\n")
    skill = author.author("python_basics", "x")
    with pytest.raises(SkillAuthoringError, match="cannot be saved"):
        author.save(skill, policy)


def test_saved_skill_carries_a_not_approved_header(vault):
    author, _, policy = make(vault)
    skill = author.author("python_basics", "add two numbers")
    path = author.save(skill, policy)
    text = path.read_text(encoding="utf-8")
    assert "NOT approved for execution" in text
    assert "print(2 + 2)" in text


def test_saving_does_not_grant_execution(vault):
    author, manifest, policy = make(vault)
    skill = author.author("python_basics", "add two numbers")
    path = author.save(skill, policy)
    # Written to disk, never auto-executed.
    run = run_skill(manifest, policy, path)
    assert not run.ok
    assert "not been approved" in run.error


# --- approval --------------------------------------------------------------


def test_approval_then_execution_works(vault):
    author, manifest, policy = make(vault)
    path = author.save(author.author("python_basics", "add two numbers"), policy)
    manifest = approve(manifest, policy, path, topic="python_basics")
    run = run_skill(manifest, policy, path)
    assert run.ok, run.stderr
    assert "4" in run.stdout


def test_editing_a_skill_voids_its_approval(vault):
    # "Approve once" must not become "approve whatever this file says later".
    author, manifest, policy = make(vault)
    path = author.save(author.author("python_basics", "add two numbers"), policy)
    manifest = approve(manifest, policy, path, topic="python_basics")
    assert run_skill(manifest, policy, path).ok

    path.write_text('print("something else entirely")\n', encoding="utf-8")
    run = run_skill(manifest, policy, path)
    assert not run.ok
    assert "changed since it was approved" in run.error


def test_relocking_the_topic_withdraws_execution(vault):
    author, manifest, policy = make(vault)
    path = author.save(author.author("python_basics", "add two numbers"), policy)
    manifest = approve(manifest, policy, path, topic="python_basics")
    manifest = manifest.with_relocked("python_basics")
    run = run_skill(manifest, policy, path)
    assert not run.ok
    assert "now locked" in run.error


def test_revoke_removes_approval(vault):
    author, manifest, policy = make(vault)
    path = author.save(author.author("python_basics", "add two numbers"), policy)
    manifest = approve(manifest, policy, path, topic="python_basics")
    manifest = revoke(manifest, policy, path)
    assert not run_skill(manifest, policy, path).ok


def test_approval_records_the_digest(vault):
    author, manifest, policy = make(vault)
    path = author.save(author.author("python_basics", "add two numbers"), policy)
    manifest = approve(manifest, policy, path, topic="python_basics")
    record = approval_for(manifest, policy, path)
    assert record.sha256 == digest_of(path)


def test_approval_for_an_unapproved_skill_raises(vault):
    author, manifest, policy = make(vault)
    path = author.save(author.author("python_basics", "add two numbers"), policy)
    with pytest.raises(SkillError, match="not been approved"):
        approval_for(manifest, policy, path)


# --- execution -------------------------------------------------------------


def test_tier_below_two_cannot_execute(vault):
    author, manifest, policy = make(vault, tier=2)
    path = author.save(author.author("python_basics", "add two numbers"), policy)
    manifest = approve(manifest, policy, path, topic="python_basics")

    tier1_manifest = manifest.with_trust_tier(1)
    tier1_policy = PathPolicy.build(vault, trust_tier=1)
    run = run_skill(tier1_manifest, tier1_policy, path)
    assert not run.ok
    assert "trust tier" in run.error.lower() or "Tier" in run.error


def test_timeout_terminates_a_runaway_skill(vault):
    author, manifest, policy = make(vault, main_reply="import time\nwhile True:\n    time.sleep(0.1)\n")
    path = author.save(author.author("python_basics", "loop forever"), policy)
    manifest = approve(manifest, policy, path, topic="python_basics")
    run = run_skill(manifest, policy, path, timeout_s=2.0)
    assert not run.ok
    assert run.timed_out


def test_output_is_capped(vault):
    author, manifest, policy = make(
        vault, main_reply="for i in range(200000):\n    print('spam spam spam')\n"
    )
    path = author.save(author.author("python_basics", "print a lot"), policy)
    manifest = approve(manifest, policy, path, topic="python_basics")
    run = run_skill(manifest, policy, path, timeout_s=30.0, max_output=2000)
    assert run.truncated
    assert len(run.stdout) < 4000


def test_failing_skill_reports_its_error(vault):
    author, manifest, policy = make(vault, main_reply="raise ValueError('deliberate')\n")
    path = author.save(author.author("python_basics", "fail"), policy)
    manifest = approve(manifest, policy, path, topic="python_basics")
    run = run_skill(manifest, policy, path)
    assert not run.ok
    assert "deliberate" in run.stderr


def test_network_access_from_inside_a_skill_is_blocked(vault):
    # The guard is installed in the child before the skill's code is compiled,
    # so it cannot capture an unpatched socket reference.
    source = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('example.com', 80), timeout=2)\n"
        "    print('CONNECTED')\n"
        "except Exception as exc:\n"
        "    print('BLOCKED', type(exc).__name__)\n"
    )
    author, manifest, policy = make(vault)
    path = vault / "projects" / "default" / "skills" / "net.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    manifest = approve(manifest, policy, path, topic="python_basics")
    run = run_skill(manifest, policy, path)
    assert "CONNECTED" not in run.stdout
    assert "BLOCKED" in run.stdout


def test_skill_outside_the_vault_is_refused(vault, tmp_path):
    outside = tmp_path / "evil.py"
    outside.write_text("print('hi')\n", encoding="utf-8")
    manifest = Manifest.initial().with_trust_tier(2)
    policy = PathPolicy.build(vault, trust_tier=2)
    run = run_skill(manifest, policy, outside)
    assert not run.ok


def test_missing_skill_file_is_reported(vault):
    manifest = Manifest.initial().with_trust_tier(2)
    policy = PathPolicy.build(vault, trust_tier=2)
    run = run_skill(manifest, policy, vault / "projects" / "default" / "skills" / "absent.py")
    assert not run.ok
    assert "no such skill" in run.error
