"""The `Projects` bridge: creating and opening projects, and grants that belong
to the open one, recorded in the activity log with the project's name.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtCore")

from akira.core.permissions import AuditLog, Policy  # noqa: E402
from akira.core.projects import ProjectStore  # noqa: E402
from akira.ui.bridge.projects import ProjectsBridge  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def bridge(tmp_path):
    return ProjectsBridge(ProjectStore(tmp_path / "projects"), AuditLog(tmp_path / "audit.jsonl"))


def test_creating_a_project_opens_it(bridge, tmp_path):
    assert bridge.currentName == ""
    assert bridge.create("Garden", "") == ""
    [row] = bridge.projects
    assert row["name"] == "Garden" and row["current"] and bridge.currentName == "Garden"
    assert bridge.create("garden", "").startswith("There is already")
    assert "not a folder" in bridge.create("Novel", str(tmp_path / "missing"))


def test_grants_here_belong_to_the_open_project(bridge, tmp_path):
    folder = tmp_path / "Garden"
    folder.mkdir()
    assert bridge.grant("files.read", [str(folder)]).startswith("Open a project first")

    bridge.create("Garden", str(folder))
    assert bridge.grant("files.read", []) != "", "a scoped grant with no scope was accepted"
    assert bridge.grant("files.read", [str(folder)]) == ""
    assert bridge.grants == [{"id": "files.read", "scopes": [str(folder)], "expires": 0}]
    assert bridge.effective(Policy()).allows("files.read", str(folder / "plan.md"))
    assert "in the project Garden" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")

    assert bridge.openProject("") == ""
    assert bridge.grants == []
    assert not bridge.effective(Policy()).allows("files.read", str(folder / "plan.md"))


def test_revoking_and_removing(bridge, tmp_path):
    folder = tmp_path / "Garden"
    folder.mkdir()
    bridge.create("Garden", "")
    bridge.grant("files.read", [str(folder)])
    assert bridge.revoke("files.read") == "" and bridge.grants == []

    bridge.grant("files.read", [str(folder)])
    project_id = bridge.currentId
    assert bridge.remove(project_id) == ""
    assert bridge.projects == [] and bridge.currentId == ""
    assert "was removed" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert bridge.remove(project_id) == "There is no such project."


def test_renaming_and_personality(bridge):
    bridge.create("Garden", "")
    project_id = bridge.currentId
    assert bridge.rename(project_id, "Allotment") == "" and bridge.currentName == "Allotment"
    assert bridge.setPersonality(project_id, "Terse, practical.") == ""
    assert bridge.projects[0]["personality"] == "Terse, practical."
    assert bridge.setPersonality(project_id, "x" * 5000) != ""
