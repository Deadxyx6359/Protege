"""The person's changes to their chats: rename, pin, move to a project, delete.

These are what the sidebar's right-click menu and Settings → Chats call.
"""

from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("PySide6", reason="the Qt interface is optional for the old app")

from akira.core.conversation import Conversation  # noqa: E402
from akira.core.conversations import ConversationError, ConversationStore  # noqa: E402

from tests.test_chat_bridge import SlowBackend, make_bridge, model_file, pump_until, qt_app  # noqa: E402,F401

DAY = 86_400


def saved(store, text, *, project="", pinned=False, age_days=0.0):
    """A chat saved \a age_days ago, and its id."""
    chat = Conversation(title=text, project=project, pinned=pinned)
    chat.add("user", text)
    chat.add("assistant", "ok")
    store.save(chat)
    when = time.time() - age_days * DAY
    os.utime(store.directory / f"{chat.id}.json", (when, when))
    return chat.id


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "conversations")


def titles(bridge):
    return [entry["title"] for entry in bridge.recents]


# -- the store ------------------------------------------------------------------


def test_a_pinned_chat_is_listed_first_and_says_so(store):
    saved(store, "new", age_days=0.1)
    saved(store, "old but pinned", pinned=True, age_days=9)
    listed = store.list()
    assert [s.title for s in listed] == ["old but pinned", "new"]
    assert [s.pinned for s in listed] == [True, False]
    assert store.load(listed[0].id).pinned is True


def test_changing_a_chat_keeps_its_place_and_its_messages(store):
    first = saved(store, "first", age_days=0.1)
    saved(store, "second", age_days=0.2)
    store.update(first, title="Renamed", project="p1")

    listed = store.list()
    assert [s.title for s in listed] == ["Renamed", "second"]
    assert listed[0].project == "p1"
    assert [m.text for m in store.load(first).messages] == ["first", "ok"]
    assert abs(listed[0].updated - (time.time() - 0.1 * DAY)) < 5


def test_a_chat_that_is_not_saved_cannot_be_changed(store):
    with pytest.raises(ConversationError):
        store.update("0123456789abcdef", title="x")
    with pytest.raises(ConversationError):
        store.update("../../secrets", title="x")


# -- the bridge -------------------------------------------------------------------


def test_a_chat_is_renamed_where_it_stands(qt_app, make_bridge, store):
    older = saved(store, "older", age_days=2)
    saved(store, "newer", age_days=1)
    bridge = make_bridge(SlowBackend(["x"]))

    assert bridge.renameConversation(older, "  My   garden  plans ") == ""
    assert titles(bridge) == ["newer", "My garden plans"]
    assert store.load(older).title == "My garden plans"


def test_a_chat_needs_a_name_of_sensible_length(qt_app, make_bridge, store):
    chat = saved(store, "keep")
    bridge = make_bridge(SlowBackend(["x"]))
    assert bridge.renameConversation(chat, "   ") == "Give the chat a name."
    assert "at most" in bridge.renameConversation(chat, "x" * 500)
    assert store.load(chat).title == "keep"


def test_a_chat_that_has_gone_says_so(qt_app, make_bridge, store):
    bridge = make_bridge(SlowBackend(["x"]))
    assert bridge.renameConversation("0123456789abcdef", "x") == "That chat is not saved any more."
    assert bridge.pinConversation("not-an-id", True) == "That chat is not saved any more."


def test_renaming_the_open_chat_changes_its_title(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["answer"]))
    bridge.send("first question")
    assert pump_until(lambda: not bridge.busy)

    assert bridge.renameConversation(bridge.conversationId, "Beans") == ""
    assert bridge.title == "Beans"
    assert titles(bridge) == ["Beans"]

    # And the next turn does not put the old name back.
    bridge.send("another")
    assert pump_until(lambda: not bridge.busy)
    assert titles(bridge) == ["Beans"]


def test_the_open_chat_can_be_renamed_before_its_first_reply_is_saved(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["a", "b", "c"], delay=0.05))
    bridge.send("slow question")
    assert bridge.busy

    assert bridge.renameConversation(bridge.conversationId, "Named early") == ""
    assert pump_until(lambda: not bridge.busy)
    assert titles(bridge) == ["Named early"]


def test_an_empty_chat_cannot_be_changed(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["x"]))
    reason = bridge.pinConversation(bridge.conversationId, True)
    assert reason.startswith("Say something in the chat first")
    assert bridge.recents == []


def test_a_pinned_chat_goes_to_the_top(qt_app, make_bridge, store):
    old = saved(store, "old", age_days=5)
    saved(store, "new", age_days=1)
    bridge = make_bridge(SlowBackend(["x"]))

    assert bridge.pinConversation(old, True) == ""
    assert titles(bridge) == ["old", "new"]
    assert [e["pinned"] for e in bridge.recents] == [True, False]

    assert bridge.pinConversation(old, False) == ""
    assert titles(bridge) == ["new", "old"]


def test_a_chat_is_moved_to_another_project(qt_app, make_bridge, store):
    chat = saved(store, "garden", project="home")
    bridge = make_bridge(SlowBackend(["x"]))

    assert bridge.recents[0]["project"] == "home"
    assert bridge.moveConversation(chat, "allotment") == ""
    assert bridge.recents[0]["project"] == "allotment"
    assert store.load(chat).project == "allotment"

    assert bridge.moveConversation(chat, "") == ""
    assert store.load(chat).project == ""


def test_the_open_chat_is_not_moved_while_it_is_answering(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["a", "b", "c"], delay=0.05))
    bridge.send("question")
    assert bridge.moveConversation(bridge.conversationId, "elsewhere") \
        == "Wait for the reply to finish first."
    assert pump_until(lambda: not bridge.busy)
    assert bridge.moveConversation(bridge.conversationId, "elsewhere") == ""
    assert bridge.recents[0]["project"] == "elsewhere"


def test_chosen_chats_are_deleted(qt_app, make_bridge, store):
    one = saved(store, "one", age_days=1)
    two = saved(store, "two", age_days=2)
    saved(store, "three", age_days=3)
    bridge = make_bridge(SlowBackend(["x"]))

    assert bridge.deleteConversations([one, two, "0123456789abcdef"]) == 2
    assert titles(bridge) == ["three"]


def test_deleting_everything_can_spare_the_pinned(qt_app, make_bridge, store):
    saved(store, "keep", pinned=True)
    saved(store, "drop")
    bridge = make_bridge(SlowBackend(["x"]))

    assert bridge.deleteAllConversations(True) == 1
    assert titles(bridge) == ["keep"]
    assert bridge.deleteAllConversations(False) == 1
    assert bridge.recents == []


def test_deleting_everything_clears_the_open_chat(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["answer"]))
    bridge.send("question")
    assert pump_until(lambda: not bridge.busy)

    assert bridge.deleteAllConversations(False) == 1
    assert bridge.messages.rowCount() == 0
    assert bridge.title == "New chat"


def test_old_chats_are_deleted_by_age(qt_app, make_bridge, store):
    saved(store, "recent", age_days=3)
    saved(store, "old", age_days=40)
    saved(store, "old but pinned", pinned=True, age_days=60)
    bridge = make_bridge(SlowBackend(["x"]))

    # Counted first, so the question can say how many.
    assert bridge.countConversations(0, False) == 3
    assert bridge.countConversations(0, True) == 2
    assert bridge.countConversations(30, True) == 1

    assert bridge.deleteConversationsOlderThan(0, False) == 0
    assert bridge.deleteConversationsOlderThan(30, True) == 1
    assert titles(bridge) == ["old but pinned", "recent"]
    assert bridge.deleteConversationsOlderThan(30, False) == 1
    assert titles(bridge) == ["recent"]


def test_the_chat_that_is_answering_is_not_deleted_in_bulk(qt_app, make_bridge, store):
    saved(store, "idle", age_days=1)
    bridge = make_bridge(SlowBackend(["a", "b", "c"], delay=0.05))
    bridge.send("busy one")

    assert bridge.countConversations(0, False) == 1
    assert bridge.deleteAllConversations(False) == 1
    assert pump_until(lambda: not bridge.busy)
    assert titles(bridge) == ["busy one"]
