"""File attach/import, the theme, and the rain -- the additions the user asked for.

The attach path's one security-relevant property is tested here explicitly:
attachments enter the prompt, but MAIN's *output* about them still passes the
gate, so an attached file cannot be used to launder locked knowledge out.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from akira.context.assembly import ContextAssembler
from akira.personality.defaults import default_personality
from akira.schemas import Manifest, Settings
from akira.ui.file_dialogs import MAX_ATTACH_BYTES, FileReadError, read_text_file


def words(text: str) -> int:
    return len(text.split())


def _manifest(*unlocked):
    manifest = Manifest.initial()
    for topic in unlocked:
        manifest = manifest.with_unlocked(topic)
    return manifest


# --- read_text_file ---------------------------------------------------------


def test_reads_utf8(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("héllo wörld", encoding="utf-8")
    name, content = read_text_file(path)
    assert name == "note.txt"
    assert content == "héllo wörld"


def test_reads_utf8_with_bom(tmp_path):
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbfhello")
    _, content = read_text_file(path)
    assert content == "hello"


def test_reads_cp1252_fallback(tmp_path):
    # Windows-authored text is often cp1252; the user should not have to
    # re-save their own notes in another editor.
    path = tmp_path / "legacy.txt"
    path.write_bytes("café résumé".encode("cp1252"))
    _, content = read_text_file(path)
    assert "café" in content


def test_rejects_binary(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG\x00\x00garbage")
    with pytest.raises(FileReadError, match="binary"):
        read_text_file(path)


def test_rejects_oversized(tmp_path):
    path = tmp_path / "huge.txt"
    path.write_bytes(b"a" * (MAX_ATTACH_BYTES + 1))
    with pytest.raises(FileReadError, match="MB"):
        read_text_file(path)


def test_rejects_empty(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n", encoding="utf-8")
    with pytest.raises(FileReadError, match="empty"):
        read_text_file(path)


def test_rejects_missing(tmp_path):
    with pytest.raises(FileReadError):
        read_text_file(tmp_path / "absent.txt")


# --- attachments in context assembly ----------------------------------------


def _assemble(assembler, **kwargs):
    base = dict(
        manifest=_manifest("physics"),
        personality=default_personality(),
        user_text="what does the file say?",
    )
    base.update(kwargs)
    return assembler.assemble(**base)


def test_attachment_enters_the_prompt():
    assembler = ContextAssembler(Settings(), words)
    result = _assemble(assembler, attached_files=[("notes.txt", "The measured value was 42.")])
    assert "FILES THE USER ATTACHED:" in result.system_prompt
    assert "[attached file: notes.txt]" in result.system_prompt
    assert "The measured value was 42." in result.system_prompt


def test_attachment_sits_between_project_doc_and_retrieved_notes():
    assembler = ContextAssembler(Settings(), words)
    result = _assemble(
        assembler,
        project_doc="# Project\n\nContext here.",
        attached_files=[("f.txt", "Attached content.")],
    )
    prompt = result.system_prompt
    assert prompt.index("PROJECT CONTEXT:") < prompt.index("FILES THE USER ATTACHED:")
    # The directive still ends the prompt, attachments or not.
    assert prompt.rstrip().endswith("the list above still governs.")


def test_attachment_truncation_is_announced():
    settings = Settings.from_json({"context": {"total_budget_tokens": 512, "reserve_for_response": 64}})
    assembler = ContextAssembler(settings, words)
    result = _assemble(assembler, attached_files=[("big.txt", "word " * 2000)])
    section = result.section("attached files")
    assert section is not None and section.truncated
    assert any("big.txt" in n for n in result.notices)


def test_attachment_that_fits_nothing_is_reported_dropped():
    settings = Settings.from_json({"context": {"total_budget_tokens": 512, "reserve_for_response": 64}})
    assembler = ContextAssembler(settings, words)
    result = _assemble(
        assembler,
        user_text="x " * 300,
        attached_files=[("a.txt", "word " * 500)],
    )
    section = result.section("attached files")
    assert section is not None
    assert section.dropped_items >= 1 or section.truncated


def test_no_attachments_means_no_section_text():
    assembler = ContextAssembler(Settings(), words)
    result = _assemble(assembler)
    assert "FILES THE USER ATTACHED:" not in result.system_prompt


def test_attached_content_does_not_bypass_the_output_gate(tmp_path):
    """The property that makes attach safe to ship.

    A user attaches a file about a locked topic (their right -- it is their
    file). MAIN's *reply* quoting it is model output and still passes the
    tripwires: the gate reads content, not provenance.
    """
    import json

    from akira.lock.pipeline import PipelineResponder
    from akira.chat import Conversation
    from akira.models import ModelManager, ModelSpec, Role
    from akira.models.scripted import ScriptedBackend
    from akira.store import bootstrap_vault, tripwire_dir

    vault = tmp_path / "vault"
    vault.mkdir()
    bootstrap_vault(vault)
    (tripwire_dir(vault) / "chemistry.json").write_text(
        json.dumps({"topic": "chemistry", "keywords": ["sodium"]}), encoding="utf-8"
    )
    settings = Settings.from_json(
        {"models": {"main_path": "m.gguf", "auditor_path": "a.gguf", "loading": "concurrent"}}
    )
    leak = "As your file says, sodium reacts violently with water."
    main = ScriptedBackend(ModelSpec(path="m.gguf", role=Role.MAIN), patterns=[(r".*", leak)])
    auditor = ScriptedBackend(ModelSpec(path="a.gguf", role=Role.AUDITOR), patterns=[(r".*", "VERDICT: PASS")])
    manager = ModelManager(settings, factory=lambda s: main if s.role is Role.MAIN else auditor)

    responder = PipelineResponder(
        vault,
        Manifest.initial().with_unlocked("physics").with_trust_tier(2),
        settings,
        default_personality(),
        manager,
        attachments=lambda: [("chem-notes.txt", "sodium + water = boom")],
    )
    turn = responder.respond("summarize my file", Conversation())
    assert turn.blocked
    assert turn.detail.layer == "tripwires"
    assert "sodium" not in turn.text


# --- theme ------------------------------------------------------------------


def test_palette_has_no_duplicate_meanings():
    from akira.ui import theme

    # Ground, prose, and accent must be distinct or the theme collapses.
    assert len({theme.BG, theme.FG, theme.PURPLE, theme.DANGER}) == 4


def test_widgets_reexport_the_theme_palette():
    from akira.ui import theme, widgets

    assert widgets.WARNING_BG == theme.WARNING_BG
    assert widgets.DANGER_FG == theme.DANGER
    assert widgets.MUTED_FG == theme.FG_DIM


def test_no_stray_hex_literals_outside_theme():
    """Every color lives in theme.py; a second source of truth is drift."""
    import re
    from pathlib import Path

    ui_dir = Path(__file__).resolve().parent.parent / "akira" / "ui"
    offenders = []
    for path in ui_dir.glob("*.py"):
        if path.name == "theme.py":
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r'"#[0-9a-fA-F]{6}"', line):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)


def test_font_families_resolve_without_a_root():
    from akira.ui import theme

    assert theme.font_family() in theme.MONO_CANDIDATES
    assert theme.ui_family() in theme.UI_CANDIDATES


def test_ui_and_mono_are_separate_roles():
    """Interface prose in a terminal face is what made the first cut look
    'low res and old'. Mono is reserved for chat, rain and wordmarks."""
    from akira.ui import theme

    assert theme.MONO_CANDIDATES[0] != theme.UI_CANDIDATES[0]
    assert "Segoe UI" in theme.UI_CANDIDATES


# --- Tk-dependent smoke (skipped without a display) --------------------------


@pytest.fixture
def root(clean_root):
    """The shared session-wide Tk interpreter (see conftest.py).

    Not a fresh `tk.Tk()` per module: several live interpreters in one process
    made Tk fail intermittently, and the fixture's TclError handler turned that
    into a silent skip of the whole module.
    """
    return clean_root


def test_theme_install_sets_the_option_database(root):
    label = tk.Label(root)
    from akira.ui import theme

    assert str(label.cget("background")) == theme.BG
    assert str(label.cget("foreground")) == theme.FG
    label.destroy()


def test_rain_canvas_starts_and_stops(root):
    from akira.ui.rain import RainCanvas

    rain = RainCanvas(root, width=80)
    rain.pack()
    rain.start()
    root.update_idletasks()
    # Force geometry so columns build, then let one tick run.
    rain.event_generate("<Configure>")
    root.update()
    rain.stop()
    assert rain._after_id is None
    rain.destroy()


def test_rain_rebuild_preserves_embedded_windows(root):
    from akira.ui.rain import RainCanvas

    rain = RainCanvas(root, width=200, height=200)
    rain.pack()
    inner = tk.Frame(rain)
    item = rain.create_window(100, 100, window=inner)
    root.update_idletasks()
    rain._built_for = (0, 0)  # force a rebuild
    rain.event_generate("<Configure>")
    root.update_idletasks()
    # The glyph rebuild must not have deleted the embedded window item.
    assert item in rain.find_all()
    rain.destroy()


def test_themed_scrolled_text_uses_a_ttk_scrollbar(root):
    from tkinter import ttk

    from akira.ui.widgets import ThemedScrolledText

    widget = ThemedScrolledText(root, height=4)
    widget.pack()
    assert isinstance(widget.vbar, ttk.Scrollbar)
    widget.destroy()


def test_modal_dialog_transient_flag(root):
    from akira.ui.widgets import ModalDialog

    transient = ModalDialog(root, "t")
    non_transient = ModalDialog(root, "n", transient=False)
    root.update_idletasks()
    # Tk reports the master path for transients, empty string otherwise.
    assert transient.wm_transient()
    assert not non_transient.wm_transient()
    transient.destroy()
    non_transient.destroy()


def test_pin_dialogs_declare_initial_focus(root):
    from akira.security.pin import hash_pin
    from akira.ui.pin_dialog import PinPromptDialog, PinSetupDialog

    setup = PinSetupDialog(root)
    assert setup.initial_focus is setup.first
    setup.destroy()

    prompt = PinPromptDialog(root, hash_pin("1234"))
    assert prompt.initial_focus is prompt.entry
    prompt.destroy()
