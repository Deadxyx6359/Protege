"""The permission model, which is the thing everything else rests on.

These are mostly adversarial. A permission system that works when asked nicely
is not a permission system, so most of what is checked here is what happens
when the path is a traversal, the host is a lookalike, the grant file has been
edited by hand, or the capability being asked for was never declared.
"""

from __future__ import annotations

import json
import time

import pytest

from protege.core.permissions import (
    CATALOGUE,
    AuditLog,
    Grant,
    PermissionError_,
    Policy,
    SecretStore,
    redact,
)
from protege.core.permissions.capabilities import Direction, ScopeKind, get
from protege.core.permissions.secrets import SecretError, available


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never touch the real permission file or the real secret store."""
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


# -- the default ------------------------------------------------------------


def test_nothing_is_allowed_by_default():
    policy = Policy()
    for capability in CATALOGUE:
        assert not policy.allows(capability, "anything")


def test_there_is_no_allow_everything():
    """The absence of this switch is deliberate. See model.py."""
    policy = Policy()
    assert not hasattr(policy, "allow_all")
    assert not hasattr(policy, "grant_all")


def test_money_cannot_be_moved_because_no_capability_exists():
    """Reading balances is offered; moving money is not, so no tool can ask."""
    assert "bank.read" in CATALOGUE
    assert not [c for c in CATALOGUE if c.startswith("bank.") and c != "bank.read"]


def test_read_and_write_are_always_separable():
    """"Read my email" and "send email as me" must be grantable apart."""
    for domain in ("files", "mail", "calendar", "vault", "docs"):
        directions = {get(c).direction for c in CATALOGUE if c.startswith(domain + ".")}
        assert Direction.READ in directions and Direction.WRITE in directions


# -- path scopes ------------------------------------------------------------


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
    return root


def test_a_granted_root_covers_what_is_beneath_it(project):
    policy = Policy()
    policy.grant("files.read", (str(project),))
    assert policy.allows("files.read", str(project / "src" / "main.py"))


def test_a_sibling_with_the_same_prefix_is_outside(project, tmp_path):
    """`/project-backup` must not be inside `/project`."""
    sibling = tmp_path / "project-backup"
    sibling.mkdir()
    policy = Policy()
    policy.grant("files.read", (str(project),))
    assert not policy.allows("files.read", str(sibling / "secrets.txt"))


def test_traversal_out_of_the_root_is_refused(project):
    policy = Policy()
    policy.grant("files.read", (str(project),))
    assert not policy.allows("files.read", str(project / ".." / ".." / "Windows"))


def test_a_symlink_pointing_out_of_the_root_is_refused(project, tmp_path):
    """Containment is checked after resolution, or a link defeats it."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    link = project / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this machine does not allow creating symlinks")

    policy = Policy()
    policy.grant("files.read", (str(project),))
    assert not policy.allows("files.read", str(link / "secret.txt"))


def test_reserved_device_names_are_refused(project):
    policy = Policy()
    policy.grant("files.read", (str(project),))
    assert not policy.allows("files.read", str(project / "CON"))


def test_alternate_data_streams_are_refused(project):
    policy = Policy()
    policy.grant("files.read", (str(project),))
    assert not policy.allows("files.read", str(project / "notes.txt:hidden"))


def test_a_scoped_capability_with_no_scope_given_is_refused(project):
    policy = Policy()
    policy.grant("files.read", (str(project),))
    assert not policy.allows("files.read", None)


def test_a_scoped_capability_cannot_be_granted_without_a_scope():
    with pytest.raises(ValueError):
        Policy().grant("files.read")


# -- host scopes ------------------------------------------------------------


@pytest.mark.parametrize(
    "granted, candidate, expected",
    [
        ("example.com", "example.com", True),
        ("example.com", "api.example.com", True),
        ("example.com", "EXAMPLE.COM", True),
        ("example.com", "example.com:443", True),
        ("example.com", "notexample.com", False),
        ("example.com", "example.com.evil.net", False),
        ("example.com", "evil.net", False),
    ],
)
def test_host_matching(granted, candidate, expected):
    policy = Policy()
    policy.grant("net.http", (granted,))
    assert bool(policy.allows("net.http", candidate)) is expected


# -- expiry -----------------------------------------------------------------


def test_an_expired_grant_stops_allowing():
    policy = Policy()
    policy.grant("web.search", expires=time.time() - 1)
    assert not policy.allows("web.search")
    assert policy.granted("web.search") is None


def test_expired_grants_are_dropped_when_loading():
    policy = Policy()
    policy.grant("web.search", expires=time.time() - 1)
    policy.grant("screen.capture")
    policy.save()
    assert [g.capability for g in Policy.load().active()] == ["screen.capture"]


# -- failing closed ---------------------------------------------------------


def test_a_corrupt_grant_file_yields_no_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path))
    Policy.path().parent.mkdir(parents=True, exist_ok=True)
    Policy.path().write_text("{ this is not json", encoding="utf-8")
    assert Policy.load().active() == []


def test_a_grant_for_an_undeclared_capability_is_dropped(tmp_path, monkeypatch):
    """An invented capability must not become an unrestricted one."""
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path))
    Policy.path().parent.mkdir(parents=True, exist_ok=True)
    Policy.path().write_text(json.dumps({
        "grants": [{"capability": "root.everything", "scopes": ["/"]}]
    }), encoding="utf-8")
    assert Policy.load().active() == []


def test_a_malformed_grant_entry_is_dropped():
    assert Grant.from_json({"capability": "files.read", "scopes": "not-a-list"}) is None
    assert Grant.from_json({"capability": 12}) is None
    assert Grant.from_json("nonsense") is None


def test_asking_about_an_undeclared_capability_is_refused_not_allowed():
    decision = Policy().allows("files.obliterate", "/")
    assert not decision
    assert "no such capability" in decision.reason


def test_a_denied_decision_explains_itself():
    """A refusal with no reason trains people to grant everything."""
    decision = Policy().allows("mail.send", "me@example.com")
    assert "Send email" in decision.reason
    with pytest.raises(PermissionError_):
        decision.raise_if_denied()


def test_revoking_everything_leaves_nothing(project):
    policy = Policy()
    policy.grant("files.read", (str(project),))
    policy.grant("web.search")
    policy.revoke_all()
    assert policy.active() == []


# -- the audit log ----------------------------------------------------------


def test_secrets_never_reach_the_log(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.tool_call("agent", "http.get",
                  {"url": "https://x.test", "api_key": "sk-live-1234",
                   "headers": {"Authorization": "Bearer abcdef"}},
                  allowed=True)
    written = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "sk-live-1234" not in written
    assert "abcdef" not in written
    assert "[redacted]" in written


def test_redaction_reaches_nested_values():
    out = redact({"outer": {"inner": {"password": "hunter2", "safe": "ok"}}})
    assert out["outer"]["inner"]["password"] == "[redacted]"
    assert out["outer"]["inner"]["safe"] == "ok"


def test_long_values_are_trimmed():
    out = redact({"body": "x" * 5000})
    assert len(out["body"]) < 500


def test_refusals_are_logged_as_loudly_as_successes(tmp_path):
    """The pattern of what an agent *tried* is the interesting part."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.tool_call("agent", "write_file", {"path": "/etc/passwd"},
                  allowed=False, error="not permitted")
    events = log.read()
    assert len(events) == 1 and events[0].allowed is False


def test_a_broken_log_directory_does_not_break_the_action(tmp_path):
    """Failing to log must not become a way to break the application."""
    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    log = AuditLog(blocker / "audit.jsonl")
    log.tool_call("agent", "read_file", {"path": "/x"}, allowed=True)
    assert log.read() == []


def test_a_malformed_line_does_not_hide_the_rest(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.tool_call("agent", "a", {}, allowed=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{ truncated\n")
    log.tool_call("agent", "b", {}, allowed=True)
    assert [e.action for e in log.read()] == ["a", "b"]


# -- secrets ----------------------------------------------------------------


@pytest.mark.skipif(not available(), reason="no OS credential store here")
def test_a_secret_round_trips_and_is_never_stored_in_plaintext(tmp_path):
    store = SecretStore(tmp_path / "secrets")
    store.put("canvas_token", "super-secret-value")
    assert store.get("canvas_token") == "super-secret-value"
    blob = (tmp_path / "secrets" / "canvas_token.dpapi").read_bytes()
    assert b"super-secret-value" not in blob


@pytest.mark.skipif(not available(), reason="no OS credential store here")
def test_the_store_lists_names_but_never_values(tmp_path):
    store = SecretStore(tmp_path / "secrets")
    store.put("mail_password", "hunter2")
    assert store.names() == ["mail_password"]


def test_a_name_that_could_escape_the_directory_is_refused(tmp_path):
    store = SecretStore(tmp_path / "secrets")
    for bad in ("../escape", "a/b", "", "x" * 200, "with space"):
        with pytest.raises(SecretError):
            store.put(bad, "value")


def test_asking_for_a_secret_that_does_not_exist_says_so(tmp_path):
    with pytest.raises(SecretError):
        SecretStore(tmp_path / "secrets").get("absent")


# -- the catalogue ----------------------------------------------------------


def test_every_capability_that_leaves_the_machine_says_so():
    for capability in ("web.search", "mail.send", "model.cloud", "bank.read"):
        assert get(capability).leaves_machine


def test_irreversible_capabilities_are_marked():
    for capability in ("files.write", "mail.send", "web.submit", "shell.run"):
        assert get(capability).irreversible


def test_scoped_capabilities_declare_what_their_scope_means():
    assert get("files.read").scope is ScopeKind.PATH
    assert get("net.http").scope is ScopeKind.HOST
    assert get("mail.read").scope is ScopeKind.ACCOUNT
    assert get("screen.capture").scope is ScopeKind.NONE
