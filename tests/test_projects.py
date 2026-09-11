"""Projects (B6): a project's own grants apply only while it is open, the
combined view cannot be edited, removing a project leaves its notes alone, and
the security review sees project grants too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protege.core.permissions import AuditLog, Policy
from protege.core.projects import LayeredPolicy, ProjectError, ProjectStore
from protege.core.review import review
from protege.core.tools import default_registry


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def store(tmp_path):
    return ProjectStore(tmp_path / "projects")


@pytest.fixture
def folders(tmp_path):
    garden, novel = tmp_path / "Garden", tmp_path / "Novel"
    garden.mkdir()
    novel.mkdir()
    (garden / "plan.md").write_text("Beds in March.", encoding="utf-8")
    return garden, novel


# -- the record ----------------------------------------------------------------------------


def test_a_project_name_is_checked(store):
    for bad in ("", "  ", "../escape", "a/b", "é" * 3, "x" * 65, "."):
        with pytest.raises(ProjectError):
            store.create(bad)
    store.create("Garden plan")
    with pytest.raises(ProjectError):
        store.create("garden  PLAN")


def test_a_project_is_stored_by_id_so_a_rename_moves_nothing(store):
    project = store.create("Garden")
    directory = store.root / project.id
    assert directory.is_dir() and "Garden" not in {p.name for p in store.root.iterdir()}
    store.update(project.id, name="Allotment")
    assert store.get(project.id).name == "Allotment" and directory.is_dir()


def test_a_damaged_record_is_skipped(store):
    good = store.create("Garden")
    broken = store.root / ("0" * 16)
    broken.mkdir()
    (broken / "project.json").write_text("{not json", encoding="utf-8")
    assert [p.id for p in store.all()] == [good.id]


def test_removing_a_project_leaves_its_notes(store, folders):
    garden, _ = folders
    project = store.create("Garden", folder=str(garden))
    store.set_current(project.id)
    store.remove(project.id)
    assert store.get(project.id) is None and store.current() is None
    assert (garden / "plan.md").read_text(encoding="utf-8") == "Beds in March."


# -- grants ---------------------------------------------------------------------------------


def granted_in(store, name, capability, *scopes):
    project = store.create(name)
    policy = store.policy(project.id)
    policy.grant(capability, tuple(str(s) for s in scopes))
    policy.save()
    return project


def test_a_project_grant_applies_only_while_that_project_is_open(store, folders):
    garden, _ = folders
    base = Policy()
    first = granted_in(store, "Garden", "files.read", garden)
    second = store.create("Novel")
    target = str(garden / "plan.md")

    store.set_current(first.id)
    assert store.effective(base).allows("files.read", target)
    store.set_current(second.id)
    assert not store.effective(base).allows("files.read", target)
    store.set_current("")
    assert store.effective(base) is base and not base.allows("files.read", target)


def test_the_global_grants_still_apply_inside_a_project(store, folders):
    garden, novel = folders
    base = Policy()
    base.grant("files.read", (str(novel),))
    store.set_current(granted_in(store, "Garden", "files.read", garden).id)
    effective = store.effective(base)
    assert effective.allows("files.read", str(novel / "x.md"))
    assert effective.allows("files.read", str(garden / "plan.md"))
    assert set(effective.granted("files.read").scopes) == {str(novel), str(garden)}


def test_a_refusal_explains_itself_from_the_layer_that_holds_the_capability(store, folders, tmp_path):
    garden, _ = folders
    store.set_current(granted_in(store, "Garden", "files.read", garden).id)
    decision = store.effective(Policy()).allows("files.read", str(tmp_path / "elsewhere.md"))
    assert not decision and "outside what" in decision.reason


def test_the_combined_view_cannot_be_edited(store, folders):
    garden, _ = folders
    store.set_current(granted_in(store, "Garden", "files.read", garden).id)
    effective = store.effective(Policy())
    assert isinstance(effective, LayeredPolicy)
    for change in (lambda: effective.grant("clipboard.read"), lambda: effective.revoke("files.read"),
                   effective.revoke_all, effective.save):
        with pytest.raises(RuntimeError):
            change()


def test_project_grants_fail_closed(store):
    project = store.create("Garden")
    (store.root / project.id / "permissions.json").write_text("[1, 2", encoding="utf-8")
    assert store.policy(project.id).active() == []


def test_tools_granted_in_the_open_project_are_offered_only_there(store, folders):
    garden, _ = folders
    base = Policy()
    project = granted_in(store, "Garden", "files.read", garden)
    offered = lambda: {t.name for t in default_registry().available(store.effective(base))}
    assert "read_file" not in offered()
    store.set_current(project.id)
    assert "read_file" in offered()


def test_the_review_sees_grants_made_in_projects(store, tmp_path):
    project = granted_in(store, "Garden", "files.write", Path.home())
    result = review(policy=Policy(), audit=AuditLog(tmp_path / "audit.jsonl"),
                    permissions_file=tmp_path / "permissions.json", protected=tmp_path,
                    projects=store.policies())
    assert any(f.code == "broad-path" and f.severity == "critical"
               and f.title.startswith("In the project Garden:") for f in result.findings)
    assert store.get(project.id) is not None
