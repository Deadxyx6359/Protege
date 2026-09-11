"""The `Graph` bridge: the map is drawn off the UI thread, only where notes may
be read, and the request is in the activity log.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from protege.core.permissions import AuditLog, Policy  # noqa: E402
from protege.ui.bridge.graph import GraphBridge  # noqa: E402


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return predicate()


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "Vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "Tomatoes.md").write_text("#garden/tomatoes, see [[Basil]].\n", encoding="utf-8")
    (root / "Basil.md").write_text("#garden/basil\n", encoding="utf-8")
    return root


def test_the_map_needs_permission_to_read_the_notes(app, vault, tmp_path):
    live = Policy()
    bridge = GraphBridge(policy=lambda: live, audit=AuditLog(tmp_path / "audit.jsonl"))
    assert bridge.build("", 800, 600) == "Choose a folder of notes."
    assert "not a folder" in bridge.build(str(tmp_path / "missing"), 800, 600)
    assert bridge.build(str(vault), 800, 600).startswith("Not permitted")
    assert not bridge.busy and bridge.tags == {}


def test_the_map_is_drawn_off_the_ui_thread(app, vault, tmp_path):
    live = Policy()
    live.grant("vault.read", (str(vault),))
    bridge = GraphBridge(policy=lambda: live, audit=AuditLog(tmp_path / "audit.jsonl"))
    built = []
    bridge.builtChanged.connect(lambda: built.append(1))

    assert bridge.build(str(vault), 800, 600) == ""
    assert pump_until(app, lambda: not bridge.busy), "the map never came back"
    assert built and bridge.error == ""
    assert bridge.tags["summary"] == "2 tags in 1 group."
    assert all(0 < node["x"] < 800 for node in bridge.tags["nodes"])
    assert [(e["a"], e["b"]) for e in bridge.links["edges"]] == [("Tomatoes.md", "Basil.md")]
    assert "draw_map" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
