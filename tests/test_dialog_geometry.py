"""Every dialog must fit its own contents at its default size.

The reported symptom was having to drag a window bigger to reach Save. That is
not cosmetic: a button below the fold is a feature the user cannot invoke, and
on a laptop screen "just resize it" may not even be available.

Tk computes what a window *needs* via `winfo_reqwidth/reqheight` once its
children are laid out. Comparing that against the geometry the dialog asked for
catches clipping without anyone having to look at a screenshot -- and catches it
again automatically if someone adds a row later.
"""

from __future__ import annotations


import pytest

from protege import store
from protege.lock.pipeline import OutputGate
from protege.lock.tripwires import TripwireSet
from protege.models import ModelManager
from protege.personality.defaults import default_personality
from protege.projects import ensure_project
from protege.schemas import Manifest, Settings
from protege.unlock import UnlockFlow


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
    (root_path / "global" / "notes").mkdir(parents=True, exist_ok=True)
    (root_path / "global" / "notes" / "a.md").write_text(
        "---\ntopics: [physics]\n---\n\nGravity.\n", encoding="utf-8"
    )
    return root_path


def pieces(vault):
    manifest = Manifest.initial().with_unlocked("physics").with_trust_tier(2)
    settings = Settings.from_json(
        {"models": {"main_path": "m.gguf", "auditor_path": "a.gguf", "loading": "concurrent"}}
    )
    manager = ModelManager(settings, factory=lambda spec: None)
    gate = OutputGate(manifest, settings, TripwireSet.load(vault), manager)
    return manifest, settings, manager, gate


def geometry_of(window) -> tuple[int, int, int, int]:
    """(requested_w, requested_h, opens_at_w, opens_at_h).

    Reads the size the dialog *asks the window manager for*, rather than
    mapping it and measuring. Mapping proved unreliable in a test harness --
    an unmapped Toplevel reports 1x1, and a mapped one briefly inherits its
    parent's geometry -- and neither is what we care about. The question is
    "what size does this dialog open at", which is exactly the geometry string
    it sets.

    `_fit_to_content` normally runs on an idle callback that never fires for an
    unmapped window, so it is invoked directly here. It is idempotent.
    """
    window.update_idletasks()
    fit = getattr(window, "_fit_to_content", None)
    if callable(fit):
        fit()
    window.update_idletasks()
    size = window.wm_geometry().split("+")[0]
    width, height = (int(part) for part in size.split("x"))
    return window.winfo_reqwidth(), window.winfo_reqheight(), width, height


def assert_not_shrunk(window, name: str) -> None:
    """A dialog must never open smaller than the size it asked for.

    The fit-to-content pass may only grow a window. It once used
    `winfo_width()` as its floor, which is 1 on an unmapped window, so it
    collapsed the PIN dialog from 700px to a 105px sliver -- "PROTEGE" clipped
    to "OTEGE", buttons half off the edge. `assert_fits` alone did not catch
    that, because the requirement matched the shrunken size perfectly. Only a
    real launch revealed it, which is exactly why this assertion exists.
    """
    declared = getattr(window, "_requested_size", None)
    if declared is None:
        return
    size = window.wm_geometry().split("+")[0]
    width, height = (int(part) for part in size.split("x"))
    assert width >= declared[0] and height >= declared[1], (
        f"{name}: asked for {declared[0]}x{declared[1]} but opens at "
        f"{width}x{height} -- fit-to-content shrank it instead of growing it"
    )


def assert_fits(window, name: str) -> None:
    req_w, req_h, width, height = geometry_of(window)
    assert_not_shrunk(window, name)
    # A little slack: Tk's requested size can exceed the useful size by a few
    # pixels from border and padding rounding.
    assert req_w <= width + 4, (
        f"{name}: needs {req_w}px wide but opens at {width}px -- "
        f"{req_w - width}px of content is off-screen"
    )
    assert req_h <= height + 4, (
        f"{name}: needs {req_h}px tall but opens at {height}px -- "
        f"{req_h - height}px of content is off-screen (this is the 'had to "
        f"resize to reach Save' bug)"
    )


def assert_has_minsize(window, name: str) -> None:
    min_w, min_h = window.minsize()
    assert min_w > 1 and min_h > 1, (
        f"{name}: no minsize, so it can be dragged smaller than its own controls"
    )


# --- every dialog -----------------------------------------------------------


def test_settings_window_fits(root, vault):
    from protege.ui.settings_window import SettingsWindow

    manifest, settings, _, _ = pieces(vault)
    window = SettingsWindow(root, vault, manifest, settings, default_personality(),
                            on_apply=lambda *_: None)
    try:
        assert_fits(window, "SettingsWindow")
        assert_has_minsize(window, "SettingsWindow")
    finally:
        window.destroy()


def test_every_settings_tab_fits(root, vault):
    """Each tab individually -- the notebook only sizes to the active one."""
    from protege.ui.settings_window import SettingsWindow

    manifest, settings, _, _ = pieces(vault)
    window = SettingsWindow(root, vault, manifest, settings, default_personality(),
                            on_apply=lambda *_: None)
    try:
        tabs = window.notebook.tabs()
        for index, tab in enumerate(tabs):
            window.notebook.select(tab)
            window.update_idletasks()
            name = window.notebook.tab(index, "text")
            assert_fits(window, f"Settings tab {name!r}")
    finally:
        window.destroy()


def test_skills_window_fits(root, vault):
    from protege.ui.skills_window import SkillsWindow

    manifest, settings, manager, gate = pieces(vault)
    window = SkillsWindow(root, vault, "default", manifest, settings, manager, gate)
    try:
        assert_fits(window, "SkillsWindow")
        assert_has_minsize(window, "SkillsWindow")
    finally:
        window.destroy()


def test_vault_browser_fits(root, vault):
    from protege.ui.vault_browser import VaultBrowser

    manifest, _, _, _ = pieces(vault)
    window = VaultBrowser(root, vault, manifest, "default")
    try:
        assert_fits(window, "VaultBrowser")
        assert_has_minsize(window, "VaultBrowser")
    finally:
        window.destroy()


def test_unlock_dialog_fits(root, vault):
    from protege.ui.unlock_dialog import UnlockDialog

    manifest, settings, manager, _ = pieces(vault)
    flow = UnlockFlow(vault, manifest, settings, manager, tripwires=TripwireSet.load(vault))
    window = UnlockDialog(root, flow)
    try:
        assert_fits(window, "UnlockDialog")
        assert_has_minsize(window, "UnlockDialog")
    finally:
        window.destroy()


def test_topic_manager_fits(root, vault):
    from protege.ui.unlock_dialog import TopicManagerDialog

    manifest, settings, manager, _ = pieces(vault)
    flow = UnlockFlow(vault, manifest, settings, manager, tripwires=TripwireSet.load(vault))
    window = TopicManagerDialog(root, flow)
    try:
        assert_fits(window, "TopicManagerDialog")
    finally:
        window.destroy()


def test_relock_dialog_fits(root, vault):
    from protege.ui.unlock_dialog import RelockDialog

    manifest, settings, manager, _ = pieces(vault)
    flow = UnlockFlow(vault, manifest, settings, manager, tripwires=TripwireSet.load(vault))
    window = RelockDialog(root, flow, "physics")
    try:
        assert_fits(window, "RelockDialog")
    finally:
        window.destroy()


def test_knowledge_web_fits(root, vault):
    from protege.ui.knowledge_web import KnowledgeWebDialog

    manifest, settings, manager, _ = pieces(vault)
    flow = UnlockFlow(vault, manifest, settings, manager, tripwires=TripwireSet.load(vault))
    window = KnowledgeWebDialog(root, flow)
    try:
        assert_fits(window, "KnowledgeWebDialog")
    finally:
        window.destroy()


def test_memory_panel_fits(root, vault):
    from protege.memory.live import LiveMemory
    from protege.ui.memory_panel import MemoryPanel

    manifest, _, _, gate = pieces(vault)
    memory = LiveMemory(vault, "default", manifest, gate, session_id="s1")
    window = MemoryPanel(root, memory, manifest.unlocked_topics)
    try:
        assert_fits(window, "MemoryPanel")
    finally:
        window.destroy()


def test_pin_dialogs_fit(root):
    from protege.security.pin import hash_pin
    from protege.ui.pin_dialog import PinChangeDialog, PinPromptDialog, PinSetupDialog

    encoded = hash_pin("1234")
    for window, name in (
        (PinSetupDialog(root), "PinSetupDialog"),
        (PinPromptDialog(root, encoded), "PinPromptDialog"),
        (PinChangeDialog(root, encoded), "PinChangeDialog"),
    ):
        try:
            assert_fits(window, name)
        finally:
            window.destroy()


def test_new_trait_dialog_fits(root):
    """Five band boxes plus a form and buttons -- the tallest small dialog."""
    from protege.ui.personality_panel import NewTraitDialog

    window = NewTraitDialog(root, ("directness",))
    try:
        assert_fits(window, "NewTraitDialog")
    finally:
        window.destroy()


def test_attachments_dialog_fits(root):
    from protege.ui.file_dialogs import AttachmentsDialog

    window = AttachmentsDialog(root, [("a.txt", "content")])
    try:
        assert_fits(window, "AttachmentsDialog")
    finally:
        window.destroy()


def test_import_dialog_fits(root, vault):
    from protege.ui.file_dialogs import ImportDialog

    manifest, _, _, _ = pieces(vault)
    window = ImportDialog(root, vault, "default", manifest)
    try:
        assert_fits(window, "ImportDialog")
    finally:
        window.destroy()


def test_document_import_dialog_fits(root, vault):
    from protege.ui.document_import import DocumentImportDialog

    manifest, _, _, _ = pieces(vault)
    window = DocumentImportDialog(root, vault, "default", manifest)
    try:
        assert_fits(window, "DocumentImportDialog")
        assert_has_minsize(window, "DocumentImportDialog")
    finally:
        window.destroy()
