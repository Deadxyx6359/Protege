"""Stopping a turn, and the keys that were missing.

A generation on a 24B takes minutes. Before this there was no way to stop one:
the Send button greyed out, `activity.stop()` only halted an animation, and the
only escape was closing the window. These tests pin the behaviour that replaced
it, including the awkward part -- a thread cannot be killed, so a turn already
inside the auditor keeps running and its result has to be *discarded* rather
than prevented.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from akira import store
from akira.chat import Turn, TurnCancelled
from akira.projects import ensure_project
from akira.schemas import Settings


@pytest.fixture(scope="module")
def app(tmp_path_factory, tk_available):
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
    app.scrollback.configure(state="normal")
    app.scrollback.delete("1.0", "end")
    app.scrollback.configure(state="disabled")
    app._set_busy(False)
    app._cancelled.clear()
    app._stream_marker = None
    app._stream_started = False
    app._last_user_text = ""
    return app


def text_of(win) -> str:
    return win.scrollback.get("1.0", "end")


def begin_turn(win, prompt: str = "explain thevenin") -> int:
    """Put the window into the state `_on_send` leaves it in, without a model."""
    win._last_user_text = prompt
    win._set_busy(True)
    win._append("Akira\n", "assistant_prefix")
    win._stream_marker = win.scrollback.index("end-1c")
    win._stream_started = False
    win._cancelled.clear()
    win._turn_id += 1
    return win._turn_id


# --- the button ---------------------------------------------------------------


def test_send_becomes_stop_while_busy(win):
    """A disabled button says "wait". Nothing said "you may stop this"."""
    assert win.send_button.cget("text") == "Send"
    win._set_busy(True)
    assert win.send_button.cget("text") == "Stop"
    win._set_busy(False)
    assert win.send_button.cget("text") == "Send"


def test_the_stop_button_is_clickable_while_busy(win):
    """It used to be `state=disabled`, which is what made this unfixable."""
    win._set_busy(True)
    assert str(win.send_button.cget("state")) != "disabled"


# --- stopping -----------------------------------------------------------------


def test_stop_clears_busy_and_says_so(win):
    begin_turn(win)
    win._append("half an ans", "assistant")
    win._stop()

    assert not win._busy
    assert "[stopped]" in text_of(win)
    assert "half an ans" not in text_of(win), "the partial draft was left on screen"


def test_stop_sets_the_flag_the_callbacks_read(win):
    """Cancellation is cooperative -- this flag is the whole mechanism."""
    begin_turn(win)
    win._stop()
    assert win._cancelled.is_set()


def test_stop_does_nothing_when_idle(win):
    before = text_of(win)
    win._stop()
    assert text_of(win) == before


def test_a_stopped_turn_leaves_the_conversation_untouched(win):
    """`_finish_turn` never runs, so the model sees no trace of it next time."""
    before = len(win.conversation.messages)
    begin_turn(win)
    win._append("partial", "assistant")
    win._stop()
    assert len(win.conversation.messages) == before


def test_late_output_from_a_stopped_turn_is_discarded(win):
    """The uninterruptible case.

    A turn already inside the auditor cannot be interrupted -- there is no way
    to kill the thread -- so it runs to completion and delivers a Turn. That
    result must not appear on screen minutes after the user stopped it.
    """
    turn_id = begin_turn(win)
    win._stop()

    win._events.put(("token", (turn_id, "text from the dead turn")))
    win._events.put(("done", (turn_id, Turn(user_text="q", text="a full answer"))))
    win._drain_events()
    win.update_idletasks()

    body = text_of(win)
    assert "text from the dead turn" not in body
    assert "a full answer" not in body
    assert not win._busy


def test_output_from_the_current_turn_still_arrives(win):
    """The discard must key on the turn id, not on having ever stopped."""
    turn_id = begin_turn(win)
    win._events.put(("token", (turn_id, "live text")))
    win._drain_events()
    win.update_idletasks()
    assert "live text" in text_of(win)


def test_a_second_turn_is_not_blocked_by_the_first_being_stopped(win):
    first = begin_turn(win)
    win._stop()
    second = begin_turn(win)
    assert second != first
    win._events.put(("token", (second, "the new answer")))
    win._drain_events()
    win.update_idletasks()
    assert "the new answer" in text_of(win)


# --- the callbacks --------------------------------------------------------------


def test_the_token_callback_raises_once_cancelled(win):
    """What actually unwinds llama.cpp's stream."""
    win._cancelled.set()
    captured = {}

    def fake_respond(_text, _conv, *, on_token, on_stage):
        try:
            on_token("x")
        except TurnCancelled:
            captured["token"] = True
        try:
            on_stage("auditing")
        except TurnCancelled:
            captured["stage"] = True
        raise TurnCancelled()

    original = win.responder.respond
    win.responder.respond = fake_respond
    try:
        win._run_turn("q", win._turn_id)
    finally:
        win.responder.respond = original

    assert captured.get("token"), "a cancelled turn kept streaming tokens"
    assert captured.get("stage"), (
        "stage boundaries must also raise, so Stop during MAIN aborts before "
        "the auditor -- the slow phase -- is ever started"
    )


def test_a_cancelled_turn_queues_no_error(win):
    """Stopping is not a failure and must not print one."""
    win._cancelled.set()

    def fake_respond(_text, _conv, *, on_token, on_stage):
        raise TurnCancelled()

    original = win.responder.respond
    win.responder.respond = fake_respond
    try:
        win._run_turn("q", win._turn_id)
    finally:
        win.responder.respond = original

    win._drain_events()
    assert "[error]" not in text_of(win)


# --- shortcuts ------------------------------------------------------------------


def test_up_arrow_recalls_the_last_message_only_when_empty(win):
    win._last_user_text = "explain thevenin"
    win.input.delete("1.0", "end")
    assert win._recall_last(None) == "break"
    assert win.input.get("1.0", "end-1c") == "explain thevenin"

    # With a draft in progress, Up is cursor movement and must stay that way.
    win.input.delete("1.0", "end")
    win.input.insert("1.0", "a draft I am writing")
    assert win._recall_last(None) is None
    assert win.input.get("1.0", "end-1c") == "a draft I am writing"


def test_regenerate_does_nothing_without_a_previous_message(win):
    win._last_user_text = ""
    before = text_of(win)
    win._regenerate()
    assert text_of(win) == before


def test_regenerate_is_inert_while_busy(win):
    win._last_user_text = "q"
    win._set_busy(True)
    before = text_of(win)
    win._regenerate()
    assert text_of(win) == before


def test_shortcuts_are_inert_while_a_modal_has_the_grab(win):
    """`bind_all` binds application-wide, dialogs included.

    Without the guard, Ctrl+N pressed over the Settings window would start a
    new session behind the modal -- invisibly, since the dialog keeps focus.
    """
    calls = []
    handler = win._only_when_unobstructed(lambda: calls.append(1))

    handler(None)
    assert calls == [1]

    dialog = tk.Toplevel(win)
    dialog.grab_set()
    try:
        handler(None)
        assert calls == [1], "a shortcut fired while a modal dialog was up"
    finally:
        dialog.grab_release()
        dialog.destroy()


def test_every_bound_shortcut_names_a_real_method(win):
    """A typo in a binding is silent until the day someone presses the key."""
    for name in ("_stop", "_new_session", "_regenerate", "_knowledge_web",
                 "_show_settings"):
        assert callable(getattr(win, name, None)), name
