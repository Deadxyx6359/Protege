"""Construction smoke tests for the Tk interface.

These do not drive the UI -- they build each window, let Tk process its pending
events, and tear it down. That is enough to catch the class of mistake Tk is
prone to and Python's type checker is not: a bad `pack` argument, a widget
referenced before it exists, a callback bound to a missing attribute. Those
surface as a traceback at construction, not at import, so an import test does
not reach them.

Skipped entirely where no display is available.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from akira.lock.pipeline import OutputGate
from akira.lock.tripwires import TripwireSet
from akira.memory.live import LiveMemory
from akira.models import ModelManager, ModelSpec, Role
from akira.models.scripted import ScriptedBackend
from akira.personality.defaults import default_personality
from akira.projects import ensure_project
from akira.schemas import Manifest, Settings
from akira.store import bootstrap_vault
from akira.unlock import UnlockFlow


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
    bootstrap_vault(root_path)
    ensure_project(root_path, "default")
    (root_path / "global" / "notes" / "a.md").write_text(
        "---\ntopics: [physics]\n---\n\nGravity accelerates objects.\n", encoding="utf-8"
    )
    return root_path


@pytest.fixture
def pieces(vault):
    manifest = Manifest.initial().with_unlocked("physics").with_trust_tier(2)
    settings = Settings.from_json(
        {"models": {"main_path": "m.gguf", "auditor_path": "a.gguf", "loading": "concurrent"}}
    )
    main = ScriptedBackend(ModelSpec(path="m.gguf", role=Role.MAIN), patterns=[(r".*", "ok")])
    auditor = ScriptedBackend(ModelSpec(path="a.gguf", role=Role.AUDITOR), patterns=[(r".*", "VERDICT: PASS")])
    manager = ModelManager(settings, factory=lambda s: main if s.role is Role.MAIN else auditor)
    gate = OutputGate(manifest, settings, TripwireSet.load(vault), manager)
    return vault, manifest, settings, manager, gate


def pump(widget: tk.Misc) -> None:
    widget.update_idletasks()


def test_widgets_module_constructs(root):
    from akira.ui.widgets import LabeledSlider, ScrollableFrame

    slider = LabeledSlider(root, "Directness", ["a", "b", "c", "d", "e"], 75)
    pump(root)
    assert slider.get() == 75
    # The number must not appear in the visible label -- only the band prose.
    assert "75" not in slider.band_label.cget("text")
    assert slider.band_label.cget("text") == "d"
    slider.destroy()

    frame = ScrollableFrame(root)
    pump(root)
    frame.destroy()


def test_labeled_slider_marks_neutral(root):
    from akira.ui.widgets import LabeledSlider

    slider = LabeledSlider(root, "Warmth", ["a", "b", "c", "d", "e"], 50)
    pump(root)
    assert "neutral" in slider.band_number.cget("text")
    slider.destroy()


def test_pin_dialogs_construct(root):
    from akira.ui.pin_dialog import PinChangeDialog, PinPromptDialog, PinSetupDialog
    from akira.security.pin import hash_pin

    encoded = hash_pin("1234")
    for dialog in (
        PinSetupDialog(root),
        PinPromptDialog(root, encoded),
        PinChangeDialog(root, encoded),
    ):
        pump(dialog)
        dialog.destroy()


def test_unlock_dialogs_construct(root, pieces):
    from akira.ui.unlock_dialog import RelockDialog, TopicManagerDialog, UnlockDialog

    vault, manifest, settings, manager, _ = pieces
    flow = UnlockFlow(vault, manifest, settings, manager, tripwires=TripwireSet.load(vault))

    for dialog in (
        UnlockDialog(root, flow),
        TopicManagerDialog(root, flow),
        RelockDialog(root, flow, "physics"),
    ):
        pump(dialog)
        dialog.destroy()


def test_memory_panel_constructs(root, pieces):
    from akira.ui.memory_panel import MemoryPanel

    vault, manifest, settings, manager, gate = pieces
    memory = LiveMemory(vault, "default", manifest, gate, session_id="s1")
    memory.write("A remembered fact.", topics=["physics"])

    panel = MemoryPanel(root, memory, manifest.unlocked_topics)
    pump(panel)
    panel.destroy()


def test_consolidation_review_constructs(root, pieces):
    from akira.memory.consolidate import Consolidator
    from akira.ui.memory_panel import ConsolidationReviewDialog

    vault, manifest, settings, manager, gate = pieces
    memory = LiveMemory(vault, "default", manifest, gate, session_id="s2")
    memory.write("A remembered fact.", topics=["physics"])
    consolidator = Consolidator(vault, "default", manifest, settings, manager, gate)
    result = consolidator.consolidate(memory, "transcript")

    dialog = ConsolidationReviewDialog(root, consolidator, result)
    pump(dialog)
    dialog.destroy()


def test_personality_panel_constructs(root):
    from akira.ui.personality_panel import NewTraitDialog, PersonalityPanel

    captured = []
    panel = PersonalityPanel(root, default_personality(), on_change=captured.append)
    pump(panel)
    # Every shipped trait gets a slider.
    assert len(panel._sliders) == len(default_personality().traits)
    panel.destroy()

    dialog = NewTraitDialog(root, ("directness",))
    pump(dialog)
    assert len(dialog.band_entries) == 5
    dialog.destroy()


def test_settings_window_constructs(root, pieces):
    from akira.ui.settings_window import SettingsWindow

    vault, manifest, settings, _, _ = pieces
    window = SettingsWindow(
        root, vault, manifest, settings, default_personality(),
        on_apply=lambda *_: None, prompt_view="example",
    )
    pump(window)
    # Every tab from the brief's settings list, plus Review. A setting with no
    # way to reach it is an inert setting, which this project has shipped once
    # already and does not intend to again.
    tabs = [window.notebook.tab(i, "text") for i in range(len(window.notebook.tabs()))]
    assert tabs == [
        "Models", "Prompt", "Personality", "Lock layers", "Tripwires", "Memory",
        "Review", "Security", "Plugins",
    ]
    window.destroy()


def test_skills_window_constructs(root, pieces):
    from akira.ui.skills_window import SkillsWindow

    vault, manifest, settings, manager, gate = pieces
    window = SkillsWindow(root, vault, "default", manifest, settings, manager, gate)
    pump(window)
    window.destroy()


def test_settings_collect_roundtrips_unchanged(root, pieces):
    from akira.ui.settings_window import SettingsWindow

    vault, manifest, settings, _, _ = pieces
    window = SettingsWindow(
        root, vault, manifest, settings, default_personality(), on_apply=lambda *_: None
    )
    pump(window)
    # Opening Settings and saving without touching anything must not change
    # the stored configuration.
    rebuilt = Settings.from_json(window._collect())
    assert rebuilt.to_json() == settings.to_json()
    window.destroy()


def test_main_window_constructs_and_reports_missing_models(vault, tk_available):
    """The main window is the most complex constructor; build one for real.

    Not using the shared `root` fixture: AkiraWindow *is* a `tk.Tk`, and two
    live Tk instances in one process is a configuration Tk tolerates badly.
    """
    from akira.ui.app import AkiraWindow

    manifest = Manifest.initial().with_unlocked("physics")
    settings = Settings.from_json({"vault_path": str(vault)})
    try:
        window = AkiraWindow(vault, manifest, settings, default_personality())
    except tk.TclError:
        if tk_available:
            # Tk works in this process, so this is a real defect.
            raise
        pytest.skip("Tk is unavailable in this environment")

    window.withdraw()
    pump(window)
    try:
        assert "1 unlocked" in window.status_var.get()
        assert "Tier 0" in window.status_var.get()
        # All layers on by default, so the warning strip stays hidden.
        assert window.warning_var.get() == ""
        # No model configured and llama-cpp-python absent: sending must refuse
        # rather than substitute anything.
        assert not window.manager.status().ready
    finally:
        window.destroy()


def test_main_window_shows_the_warning_strip_when_a_layer_is_off(vault, tk_available):
    from akira.ui.app import AkiraWindow

    settings = Settings.from_json({"lock_layers": {"auditor": False}})
    try:
        window = AkiraWindow(vault, Manifest.initial(), settings, default_personality())
    except tk.TclError:
        if tk_available:
            # Tk works in this process, so this is a real defect.
            raise
        pytest.skip("Tk is unavailable in this environment")

    window.withdraw()
    pump(window)
    try:
        assert "WARNING" in window.warning_var.get()
        assert "auditor" in window.warning_var.get()
    finally:
        window.destroy()


def test_layer_warning_appears_only_when_a_layer_is_off(root, pieces):
    from akira.ui.settings_window import SettingsWindow

    vault, manifest, settings, _, _ = pieces
    window = SettingsWindow(
        root, vault, manifest, settings, default_personality(), on_apply=lambda *_: None
    )
    pump(window)
    assert "All five layers active" in window.layer_warning.cget("text")

    window.layer_vars["auditor"].set(False)
    window._update_layer_warning()
    assert "WARNING" in window.layer_warning.cget("text")
    window.destroy()
