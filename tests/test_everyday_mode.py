"""Everyday mode: the lock stands down, and nothing else changes.

The application exists to gate knowledge behind teaching, so a mode that turns
the gate off needs its blast radius pinned precisely. The properties that matter
are not "does it answer more" -- that is the easy part -- but:

* the stored record of what has been taught is never touched, so switching back
  is exact rather than a restore from memory;
* the flag cannot be reached by editing a file, only by the mode;
* the parts of the UI that report what you have taught keep telling the truth
  while the mode is on;
* and the user cannot possibly be in it without knowing.

If any of these break, everyday mode stops being a mode and becomes a bypass.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace

import pytest

from akira import store
from akira.context.assembly import ContextAssembler
from akira.lock.directive import build_directive, build_everyday_preamble
from akira.lock.pipeline import OutputGate
from akira.lock.tripwires import TopicTripwires, TripwireSet
from akira.models import ModelManager
from akira.personality.defaults import default_personality
from akira.projects import ensure_project
from akira.schemas import Manifest, Settings


TAUGHT = Manifest.initial().with_unlocked("python_basics").with_trust_tier(2)


# --- the manifest view ---------------------------------------------------------


def test_everything_reads_unlocked_in_the_view():
    view = TAUGHT.unrestricted_view()
    assert view.is_unlocked("geography")
    assert view.all_locked(["geography", "cryptography"]) == ()


def test_the_taught_list_is_untouched():
    """Switching back has to be exact, not reconstructed."""
    view = TAUGHT.unrestricted_view()
    assert view.unlocked_topics == ("python_basics",)
    assert view.history == TAUGHT.history


def test_the_flag_is_never_written_to_disk(tmp_path):
    """It must not be settable by editing the manifest.

    This is the whole reason it is a runtime field rather than a schema field:
    a persisted "unlock everything" boolean one JSON edit away from being true
    is a different and much worse thing than a mode.
    """
    view = TAUGHT.unrestricted_view()
    assert "unrestricted" not in view.to_json()

    vault = tmp_path / "vault"
    vault.mkdir()
    store.bootstrap_vault(vault)
    store.save_manifest(vault, view)
    assert store.load_manifest(vault).unrestricted is False


def test_an_unknown_key_in_the_manifest_cannot_turn_it_on():
    raw = TAUGHT.to_json()
    raw["unrestricted"] = True
    assert Manifest.from_json(raw).unrestricted is False


def test_a_malformed_topic_still_raises_in_everyday_mode():
    """The short circuit must not swallow a caller's bug."""
    from akira.schemas import SchemaError

    with pytest.raises(SchemaError):
        TAUGHT.unrestricted_view().is_unlocked("Not A Topic!")


# --- what the model is told ----------------------------------------------------


def test_the_preamble_replaces_the_constraint_rather_than_removing_it():
    """An absent directive and a failed directive look identical otherwise."""
    everyday = build_everyday_preamble()
    locked = build_directive(("python_basics",))

    assert "EVERYDAY MODE" in everyday.text
    assert "[LOCKED:" not in everyday.text
    assert "[LOCKED:" in locked.text
    assert everyday.text.strip(), "the slot must not be left empty"


def test_the_assembled_prompt_switches_with_the_mode(tmp_path):
    settings = Settings()
    assembler = ContextAssembler(settings, len)

    locked = assembler.assemble(
        manifest=TAUGHT, personality=default_personality(), user_text="hello",
    )
    open_mode = assembler.assemble(
        manifest=TAUGHT.unrestricted_view(), personality=default_personality(),
        user_text="hello",
    )
    assert "KNOWLEDGE CONSTRAINT" in locked.system_prompt
    assert "KNOWLEDGE CONSTRAINT" not in open_mode.system_prompt
    assert "EVERYDAY MODE" in open_mode.system_prompt


# --- the layers ----------------------------------------------------------------


def gate_for(vault, manifest, settings):
    manager = ModelManager(settings, factory=lambda spec: None)
    return OutputGate(manifest, settings, TripwireSet.load(vault), manager)


def test_tripwires_have_nothing_to_scan_in_everyday_mode(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    store.bootstrap_vault(vault)
    TripwireSet.save_topic(vault, TopicTripwires(topic="java_basics",
                                                 patterns=(r"System\.out\.print",)))

    settings = Settings()
    assert gate_for(vault, TAUGHT, settings).locked_topics_to_scan() == ("java_basics",)
    assert gate_for(vault, TAUGHT.unrestricted_view(), settings).locked_topics_to_scan() == ()


def test_notes_for_locked_topics_become_retrievable(tmp_path):
    """The user's own vault, in a mode that is meant to be an ordinary assistant."""
    from akira.lock.retrieval import retrieve
    from akira.vault import scan_vault

    vault = tmp_path / "vault"
    vault.mkdir()
    store.bootstrap_vault(vault)
    notes = vault / "global" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "thevenin.md").write_text(
        "---\ntopics: [dc_thevenin]\n---\n\nThevenin equivalent resistance is "
        "found by shorting every independent voltage source.\n",
        encoding="utf-8",
    )
    scan = scan_vault(vault)

    locked = retrieve(scan, TAUGHT, "thevenin equivalent resistance", project="default")
    assert len(locked.chunks) == 0

    everyday = retrieve(scan, TAUGHT.unrestricted_view(),
                        "thevenin equivalent resistance", project="default")
    assert len(everyday.chunks) >= 1


# --- the window ------------------------------------------------------------------


@pytest.fixture(scope="module")
def window(tmp_path_factory, tk_available, capture_paused):
    """One window for the module.

    Deliberately not paired with `clean_root`: a AkiraWindow *is* a `tk.Tk`,
    and standing one up beside the shared session root puts two live Tcl
    interpreters in a single test, which is the configuration that fails under
    pytest's default fd capture (see conftest).
    """
    from akira.ui.app import AkiraWindow

    vault = tmp_path_factory.mktemp("vault")
    store.bootstrap_vault(vault)
    ensure_project(vault, "default")
    store.save_manifest(vault, TAUGHT)
    try:
        with capture_paused():
            win = AkiraWindow(vault, store.load_manifest(vault), Settings(),
                              store.load_personality(vault))
    except tk.TclError:
        if tk_available:
            raise
        pytest.skip("Tk is unavailable in this environment")
    win.withdraw()
    win.update_idletasks()
    yield win
    try:
        win.manager.close()
        win.destroy()
    except tk.TclError:
        pass


@pytest.fixture(autouse=True)
def _reset_mode(request):
    """The window is shared, so leave the mode as it was found."""
    yield
    win = request.node.funcargs.get("window")
    if win is not None:
        win.settings = replace(win.settings, everyday_mode=False)
        win._rewire()


def test_off_by_default(window):
    assert window.settings.everyday_mode is False
    assert window._effective_manifest().unrestricted is False


def test_the_responder_gets_the_open_view_and_the_window_does_not(window):
    window.settings = replace(window.settings, everyday_mode=True)
    window._rewire()

    assert window._effective_manifest().unrestricted is True
    assert window.manifest.unrestricted is False, (
        "the window's own manifest must stay the true record -- the knowledge "
        "web and topic manager read it"
    )
    assert window.manifest.unlocked_topics == ("python_basics",)


def test_the_gating_layers_stand_down_but_retrieval_does_not(window):
    window.settings = replace(window.settings, everyday_mode=True)
    layers = window._effective_settings().lock_layers
    assert layers.tripwires is False and layers.auditor is False
    assert layers.retrieval is True, (
        "everyday mode must still see the user's own notes, or it is worse at "
        "their material than Akira mode is"
    )


def test_the_stored_settings_keep_their_real_layer_switches(window):
    """Only the responder's copy is altered."""
    window.settings = replace(window.settings, everyday_mode=True)
    window._effective_settings()
    assert window.settings.lock_layers.auditor is True


def test_the_banner_shows_while_the_mode_is_on(window):
    window.settings = replace(window.settings, everyday_mode=True)
    window._refresh_layer_warning()
    window.update_idletasks()
    assert "EVERYDAY MODE" in window.warning_var.get()
    assert window.warning_label.winfo_manager(), "the banner is not packed"

    window.settings = replace(window.settings, everyday_mode=False)
    window._refresh_layer_warning()
    window.update_idletasks()
    assert not window.warning_label.winfo_manager()


def test_the_status_line_names_the_mode(window):
    window.settings = replace(window.settings, everyday_mode=True)
    window._refresh_status()
    assert "EVERYDAY MODE" in window.status_var.get()


def test_switching_back_restores_the_lock_exactly(window):
    before = window.manifest
    window.settings = replace(window.settings, everyday_mode=True)
    window._rewire()
    window.settings = replace(window.settings, everyday_mode=False)
    window._rewire()

    assert window.manifest == before
    assert window._effective_manifest().unrestricted is False
    assert window._effective_manifest().all_locked(["geography"]) == ("geography",)
