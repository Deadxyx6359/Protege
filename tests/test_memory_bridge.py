"""The `Memory` bridge: choosing the vault, running distillation off the UI
thread, and a person accepting or rejecting what it proposes.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from protege.core.brain.distil import PendingStore, register_distil_action  # noqa: E402
from protege.core.permissions import AuditLog, Policy, SecretStore  # noqa: E402
from protege.core.schedule import ActionRegistry, JobStore, Scheduler  # noqa: E402
from protege.models.scripted import ScriptedBackend  # noqa: E402
from protege.ui.bridge.memory import MemoryBridge  # noqa: E402


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


class Router:
    def __init__(self, *replies):
        self.backend = ScriptedBackend(replies=replies)

    @contextmanager
    def acquire(self, route):
        yield self.backend


@pytest.fixture
def vault_root(tmp_path):
    root = tmp_path / "Vault"
    (root / ".obsidian").mkdir(parents=True)
    return root


@pytest.fixture
def live(vault_root, tmp_path):
    conversations = tmp_path / "cfg" / "conversations"
    conversations.mkdir(parents=True)
    (conversations / "a1b2c3d4.json").write_text(json.dumps({
        "id": "a1b2c3d4", "title": "Allotment",
        "messages": [{"role": "user", "text": "I got plot 14."},
                     {"role": "assistant", "text": "Congratulations."}]}), encoding="utf-8")
    policy = Policy()
    policy.grant("vault.read", (str(vault_root),))
    policy.grant("memory.read")
    return policy


@pytest.fixture
def bridge(live, tmp_path, app):
    actions = ActionRegistry()
    audit = AuditLog(tmp_path / "audit.jsonl")
    scheduler = Scheduler(actions, policy=lambda: live, audit=audit,
                          secret_store=SecretStore(tmp_path / "secrets"),
                          store=JobStore(tmp_path / "schedule.json"))
    pending = PendingStore()
    memory = MemoryBridge(scheduler, policy=lambda: live, audit=audit, pending=pending)
    register_distil_action(actions, router=Router("## Allotment\n- Plot 14.\n"),
                           pending=pending, on_proposed=memory.on_proposed)
    return memory


def distilled(bridge, app, vault_root):
    assert bridge.setVault(str(vault_root)) == ""
    assert bridge.distilNow() == ""
    assert pump_until(app, lambda: not bridge.busy), "the run never came back"


def test_choosing_a_vault_sets_up_the_nightly_job(bridge, vault_root, tmp_path):
    assert bridge.vault == ""
    assert bridge.distilNow() == "Choose a vault first."
    assert bridge.setVault("  ")
    assert "not a folder" in bridge.setVault(str(tmp_path / "missing"))
    assert bridge.setVault(str(vault_root)) == ""
    assert bridge.vault and (vault_root.samefile(bridge.vault))


def test_distilling_runs_off_the_ui_thread_and_lists_proposals(bridge, app, vault_root):
    changes = []
    bridge.pendingChanged.connect(lambda: changes.append(1))
    distilled(bridge, app, vault_root)

    assert bridge.pendingCount == 1 and changes
    [row] = bridge.pending
    assert row["target"] == "Memory/Allotment.md" and not row["addsTo"]
    assert "Plot 14" in row["preview"] and row["sources"] == ["Allotment"]
    assert "1 note proposed" in bridge.lastRun


def test_accepting_needs_permission_to_write_that_note(bridge, app, vault_root, live, tmp_path):
    distilled(bridge, app, vault_root)
    [row] = bridge.pending

    assert bridge.accept(row["id"]).startswith("Not permitted")
    assert not (vault_root / "Memory").exists() and bridge.pendingCount == 1

    live.grant("vault.write", (str(vault_root),))
    assert bridge.accept(row["id"]) == ""
    assert "Plot 14" in (vault_root / "Memory" / "Allotment.md").read_text(encoding="utf-8")
    assert bridge.pendingCount == 0
    assert "accept_memory" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_rejecting_discards_only_the_proposal(bridge, app, vault_root, tmp_path):
    distilled(bridge, app, vault_root)
    [row] = bridge.pending
    assert bridge.reject(row["id"]) == ""
    assert bridge.pendingCount == 0
    assert bridge.reject(row["id"]) == "That proposal is no longer waiting."
    assert (tmp_path / "cfg" / "conversations" / "a1b2c3d4.json").exists()
