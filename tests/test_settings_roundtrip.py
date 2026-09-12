"""End-to-end UI flows: does what the user did actually persist?

These drive the real widgets the way a person does -- move a slider, press
Save, close, reopen -- and then check the file on disk. Unit tests on the
underlying dataclasses all passed while the Settings window was still losing
personality edits, because the bug lived in the wiring between them.
"""

from __future__ import annotations


import pytest

from akira import store
from akira.projects import ensure_project


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


def open_settings(root, vault):
    from akira.ui.settings_window import SettingsWindow

    manifest = store.load_manifest(vault)
    settings = store.load_settings(vault)
    personality = store.load_personality(vault)
    applied = {}

    def on_apply(m, s, p):
        applied["manifest"], applied["settings"], applied["personality"] = m, s, p

    window = SettingsWindow(root, vault, manifest, settings, personality, on_apply=on_apply)
    window.update_idletasks()
    return window, applied


# --- personality persistence ------------------------------------------------


def test_slider_move_then_save_persists_to_disk(root, vault):
    """The reported bug: personality edits vanished on leaving Settings."""
    window, applied = open_settings(root, vault)
    panel = window.personality_panel

    panel._sliders["directness"].set(95)
    panel._sliders["humor"].set(5)
    window.update_idletasks()

    window._save()

    saved = store.load_personality(vault)
    profile = saved.active()
    assert profile.values["directness"] == 95, "slider value did not reach disk"
    assert profile.values["humor"] == 5


def test_saved_personality_reopens_with_the_same_values(root, vault):
    window, _ = open_settings(root, vault)
    window.personality_panel._sliders["verbosity"].set(88)
    window.update_idletasks()
    window._save()

    reopened, _ = open_settings(root, vault)
    assert reopened.personality_panel._sliders["verbosity"].get() == 88
    reopened.destroy()


def test_save_reports_the_personality_to_the_main_window(root, vault):
    window, applied = open_settings(root, vault)
    window.personality_panel._sliders["warmth"].set(90)
    window.update_idletasks()
    window._save()
    assert applied["personality"].active().values["warmth"] == 90


def test_rebuilding_sliders_does_not_clobber_other_traits(root, vault):
    """Each LabeledSlider fires its callback while being constructed, so a
    rebuild commits partially-populated profiles unless guarded."""
    window, _ = open_settings(root, vault)
    panel = window.personality_panel
    panel._sliders["directness"].set(90)
    panel._sliders["formality"].set(10)
    window.update_idletasks()

    panel._rebuild_sliders()
    window.update_idletasks()

    values = panel._current_profile().values
    assert values["directness"] == 90
    assert values["formality"] == 10
    assert len(values) == len(panel.personality.traits)


def test_new_profile_is_saved_and_selectable(root, vault):
    window, _ = open_settings(root, vault)
    panel = window.personality_panel
    panel._sliders["directness"].set(100)
    panel.profile_var.set("blunt")
    panel._commit()
    window.update_idletasks()
    window._save()

    saved = store.load_personality(vault)
    assert saved.profile("blunt") is not None
    assert saved.profile("blunt").values["directness"] == 100


def test_cancel_does_not_write_personality(root, vault):
    before = store.load_personality(vault).active().values["directness"]
    window, _ = open_settings(root, vault)
    window.personality_panel._sliders["directness"].set(97)
    window.update_idletasks()
    window.destroy()  # Cancel / window close

    assert store.load_personality(vault).active().values["directness"] == before


# --- the other tabs round-trip too ------------------------------------------


def test_system_prompt_persists(root, vault):
    window, _ = open_settings(root, vault)
    window.system_prompt.delete("1.0", "end")
    window.system_prompt.insert("1.0", "Answer only in questions.")
    window._save()
    assert store.load_settings(vault).system_prompt == "Answer only in questions."


def test_model_fields_persist(root, vault):
    window, _ = open_settings(root, vault)
    window.temperature.delete(0, "end")
    window.temperature.insert(0, "0.25")
    window.max_tokens.delete(0, "end")
    window.max_tokens.insert(0, "512")
    window._save()
    models = store.load_settings(vault).models
    assert models.temperature == 0.25
    assert models.max_tokens == 512


def test_lock_layer_toggle_persists(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    monkeypatch.setattr(mb, "askokcancel", lambda *a, **k: True)
    window, _ = open_settings(root, vault)
    window.layer_vars["tripwires"].set(False)
    window._save()
    assert store.load_settings(vault).lock_layers.tripwires is False


def test_memory_settings_persist(root, vault):
    window, _ = open_settings(root, vault)
    window.holding_days.delete(0, "end")
    window.holding_days.insert(0, "30")
    window.auto_confirm.set(True)
    window._save()
    memory = store.load_settings(vault).memory
    assert memory.holding_days == 30
    assert memory.auto_confirm is True


def test_invalid_field_is_refused_without_writing(root, vault, monkeypatch):
    import tkinter.messagebox as mb

    errors = []
    monkeypatch.setattr(mb, "showerror", lambda *a, **k: errors.append(a))
    before = store.load_settings(vault).models.temperature

    window, _ = open_settings(root, vault)
    window.temperature.delete(0, "end")
    window.temperature.insert(0, "not-a-number")
    window._save()

    assert errors, "a bad value should raise an error dialog"
    assert store.load_settings(vault).models.temperature == before
    assert window.winfo_exists(), "the window must stay open so the value can be fixed"
    window.destroy()
