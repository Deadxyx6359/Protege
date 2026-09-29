"""A grant kept with no end date on purpose, which the security review stops asking about."""

from __future__ import annotations

import time

import pytest

from akira.core.permissions import AuditLog, Policy
from akira.core.projects import LayeredPolicy
from akira.core.review import Finding, review


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


def mail_policy():
    policy = Policy()
    policy.grant("mail.read", ("me@example.com",))
    return policy


def codes(result, capability="mail.read"):
    return [f.code for f in result.findings if f.capability == capability]


def test_the_review_stops_asking_about_a_grant_kept_on_purpose(tmp_path):
    policy = mail_policy()
    audit = AuditLog(tmp_path / "audit.jsonl")
    assert "no-expiry" in codes(review(policy=policy, audit=audit))
    policy.keep("mail.read")
    assert "no-expiry" not in codes(review(policy=policy, audit=audit))


def test_kept_survives_saving_and_changing_its_accounts(tmp_path):
    policy = mail_policy()
    policy.keep("mail.read")
    policy.save()
    loaded = Policy.load()
    assert loaded.granted("mail.read").kept
    policy.keep("mail.read", False)
    assert not policy.granted("mail.read").kept


def test_only_a_grant_with_no_end_date_can_be_kept():
    policy = Policy()
    policy.grant("mail.read", ("me@example.com",), expires=time.time() + 3600)
    with pytest.raises(ValueError):
        policy.keep("mail.read")
    with pytest.raises(ValueError):
        Policy().keep("mail.read")


def test_both_layers_must_keep_it_for_the_view_of_both_to():
    base, project = mail_policy(), mail_policy()
    base.keep("mail.read")
    assert not LayeredPolicy(base, project).granted("mail.read").kept
    project.keep("mail.read")
    assert LayeredPolicy(base, project).granted("mail.read").kept


def test_a_finding_says_which_project_it_is_about(tmp_path):
    result = review(policy=Policy(), audit=AuditLog(tmp_path / "audit.jsonl"),
                    projects={"Garden": mail_policy()})
    (found,) = [f for f in result.findings if f.code == "no-expiry"]
    assert found.project == "Garden"
    assert Finding.from_json(found.to_json()).project == "Garden"


def test_the_bridge_keeps_and_a_new_scope_does_not_undo_it(tmp_path):
    pytest.importorskip("PySide6")
    from akira.ui.bridge.permissions import PermissionsBridge
    bridge = PermissionsBridge(mail_policy(), AuditLog(tmp_path / "audit.jsonl"))
    assert bridge.keep("mail.read", True) == ""
    assert bridge.describe("mail.read")["kept"] is True
    assert bridge.grant("mail.read", ["me@example.com", "work@example.com"]) == ""
    assert bridge.describe("mail.read")["kept"] is True
    assert bridge.keep("files.read", True) != ""
