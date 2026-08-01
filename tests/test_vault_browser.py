"""Vault browser: note editing, note deletion, and project management."""

from __future__ import annotations


import pytest

from protege import store
from protege.projects import (
    ProjectError,
    delete_project,
    ensure_project,
    get_project,
    list_projects,
    project_contents,
    rename_project,
)
from protege.schemas import Manifest, SchemaError
from protege.vault import read_note


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    store.bootstrap_vault(root)
    ensure_project(root, "default")
    return root


def put(vault, rel, topics, body="Body."):
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntopics: [%s]\n---\n\n%s\n" % (", ".join(topics), body), encoding="utf-8"
    )
    return path


# --- project operations (no Tk) ---------------------------------------------


def test_project_contents_counts_what_will_be_lost(vault):
    ensure_project(vault, "demo")
    project = get_project(vault, "demo")
    put(vault, "projects/demo/notes/a.md", ["physics"])
    put(vault, "projects/demo/notes/b.md", ["physics"])
    (project.skills_dir / "s.py").write_text("print(1)", encoding="utf-8")
    contents = project_contents(project)
    assert contents.notes == 2
    assert contents.skills == 1
    assert "2 note(s)" in contents.describe()


def test_empty_project_says_so(vault):
    ensure_project(vault, "empty")
    assert project_contents(get_project(vault, "empty")).describe() == "This project is empty."


def test_rename_moves_the_tree(vault):
    ensure_project(vault, "old")
    put(vault, "projects/old/notes/a.md", ["physics"], "Kept content.")
    renamed = rename_project(vault, "old", "new")
    assert renamed.name == "new"
    assert not (vault / "projects" / "old").exists()
    assert (vault / "projects" / "new" / "notes" / "a.md").read_text(encoding="utf-8").count("Kept content.")


def test_rename_refuses_to_overwrite(vault):
    ensure_project(vault, "a")
    ensure_project(vault, "b")
    with pytest.raises(ProjectError, match="already exists"):
        rename_project(vault, "a", "b")


def test_rename_refuses_an_invalid_name(vault):
    ensure_project(vault, "a")
    with pytest.raises(SchemaError):
        rename_project(vault, "a", "../escape")


def test_rename_of_a_missing_project_raises(vault):
    with pytest.raises(ProjectError, match="does not exist"):
        rename_project(vault, "ghost", "other")


def test_delete_removes_everything(vault):
    ensure_project(vault, "doomed")
    put(vault, "projects/doomed/notes/a.md", ["physics"])
    delete_project(vault, "doomed")
    assert not (vault / "projects" / "doomed").exists()
    assert "doomed" not in [p.name for p in list_projects(vault)]


def test_delete_refuses_the_last_project(vault):
    # A vault with zero projects is a state the rest of the app does not expect.
    assert [p.name for p in list_projects(vault)] == ["default"]
    with pytest.raises(ProjectError, match="only project"):
        delete_project(vault, "default")


def test_delete_of_a_missing_project_raises(vault):
    ensure_project(vault, "other")
    with pytest.raises(ProjectError, match="does not exist"):
        delete_project(vault, "ghost")


# --- Tk-dependent -----------------------------------------------------------


@pytest.fixture
def root(clean_root):
    """The shared session-wide Tk interpreter (see conftest.py).

    Not a fresh `tk.Tk()` per module: several live interpreters in one process
    made Tk fail intermittently, and the fixture's TclError handler turned that
    into a silent skip of the whole module.
    """
    return clean_root


def open_browser(root, vault, manifest=None, project="default"):
    from protege.ui.vault_browser import VaultBrowser

    browser = VaultBrowser(root, vault, manifest or store.load_manifest(vault), project)
    browser.update_idletasks()
    return browser


def test_lists_notes_with_visibility_marks(root, vault):
    put(vault, "global/notes/open.md", ["physics"])
    put(vault, "global/notes/locked.md", ["chemistry"])
    put(vault, "global/notes/untagged.md", [])
    manifest = Manifest.initial().with_unlocked("physics")

    browser = open_browser(root, vault, manifest)
    rows = [browser.listbox.get(i) for i in range(browser.listbox.size())]
    assert any(r.startswith("[*]") and "open.md" in r for r in rows)
    assert any(r.startswith("[L]") and "locked.md" in r for r in rows)
    assert any(r.startswith("[-]") and "untagged.md" in r for r in rows)
    browser.destroy()


def test_editing_a_note_body_persists(root, vault):
    path = put(vault, "global/notes/a.md", ["physics"], "Original body.")
    browser = open_browser(root, vault)
    browser.listbox.selection_set(0)
    browser._open_selected()
    browser.editor.delete("1.0", "end")
    browser.editor.insert("1.0", "Rewritten body.")
    browser._save_note()

    note = read_note(path, vault)
    assert "Rewritten body." in note.body
    assert note.topics == ("physics",)
    browser.destroy()


def test_retagging_changes_visibility(root, vault):
    path = put(vault, "global/notes/a.md", ["chemistry"], "Content.")
    manifest = Manifest.initial().with_unlocked("physics")
    browser = open_browser(root, vault, manifest)
    browser.listbox.selection_set(0)
    browser._open_selected()

    assert not read_note(path, vault).visible_to(manifest)
    browser.topics_entry.delete(0, "end")
    browser.topics_entry.insert(0, "physics")
    browser._save_note()

    assert read_note(path, vault).visible_to(manifest)
    browser.destroy()


def test_save_preserves_protege_written_frontmatter(root, vault):
    """A memory note carries session and provenance keys; retagging it must not
    flatten them away."""
    from protege.vault import render_note

    path = vault / "projects" / "default" / "notes" / "mem.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_note(["physics"], "Remembered.", extra={"kind": "note", "session": "abc123"}),
        encoding="utf-8",
    )
    browser = open_browser(root, vault)
    idx = [i for i in range(browser.listbox.size()) if "mem.md" in browser.listbox.get(i)][0]
    browser.listbox.selection_set(idx)
    browser._open_selected()
    browser._save_note()

    note = read_note(path, vault)
    assert note.frontmatter.get("session") == "abc123"
    assert note.frontmatter.get("kind") == "note"
    browser.destroy()


def test_bad_topic_blocks_the_save(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    errors = []
    monkeypatch.setattr(mb, "showerror", lambda *a, **k: errors.append(a))
    path = put(vault, "global/notes/a.md", ["physics"], "Original.")
    browser = open_browser(root, vault)
    browser.listbox.selection_set(0)
    browser._open_selected()
    browser.topics_entry.delete(0, "end")
    browser.topics_entry.insert(0, "physics, ???")
    browser.editor.delete("1.0", "end")
    browser.editor.insert("1.0", "Should not be written.")
    browser._save_note()

    assert errors
    assert "Should not be written." not in path.read_text(encoding="utf-8")
    browser.destroy()


def test_deleting_a_note_removes_the_file(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    monkeypatch.setattr(mb, "askokcancel", lambda *a, **k: True)
    path = put(vault, "global/notes/doomed.md", ["physics"])
    browser = open_browser(root, vault)
    browser.listbox.selection_set(0)
    browser._open_selected()
    browser._delete_note()

    assert not path.exists()
    assert browser.result is None or browser._changed
    browser.destroy()


def test_declining_the_delete_confirmation_keeps_the_file(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    monkeypatch.setattr(mb, "askokcancel", lambda *a, **k: False)
    path = put(vault, "global/notes/safe.md", ["physics"])
    browser = open_browser(root, vault)
    browser.listbox.selection_set(0)
    browser._open_selected()
    browser._delete_note()

    assert path.exists()
    browser.destroy()


def test_other_projects_notes_are_not_listed(root, vault):
    ensure_project(vault, "other")
    put(vault, "projects/default/notes/mine.md", ["physics"])
    put(vault, "projects/other/notes/theirs.md", ["physics"])
    browser = open_browser(root, vault, project="default")
    rows = " ".join(browser.listbox.get(i) for i in range(browser.listbox.size()))
    assert "mine.md" in rows
    assert "theirs.md" not in rows
    browser.destroy()


def test_global_notes_show_in_every_project(root, vault):
    ensure_project(vault, "other")
    put(vault, "global/notes/g.md", ["physics"])
    for project in ("default", "other"):
        browser = open_browser(root, vault, project=project)
        rows = " ".join(browser.listbox.get(i) for i in range(browser.listbox.size()))
        assert "global/notes/g.md" in rows
        browser.destroy()


def test_project_delete_via_browser(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    monkeypatch.setattr(mb, "askokcancel", lambda *a, **k: True)
    ensure_project(vault, "doomed")
    browser = open_browser(root, vault, project="default")
    browser.project_var.set("doomed")
    browser._delete_project()

    assert "doomed" not in [p.name for p in list_projects(vault)]
    assert browser._changed
    browser.destroy()
