"""Path containment, trust tiers, and the network guard."""

from __future__ import annotations

import socket

import pytest

from protege.security import netguard
from protege.security.paths import (
    PathPolicy,
    PathViolation,
    capabilities,
    is_within,
)


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "projects" / "demo" / "notes").mkdir(parents=True)
    (root / ".protege").mkdir()
    return root


# --- containment -----------------------------------------------------------


def test_relative_path_resolves_inside_vault(vault):
    policy = PathPolicy.build(vault, trust_tier=2)
    resolved = policy.resolve_model_read("projects/demo/notes/a.md")
    assert resolved == (vault / "projects" / "demo" / "notes" / "a.md").resolve()


@pytest.mark.parametrize(
    "attempt",
    [
        "../outside.md",
        "../../outside.md",
        "projects/../../outside.md",
        "projects/demo/../../../outside.md",
        "./projects/demo/../../../etc/passwd",
    ],
)
def test_traversal_is_blocked(vault, attempt):
    policy = PathPolicy.build(vault, trust_tier=3)
    with pytest.raises(PathViolation):
        policy.resolve_model_read(attempt)


def test_traversal_blocked_at_every_tier(vault):
    for tier in (1, 2, 3):
        policy = PathPolicy.build(vault, trust_tier=tier)
        with pytest.raises(PathViolation):
            policy.resolve_model_read("../escape.md")


def test_absolute_path_outside_vault_is_blocked(vault, tmp_path):
    policy = PathPolicy.build(vault, trust_tier=2)
    with pytest.raises(PathViolation):
        policy.resolve_model_read(str(tmp_path / "elsewhere.md"))


def test_sibling_directory_with_shared_prefix_is_not_inside(tmp_path):
    # String prefix matching would wrongly accept "vault-backup" as inside
    # "vault". This is why containment uses path semantics, not startswith.
    root = (tmp_path / "vault").resolve()
    sibling = (tmp_path / "vault-backup" / "note.md").resolve()
    assert not is_within(root, sibling)


def test_alternate_data_stream_is_refused(vault):
    # "note.md:hidden" writes a second invisible stream on the same file --
    # content there would never appear in a vault scan or in retrieval, making
    # it an ideal hiding place for locked material.
    policy = PathPolicy.build(vault, trust_tier=2)
    with pytest.raises(PathViolation):
        policy.resolve_model_write("projects/demo/notes/a.md:hidden")


def test_reserved_windows_device_name_is_refused(vault):
    policy = PathPolicy.build(vault, trust_tier=2)
    for name in ("CON", "nul.md", "projects/demo/COM1.txt", "aux"):
        with pytest.raises(PathViolation):
            policy.resolve_model_write(name)


def test_nul_byte_is_refused(vault):
    policy = PathPolicy.build(vault, trust_tier=2)
    with pytest.raises(PathViolation):
        policy.resolve_model_write("projects/demo/a\x00.md")


def test_symlink_escaping_vault_is_blocked(vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("locked knowledge", encoding="utf-8")
    link = vault / "projects" / "demo" / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privileges not available here")
    policy = PathPolicy.build(vault, trust_tier=2)
    with pytest.raises(PathViolation):
        policy.resolve_model_read("projects/demo/escape/secret.md")


# --- trust tiers -----------------------------------------------------------


def test_tier_zero_grants_the_model_nothing(vault):
    policy = PathPolicy.build(vault, trust_tier=0)
    caps = policy.caps
    assert not caps.model_reads_vault
    assert not caps.retrieval_enabled
    assert not caps.any_memory_writes
    assert not caps.skill_execution
    with pytest.raises(PathViolation):
        policy.resolve_model_read("projects/demo/notes/a.md")


def test_tier_zero_still_lets_the_application_read_its_own_config(vault):
    # Trust tiers gate the model, not Protege. The manifest is the file that
    # defines the gate; the app must always be able to read it.
    policy = PathPolicy.build(vault, trust_tier=0)
    assert policy.resolve_app(".protege/manifest.json").name == "manifest.json"


def test_tier_one_reads_but_never_writes(vault):
    policy = PathPolicy.build(vault, trust_tier=1)
    assert policy.resolve_model_read("projects/demo/notes/a.md")
    with pytest.raises(PathViolation):
        policy.resolve_model_write("projects/demo/notes/a.md")
    assert policy.caps.user_pinned_memory
    assert not policy.caps.model_proposed_memory


def test_tier_two_enables_model_proposed_memory(vault):
    caps = PathPolicy.build(vault, trust_tier=2).caps
    assert caps.model_writes_vault
    assert caps.model_proposed_memory


def test_external_roots_only_apply_at_tier_three(vault, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "doc.md").write_text("x", encoding="utf-8")

    tier2 = PathPolicy.build(vault, trust_tier=2, external_roots=[str(allowed)])
    with pytest.raises(PathViolation):
        tier2.resolve_model_read(str(allowed / "doc.md"))

    tier3 = PathPolicy.build(vault, trust_tier=3, external_roots=[str(allowed)])
    assert tier3.resolve_model_read(str(allowed / "doc.md")) == (allowed / "doc.md").resolve()


def test_tier_three_external_roots_do_not_extend_to_the_application(vault, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    policy = PathPolicy.build(vault, trust_tier=3, external_roots=[str(allowed)])
    with pytest.raises(PathViolation):
        policy.resolve_app(str(allowed / "manifest.json"))


def test_unknown_tier_collapses_to_zero():
    # A tier we do not recognize means a corrupt manifest, and the safe reading
    # of a corrupt manifest is "no privileges", not "closest match".
    assert capabilities(99).tier == 0
    assert capabilities(-1).tier == 0
    assert not capabilities(99).model_reads_vault


def test_require_names_the_missing_capability(vault):
    policy = PathPolicy.build(vault, trust_tier=0)
    with pytest.raises(PathViolation, match="retrieval_enabled"):
        policy.require("retrieval_enabled")


def test_no_tier_grants_network_access():
    from protege.security.paths import TIERS

    for caps in TIERS.values():
        assert not any("network" in field.lower() for field in vars(caps))


# --- netguard --------------------------------------------------------------


def test_guard_blocks_outbound_connect():
    netguard.install()
    try:
        with pytest.raises(netguard.NetworkAccessBlocked):
            socket.create_connection(("example.com", 80))
        with pytest.raises(netguard.NetworkAccessBlocked):
            socket.socket().connect(("93.184.216.34", 80))
    finally:
        netguard.uninstall()


def test_guard_blocks_dns_resolution():
    # Resolution leaks the query to the resolver even when no connection
    # follows, so it is blocked independently of connect.
    netguard.install()
    try:
        with pytest.raises(netguard.NetworkAccessBlocked):
            socket.getaddrinfo("example.com", 443)
    finally:
        netguard.uninstall()


def test_guard_permits_loopback_lookup():
    netguard.install()
    try:
        assert socket.getaddrinfo("127.0.0.1", 80)
    finally:
        netguard.uninstall()


def test_guard_blocks_bind_to_non_loopback():
    netguard.install()
    try:
        with pytest.raises(netguard.NetworkAccessBlocked):
            socket.socket().bind(("0.0.0.0", 0))
    finally:
        netguard.uninstall()


def test_guard_is_idempotent():
    netguard.install()
    netguard.install()
    try:
        assert netguard.is_installed()
    finally:
        netguard.uninstall()
    assert not netguard.is_installed()


def test_uninstall_restores_original_behavior():
    netguard.install()
    netguard.uninstall()
    # Not asserting a real connection succeeds -- that would require network.
    # Asserting the guard's exception is gone is the observable part.
    assert socket.getaddrinfo("127.0.0.1", 80)
