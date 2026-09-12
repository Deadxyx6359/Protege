"""Guidance after a decline, and the streamed-whitespace fix.

Both come from a real session: a user tried to teach a locked topic by
explaining it in the chat, got `[LOCKED: programming_languages]` with no next
step, and reasonably concluded nothing was happening. Conversation genuinely
cannot unlock anything -- that is the security property -- so the UI has to
point at the door that does work.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from akira import store
from akira.chat import BlockDetail, Turn
from akira.projects import ensure_project
from akira.schemas import Manifest, Settings


@pytest.fixture(scope="module")
def app(tmp_path_factory, tk_available):
    """One AkiraWindow for the whole module.

    A AkiraWindow *is* a `tk.Tk`, so building one per test would leave
    several Tcl interpreters alive at once -- a configuration Tk tolerates
    badly, and which failed here with a spurious "tk wasn't installed
    properly" partway through the file. One window, reset between tests.
    """
    from akira.ui.app import AkiraWindow

    vault_path = tmp_path_factory.mktemp("vault")
    store.bootstrap_vault(vault_path)
    ensure_project(vault_path, "default")

    try:
        win = AkiraWindow(
            vault_path, store.load_manifest(vault_path), Settings(),
            store.load_personality(vault_path),
        )
    except tk.TclError:
        if tk_available:
            # Tk works in this process, so this is a real defect.
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


@pytest.fixture
def win(app):
    """The shared window, reset: clean scrollback, locked manifest, no notes.

    The vault is shared along with the window, so notes written by one test
    would otherwise leak into the next -- and the guidance under test reads the
    vault, so that leakage silently changes what it offers.
    """
    app.manifest = Manifest.initial()
    app.scrollback.configure(state="normal")
    app.scrollback.delete("1.0", "end")
    app.scrollback.configure(state="disabled")
    app._stream_marker = None
    app._stream_started = False

    notes = app.vault / "global" / "notes"
    if notes.is_dir():
        for path in notes.glob("*.md"):
            path.unlink()
    return app


def unlock(win, *topics):
    for topic in topics:
        win.manifest = win.manifest.with_unlocked(topic)


def scrollback_text(win) -> str:
    return win.scrollback.get("1.0", "end")


# --- the path a real decline actually takes ---------------------------------


def test_compliant_decline_offers_teaching(win):
    """The case that matters most, and the one the first cut missed.

    When MAIN obeys the directive and replies only `[LOCKED: x]`, the gate
    short-circuits and marks the turn ALLOWED -- a pure decline conveys no
    knowledge. So it lands in the non-blocked branch of `_finish_turn`, and
    guidance hung off `turn.blocked` never ran. This drives the real entry
    point rather than calling `_render_block` directly.
    """
    win._append("Akira\n", "assistant_prefix")
    win._stream_marker = win.scrollback.index("end-1c")
    win._stream_started = False

    turn = Turn(
        user_text="Do you know Python?",
        text="[LOCKED: programming_languages]",
        blocked=False,          # allowed: a compliant decline
    )
    win._finish_turn(turn)
    win.update_idletasks()

    text = scrollback_text(win)
    assert "will not unlock it" in text
    assert "teach programming_languages now" in text


def test_ordinary_reply_gets_no_teaching_offer(win):
    win._finish_turn(Turn(user_text="hi", text="Hello. How may I assist you?", blocked=False))
    win.update_idletasks()
    assert "will not unlock it" not in scrollback_text(win)


def test_reply_merely_mentioning_the_word_locked_is_not_a_decline(win):
    win._finish_turn(
        Turn(user_text="q", text="That file is locked by another process.", blocked=False)
    )
    win.update_idletasks()
    assert "will not unlock it" not in scrollback_text(win)


# --- guidance after a decline -----------------------------------------------


def test_decline_explains_that_chat_cannot_teach(win):
    turn = Turn(
        user_text="Do you know Python?",
        text="[LOCKED: programming_languages]",
        blocked=True,
        detail=BlockDetail(layer="directive", topic="programming_languages"),
    )
    win._render_block(turn)
    text = scrollback_text(win)

    assert "will not unlock it" in text
    assert "topics: [programming_languages]" in text
    assert "teach programming_languages now" in text


def test_guidance_names_the_topic_from_the_marker(win):
    win._render_block(
        Turn(user_text="q", text="[LOCKED: chemistry]", blocked=True,
             detail=BlockDetail(layer="auditor", topic="chemistry"))
    )
    assert "topics: [chemistry]" in scrollback_text(win)


# --- the declined label need not match your tags ----------------------------


def put_note(win, name, topics, body="Voltage is electrical potential difference."):
    path = win.vault / "global" / "notes" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntopics: [%s]\n---\n\n%s\n" % (", ".join(topics), body), encoding="utf-8"
    )
    return path


def test_offers_the_topic_you_actually_have_notes_for(win):
    """From a real session: a note tagged `electronics`, a question about
    voltage, and the model declined with `[LOCKED: physics]` -- its own label
    for the subject. Offering to teach `physics` would point at a topic with no
    notes behind it, which is worse than saying nothing."""
    put_note(win, "dc-basics.md", ["electronics"])
    win._render_block(
        Turn(user_text="what is voltage?", text="[LOCKED: physics]", blocked=True,
             detail=BlockDetail(layer="directive", topic="physics"))
    )
    text = scrollback_text(win)

    assert "'physics' is locked" in text
    assert "model's own guess" in text
    assert "electronics" in text
    assert "teach electronics now" in text


def test_offers_every_locked_topic_that_has_notes(win):
    put_note(win, "dc.md", ["electronics"])
    put_note(win, "org.md", ["chemistry"])
    win._render_block(
        Turn(user_text="q", text="[LOCKED: physics]", blocked=True,
             detail=BlockDetail(layer="directive", topic="physics"))
    )
    text = scrollback_text(win)
    assert "teach chemistry now" in text
    assert "teach electronics now" in text


def test_already_unlocked_topics_are_not_offered(win):
    put_note(win, "dc.md", ["electronics"])
    put_note(win, "py.md", ["programming_languages"])
    unlock(win, "programming_languages")
    win._render_block(
        Turn(user_text="q", text="[LOCKED: physics]", blocked=True,
             detail=BlockDetail(layer="directive", topic="physics"))
    )
    text = scrollback_text(win)
    assert "teach electronics now" in text
    assert "teach programming_languages now" not in text


def test_with_no_notes_at_all_it_falls_back_to_the_declined_name(win):
    win._render_block(
        Turn(user_text="q", text="[LOCKED: physics]", blocked=True,
             detail=BlockDetail(layer="directive", topic="physics"))
    )
    text = scrollback_text(win)
    assert "No notes are tagged with a locked topic yet" in text
    assert "teach physics now" in text


def test_no_guidance_when_the_topic_is_already_unlocked(win):
    """A tripwire false positive on an unlocked topic is a pattern problem, not
    a teaching problem -- pointing at the unlock flow would be wrong advice."""
    unlock(win, "physics")
    win._render_block(
        Turn(user_text="q", text="[LOCKED: physics]", blocked=True,
             detail=BlockDetail(layer="tripwires", topic="physics"))
    )
    text = scrollback_text(win)
    assert "will not unlock it" not in text
    assert "why was this blocked?" in text


def test_block_without_a_marker_gets_no_guidance(win):
    win._render_block(
        Turn(user_text="q", text="[error] the auditor timed out", blocked=True,
             detail=BlockDetail(layer="error", reason="timeout"))
    )
    assert "will not unlock it" not in scrollback_text(win)


def test_block_detail_link_still_present(win):
    win._render_block(
        Turn(user_text="q", text="[LOCKED: chemistry]", blocked=True,
             detail=BlockDetail(layer="auditor", topic="chemistry", reason="flagged"))
    )
    text = scrollback_text(win)
    assert "teach chemistry now" in text
    assert "why was this blocked?" in text


# --- streamed leading whitespace --------------------------------------------


# Events carry the turn id they belong to, so that a stopped turn's late
# output can be dropped by `_drain_events`. These tests inject directly, so
# they have to tag with the window's current id or their tokens are ignored.
def test_leading_blank_tokens_are_suppressed(win):
    """Qwen3's template emits a newline pair around its suppressed reasoning
    block, so every reply began with two blank lines under the label."""
    win._append("Akira\n", "assistant_prefix")
    win._stream_marker = win.scrollback.index("end-1c")
    win._stream_started = False

    for piece in ["\n", "\n", "How may I", " assist you?"]:
        win._events.put(("token", (win._turn_id, piece)))
    win._drain_events()
    win.update_idletasks()

    text = scrollback_text(win)
    assert "Akira\nHow may I assist you?" in text
    assert "Akira\n\n" not in text


def test_internal_blank_lines_are_preserved(win):
    """Only the leading run is trimmed; paragraph breaks inside a reply matter."""
    win._append("Akira\n", "assistant_prefix")
    win._stream_marker = win.scrollback.index("end-1c")
    win._stream_started = False

    for piece in ["\n", "First para.", "\n\n", "Second para."]:
        win._events.put(("token", (win._turn_id, piece)))
    win._drain_events()
    win.update_idletasks()

    assert "First para.\n\nSecond para." in scrollback_text(win)


def test_a_reply_that_is_only_whitespace_prints_nothing(win):
    win._append("Akira\n", "assistant_prefix")
    before = scrollback_text(win)
    win._stream_marker = win.scrollback.index("end-1c")
    win._stream_started = False

    for piece in ["\n", "   ", "\n"]:
        win._events.put(("token", (win._turn_id, piece)))
    win._drain_events()
    win.update_idletasks()

    assert scrollback_text(win) == before
