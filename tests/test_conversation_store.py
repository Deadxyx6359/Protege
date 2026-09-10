"""Saving and reloading conversations.

The failure that matters here is silent: a conversation that writes without
error and comes back wrong, or a directory that one bad file makes unreadable.
Both are tested directly.
"""

from __future__ import annotations

import json
import time

import pytest

from protege.core.conversation import Conversation
from protege.core.conversations import (
    ConversationError,
    ConversationStore,
    relative_time,
)


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "conversations")


def a_conversation(title="Squircles", turns=(("user", "hi"), ("assistant", "hello"))):
    conversation = Conversation(title=title)
    for role, text in turns:
        conversation.add(role, text)
    return conversation


# -- round trip --------------------------------------------------------------


def test_a_conversation_survives_a_round_trip(store):
    original = a_conversation()
    store.save(original)

    loaded = store.load(original.id)

    assert loaded.id == original.id
    assert loaded.title == "Squircles"
    assert [(m.role, m.text) for m in loaded.messages] == [
        ("user", "hi"),
        ("assistant", "hello"),
    ]


def test_the_error_flag_survives(store):
    conversation = a_conversation(turns=(("user", "go"),))
    conversation.add("assistant", "out of memory", error=True)
    store.save(conversation)

    loaded = store.load(conversation.id)

    assert loaded.messages[-1].error is True


def test_the_system_prompt_survives(store):
    conversation = a_conversation()
    conversation.system_prompt = "Be terse."
    store.save(conversation)

    assert store.load(conversation.id).system_prompt == "Be terse."


def test_an_empty_streaming_placeholder_is_not_written(store):
    """A placeholder that never received a token is an artefact of streaming."""
    conversation = a_conversation(turns=(("user", "hi"),))
    conversation.add("assistant")  # never filled
    store.save(conversation)

    assert len(store.load(conversation.id).messages) == 1


# -- what should not be saved ------------------------------------------------


def test_a_conversation_with_no_question_is_not_saved(store):
    """Opening the app and closing it should leave nothing behind."""
    store.save(Conversation())
    assert store.list() == []


def test_saving_an_emptied_conversation_removes_the_old_file(store):
    conversation = a_conversation()
    store.save(conversation)
    assert len(store.list()) == 1

    conversation.messages.clear()
    store.save(conversation)

    assert store.list() == []


# -- listing -----------------------------------------------------------------


def test_listing_is_newest_first(store):
    older = a_conversation(title="older")
    store.save(older)
    time.sleep(0.02)
    newer = a_conversation(title="newer")
    store.save(newer)

    assert [s.title for s in store.list()] == ["newer", "older"]


def test_listing_an_absent_directory_is_empty_not_an_error(store):
    assert store.list() == []


def test_one_corrupt_file_does_not_break_the_listing(store):
    """A single bad file must not make the sidebar unbuildable."""
    good = a_conversation(title="fine")
    store.save(good)
    (store.directory / "aabbccdd.json").write_text("{ broken", encoding="utf-8")

    listed = store.list()

    assert [s.title for s in listed] == ["fine"]


def test_listing_respects_the_limit(store):
    for i in range(5):
        store.save(a_conversation(title=f"c{i}"))
    assert len(store.list(limit=3)) == 3


# -- failure modes -----------------------------------------------------------


def test_a_corrupt_file_raises_on_load_rather_than_returning_nonsense(store):
    conversation = a_conversation()
    store.save(conversation)
    (store.directory / f"{conversation.id}.json").write_text("nope", encoding="utf-8")

    with pytest.raises(ConversationError):
        store.load(conversation.id)


def test_loading_something_that_is_not_a_conversation_raises(store):
    store.directory.mkdir(parents=True, exist_ok=True)
    (store.directory / "aabbccdd.json").write_text(json.dumps([1, 2]), encoding="utf-8")

    with pytest.raises(ConversationError):
        store.load("aabbccdd")


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../../etc/passwd",
        "..\\..\\windows\\system32",
        "not-hex",
        "",
        "a" * 200,
        "abcd/efgh",
    ],
)
def test_an_id_that_is_not_an_id_is_refused(store, bad_id):
    """An id reaching the filesystem is a path. Validate, never sanitise."""
    with pytest.raises(ConversationError):
        store.load(bad_id)


def test_deleting_an_invalid_id_is_a_no_op(store):
    store.delete("../../secrets")  # must not raise, must not touch anything
    assert store.list() == []


def test_an_implausibly_large_file_is_refused(store, monkeypatch):
    conversation = a_conversation()
    store.save(conversation)
    monkeypatch.setattr("protege.core.conversations.MAX_BYTES", 4)

    with pytest.raises(ConversationError):
        store.load(conversation.id)


def test_unreadable_message_entries_are_skipped_not_fatal(store):
    conversation = a_conversation(turns=(("user", "keep"),))
    store.save(conversation)

    path = store.directory / f"{conversation.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["messages"].extend([None, {"role": "wizard", "text": "x"}, "junk"])
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = store.load(conversation.id)

    assert [m.text for m in loaded.messages] == ["keep"]


# -- relative time -----------------------------------------------------------


@pytest.mark.parametrize(
    "seconds_ago, expected",
    [(0, "now"), (30, "now"), (60, "1m"), (3599, "59m"), (3600, "1h"), (82800, "23h")],
)
def test_relative_time_below_a_day(seconds_ago, expected):
    now = 1_700_000_000.0
    assert relative_time(now - seconds_ago, now) == expected


def test_relative_time_within_the_week_names_the_day():
    """People remember doing things on Tuesday, not three days ago."""
    now = 1_700_000_000.0
    label = relative_time(now - 3 * 86400, now)
    assert label in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def test_relative_time_beyond_a_week_gives_a_date():
    now = 1_700_000_000.0
    label = relative_time(now - 30 * 86400, now)
    assert any(char.isdigit() for char in label)
    assert label not in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def test_a_future_timestamp_does_not_produce_a_negative_age():
    """Clock skew and daylight saving both make this happen."""
    now = 1_700_000_000.0
    assert relative_time(now + 500, now) == "now"
