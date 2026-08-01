"""Realistic user flows through every dialog.

Hunting one specific class of defect: an action that *looks* like it took
effect and did not. The personality bug was exactly that -- the preview
updated live as sliders moved, so closing the window read as "applied" while
silently discarding. Anywhere else the UI shows a change before committing it
is a candidate for the same trap.
"""

from __future__ import annotations

import json

import pytest

from protege import store
from protege.lock.pipeline import OutputGate
from protege.lock.tripwires import TripwireSet
from protege.memory.live import LiveMemory
from protege.models import ModelManager, ModelSpec, Role
from protege.models.scripted import ScriptedBackend
from protege.projects import ensure_project
from protege.schemas import Manifest, Settings


@pytest.fixture
def root(clean_root):
    """The shared session-wide Tk interpreter (see conftest.py).

    Not a fresh `tk.Tk()` per module: several live interpreters in one process
    made Tk fail intermittently, and the fixture's TclError handler turned that
    into a silent skip of the whole module.
    """
    return clean_root


@pytest.fixture
def vault(tmp_path):
    root_path = tmp_path / "vault"
    root_path.mkdir()
    store.bootstrap_vault(root_path)
    ensure_project(root_path, "default")
    return root_path


def pieces(vault, unlocked=("physics",), tier=2):
    manifest = Manifest.initial().with_trust_tier(tier)
    for topic in unlocked:
        manifest = manifest.with_unlocked(topic)
    # Distinct paths on purpose. Identical paths make ModelManager share one
    # backend for both roles -- correct behaviour, and it silently turned the
    # scripted auditor into the scripted MAIN, so every gated write "failed"
    # for a reason that had nothing to do with the code under test.
    settings = Settings.from_json(
        {"models": {"main_path": "main.gguf", "auditor_path": "auditor.gguf",
                    "loading": "concurrent"}}
    )
    main = ScriptedBackend(ModelSpec(path="main.gguf", role=Role.MAIN), patterns=[(r".*", "ok")])
    auditor = ScriptedBackend(ModelSpec(path="auditor.gguf", role=Role.AUDITOR),
                              patterns=[(r".*", "VERDICT: PASS")])
    manager = ModelManager(settings, factory=lambda s: main if s.role is Role.MAIN else auditor)
    gate = OutputGate(manifest, settings, TripwireSet.load(vault), manager)
    return manifest, settings, manager, gate


# --- memory panel -----------------------------------------------------------


def test_memory_edit_persists_to_the_live_file(root, vault):
    from protege.ui.memory_panel import MemoryPanel

    manifest, _, _, gate = pieces(vault)
    memory = LiveMemory(vault, "default", manifest, gate, session_id="s1")
    memory.write("Original entry.", topics=["physics"])

    panel = MemoryPanel(root, memory, manifest.unlocked_topics)
    panel.update_idletasks()
    panel.listbox.selection_set(0)
    panel._show_selected()
    panel.editor.delete("1.0", "end")
    panel.editor.insert("1.0", "Corrected by hand.")
    panel._save_edit()

    assert "Corrected by hand." in memory.path.read_text(encoding="utf-8")
    panel.destroy()


def test_memory_discard_removes_the_entry(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    monkeypatch.setattr(mb, "askokcancel", lambda *a, **k: True)
    from protege.ui.memory_panel import MemoryPanel

    manifest, _, _, gate = pieces(vault)
    memory = LiveMemory(vault, "default", manifest, gate, session_id="s2")
    memory.write("Doomed entry.", topics=["physics"])

    panel = MemoryPanel(root, memory, manifest.unlocked_topics)
    panel.update_idletasks()
    panel.listbox.selection_set(0)
    panel._discard()

    assert memory.entries == []
    assert not memory.path.exists()
    panel.destroy()


def test_memory_pin_writes_immediately(root, vault):
    from protege.ui.memory_panel import MemoryPanel

    manifest, _, _, gate = pieces(vault)
    memory = LiveMemory(vault, "default", manifest, gate, session_id="s3")
    panel = MemoryPanel(root, memory, manifest.unlocked_topics)
    panel.update_idletasks()
    panel.pin_entry.insert(0, "A pinned fact.")
    panel._pin()

    assert len(memory.entries) == 1
    assert "A pinned fact." in memory.path.read_text(encoding="utf-8")
    panel.destroy()


def test_memory_pin_refused_by_the_gate_is_reported(root, vault, monkeypatch):
    """A blocked write must surface, not vanish."""
    import tkinter.messagebox as mb

    errors = []
    monkeypatch.setattr(mb, "showerror", lambda *a, **k: errors.append(a))
    from protege.ui.memory_panel import MemoryPanel

    (store.tripwire_dir(vault) / "chemistry.json").write_text(
        json.dumps({"topic": "chemistry", "keywords": ["sodium"]}), encoding="utf-8"
    )
    manifest, settings, manager, _ = pieces(vault)
    gate = OutputGate(manifest, settings, TripwireSet.load(vault), manager)
    memory = LiveMemory(vault, "default", manifest, gate, session_id="s4")

    panel = MemoryPanel(root, memory, manifest.unlocked_topics)
    panel.update_idletasks()
    panel.pin_entry.insert(0, "sodium reacts violently with water")
    panel._pin()

    assert errors, "a refused write must tell the user"
    assert memory.entries == []
    panel.destroy()


# --- attachments ------------------------------------------------------------


def test_removing_an_attachment_returns_the_updated_list(root):
    from protege.ui.file_dialogs import AttachmentsDialog

    dialog = AttachmentsDialog(root, [("a.txt", "one"), ("b.txt", "two")])
    dialog.update_idletasks()
    dialog.listbox.selection_set(0)
    dialog._remove()
    dialog._close()

    assert [name for name, _ in dialog.result] == ["b.txt"]
    dialog.destroy()


def test_closing_attachments_without_removing_keeps_everything(root):
    from protege.ui.file_dialogs import AttachmentsDialog

    dialog = AttachmentsDialog(root, [("a.txt", "one")])
    dialog.update_idletasks()
    dialog._close()
    assert [name for name, _ in dialog.result] == ["a.txt"]
    dialog.destroy()


# --- topic manager ----------------------------------------------------------


def test_topic_manager_returns_the_manifest_on_close(root, vault):
    from protege.ui.unlock_dialog import TopicManagerDialog
    from protege.unlock import UnlockFlow

    manifest, settings, manager, _ = pieces(vault)
    flow = UnlockFlow(vault, manifest, settings, manager, tripwires=TripwireSet.load(vault))
    dialog = TopicManagerDialog(root, flow)
    dialog.update_idletasks()
    dialog._close()
    assert dialog.result is not None
    assert dialog.result.is_unlocked("physics")
    dialog.destroy()


def test_relock_via_dialog_updates_the_manifest(root, vault, monkeypatch):
    from protege.ui.unlock_dialog import RelockDialog
    from protege.unlock import UnlockFlow

    manifest, settings, manager, _ = pieces(vault)
    flow = UnlockFlow(vault, manifest, settings, manager, tripwires=TripwireSet.load(vault))
    dialog = RelockDialog(root, flow, "physics")
    dialog.update_idletasks()
    dialog._confirm()

    assert dialog.result is not None
    assert not dialog.result.is_unlocked("physics")
    dialog.destroy()


# --- knowledge web ----------------------------------------------------------


def test_web_reports_no_change_when_nothing_was_done(root, vault):
    """Returning a manifest when nothing changed would make the caller
    re-save and re-wire on every close."""
    from protege.ui.knowledge_web import KnowledgeWebDialog
    from protege.unlock import UnlockFlow

    manifest, settings, manager, _ = pieces(vault)
    flow = UnlockFlow(vault, manifest, settings, manager, tripwires=TripwireSet.load(vault))
    dialog = KnowledgeWebDialog(root, flow)
    dialog.update_idletasks()
    dialog._close()
    assert dialog.result is None
    dialog.destroy()


def test_web_action_buttons_track_the_selection(root, vault):
    from protege.ui.knowledge_web import KnowledgeWebDialog
    from protege.unlock import UnlockFlow

    (vault / "global" / "notes").mkdir(parents=True, exist_ok=True)
    (vault / "global" / "notes" / "a.md").write_text(
        "---\ntopics: [physics]\n---\n\nUnlocked.\n", encoding="utf-8")
    (vault / "global" / "notes" / "b.md").write_text(
        "---\ntopics: [chemistry]\n---\n\nLocked.\n", encoding="utf-8")

    manifest, settings, manager, _ = pieces(vault)
    flow = UnlockFlow(vault, manifest, settings, manager, tripwires=TripwireSet.load(vault))
    dialog = KnowledgeWebDialog(root, flow)
    dialog.update_idletasks()

    # Nothing selected: neither action is offered.
    assert str(dialog._unlock_button.cget("state")) == "disabled"
    assert str(dialog._relock_button.cget("state")) == "disabled"

    dialog._selected = "physics"
    dialog._set_action_state("physics")
    assert str(dialog._unlock_button.cget("state")) == "disabled"   # already unlocked
    assert str(dialog._relock_button.cget("state")) == "normal"

    dialog._selected = "chemistry"
    dialog._set_action_state("chemistry")
    assert str(dialog._unlock_button.cget("state")) == "normal"
    assert str(dialog._relock_button.cget("state")) == "disabled"
    dialog.destroy()


# --- settings: unsaved-change guard ----------------------------------------


def make_settings(root, vault):
    from protege.ui.settings_window import SettingsWindow

    return SettingsWindow(
        root, vault, store.load_manifest(vault), store.load_settings(vault),
        store.load_personality(vault), on_apply=lambda *_: None,
    )


def test_untouched_settings_close_without_prompting(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    asked = []
    monkeypatch.setattr(mb, "askokcancel", lambda *a, **k: asked.append(a) or True)
    window = make_settings(root, vault)
    window.update_idletasks()
    window._cancel()
    assert asked == [], "closing an unmodified window must not nag"


def test_personality_edit_then_close_warns(root, vault, monkeypatch):
    """The reported bug, as a regression test."""
    import tkinter.messagebox as mb

    asked = []
    monkeypatch.setattr(mb, "askokcancel", lambda *a, **k: asked.append(a) or False)
    window = make_settings(root, vault)
    window.update_idletasks()
    window._sliders_moved = window.personality_panel._sliders["directness"].set(95)
    window.update_idletasks()

    window._cancel()
    assert asked, "closing with unsaved personality edits must confirm"
    assert "personality" in asked[0][1]
    assert window.winfo_exists(), "declining the prompt must keep the window open"
    window.destroy()


def test_field_edit_then_close_warns(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    asked = []
    monkeypatch.setattr(mb, "askokcancel", lambda *a, **k: asked.append(a) or True)
    window = make_settings(root, vault)
    window.update_idletasks()
    window.system_prompt.insert("1.0", "Be terse.")
    window._cancel()
    assert asked and "settings" in asked[0][1]


def test_tier_change_then_close_warns(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    asked = []
    monkeypatch.setattr(mb, "askokcancel", lambda *a, **k: asked.append(a) or True)
    window = make_settings(root, vault)
    window.update_idletasks()
    window.tier_var.set(2)
    window._cancel()
    assert asked and "trust tier" in asked[0][1]


def test_saving_then_closing_does_not_warn(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    asked = []
    monkeypatch.setattr(mb, "askokcancel", lambda *a, **k: asked.append(a) or True)
    window = make_settings(root, vault)
    window.update_idletasks()
    window.personality_panel._sliders["humor"].set(15)
    window.update_idletasks()
    window._save()          # destroys the window
    assert asked == [], "a saved window has nothing to discard"
