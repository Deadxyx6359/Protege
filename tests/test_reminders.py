"""Reminders asked for in the chat, set on the person's yes."""

from __future__ import annotations

from datetime import datetime

import pytest

from akira.core import reminders

MONDAY = datetime(2026, 9, 28, 14, 30)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.mark.parametrize("text, what, when", [
    ("remind me to call mum tomorrow at 9", "call mum", "tomorrow at 09:00"),
    ("Remind me in 20 minutes to take the bread out", "take the bread out",
     "in 20 minutes, at 14:50"),
    ("can you remind me at 5 to phone the shop", "phone the shop", "today at 17:00"),
    ("remind me about the dentist on Friday at 3pm", "the dentist", "Friday at 15:00"),
    ("set a reminder for tonight: water the plants", "water the plants", "today at 20:00"),
    ("remind me to stretch at 17:30", "stretch", "today at 17:30"),
    ("remind me this evening to call Sam", "call Sam", "today at 18:00"),
    ("Remind me at noon to eat", "eat", "tomorrow at 12:00"),
    ("remind me in half an hour to check the oven", "check the oven", "in 30 minutes, at 15:00"),
    ("remind me next monday morning to pay rent", "pay rent", "5 Oct at 09:00"),
])
def test_what_and_when_are_read_as_said(text, what, when):
    asked = reminders.read(text, MONDAY)
    assert asked.what == what
    assert reminders.described(asked.when, MONDAY) == when


def test_no_time_said_is_no_time_guessed():
    assert reminders.read("remind me to buy milk", MONDAY).when is None
    assert reminders.read("remind me at 25:00 to x", MONDAY).when is None


@pytest.mark.parametrize("text, asks", [
    ("Remind me to feed the cat", True), ("Could you remind me at 5?", True),
    ("Set a reminder for Friday", True), ("What should I remember to pack?", False),
    ("Did you remind me yesterday?", False),
])
def test_only_a_request_for_a_reminder_is_one(text, asks):
    assert reminders.asks(text) is asks


@pytest.mark.parametrize("text, answer", [
    ("yes", "yes"), ("Yes please", "yes"), ("ok", "yes"), ("no", "no"), ("no thanks", "no"),
    ("cancel that", "no"), ("what time is it", ""),
    ("yes, and also tell me about the history of the Roman empire please", ""),
])
def test_yes_and_no(text, answer):
    assert reminders.answer(text) == answer


# -- in the chat ---------------------------------------------------------------------------------


qt = pytest.importorskip("PySide6", reason="the Qt interface is optional")


@pytest.fixture
def chat(tmp_path):
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    from akira.core.config import AppConfig
    from akira.core.conversations import ConversationStore
    from akira.core.models import ModelRouter
    from akira.ui.bridge import ChatBridge

    set_ = []
    allowed = {"notices": True}
    config = AppConfig(models={})
    bridge = ChatBridge(ModelRouter(config), config, ConversationStore(tmp_path / "chats"),
                        remind=lambda what, at: set_.append((what, at)) or "",
                        notices=lambda: allowed["notices"])
    spoken = []
    bridge.replyEnded.connect(spoken.append)
    return bridge, set_, allowed, spoken


def last(bridge):
    model = bridge.messages
    return model.data(model.index(model.rowCount() - 1, 0), model.TextRole)


def test_a_reminder_is_offered_and_set_on_yes(chat):
    bridge, set_, _, spoken = chat
    bridge.send("remind me to call mum tomorrow at 9")
    assert not bridge.busy and set_ == []
    assert last(bridge).startswith("Set a reminder for tomorrow at 09:00: call mum?")
    assert spoken == [last(bridge)], "a call would not hear the question"
    bridge.send("yes")
    ((what, at),) = set_
    assert what == "call mum"
    assert datetime.fromtimestamp(at).strftime("%H:%M") == "09:00"
    assert last(bridge).startswith("Done. I'll remind you tomorrow at 09:00")


def test_no_sets_nothing_and_anything_else_is_a_new_message(chat):
    bridge, set_, _, _ = chat
    bridge.send("remind me to stretch in 10 minutes")
    bridge.send("no")
    assert set_ == [] and last(bridge) == "All right, no reminder."
    bridge.send("remind me to stretch in 10 minutes")
    bridge.send("What is the capital of France?")
    assert set_ == [] and "No model is configured" in last(bridge)
    bridge.send("yes")
    assert set_ == [], "a yes after the reminder was let go set it anyway"


def test_with_no_time_it_asks_when(chat):
    bridge, set_, _, _ = chat
    bridge.send("remind me to buy milk")
    assert last(bridge).startswith("When should I remind you to buy milk?")
    bridge.send("at 5pm")
    assert "buy milk?" in last(bridge)
    bridge.send("ok")
    assert [what for what, _ in set_] == ["buy milk"]


def test_it_says_when_notices_are_not_allowed(chat):
    bridge, _, allowed, _ = chat
    allowed["notices"] = False
    bridge.send("remind me to call Sam in an hour")
    assert "Notices are not allowed yet" in last(bridge)


def test_in_the_app_a_yes_makes_a_notice_job():
    from akira.ui.shell import build_context
    ctx = build_context(persist=False)
    try:
        ctx.chat.send("remind me to water the plants in 20 minutes")
        ctx.chat.send("yes")
        (job,) = [j for j in ctx.scheduler.jobs() if j.name.startswith("Reminder")]
        assert job.action == "notify" and job.arguments["text"] == "water the plants"
        assert [g.capability for g in job.grants] == ["notify.send"]
    finally:
        ctx.close()
