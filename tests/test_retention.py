"""Topics going stale, and what happens when they do.

Until now an unlock was permanent: a topic taught in March was still unlocked
in December and nothing ever asked whether the material had held. For an
application whose whole purpose is pedagogical that is the wrong shape -- it is
a permission system, not a study aid.

The clock is the manifest's own history, so there is no new file to corrupt and
every topic ever unlocked already has a timestamp. These tests pin the two ends
that matter: the arithmetic, and the promise that reporting staleness never
takes anything away by itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from akira.retention import (
    age_of,
    last_demonstrated,
    next_due,
    overdue_for_relock,
    review_queue,
    summarize,
)
from akira.schemas import Manifest, SchemaError, UnlockEvent

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def taught(topic: str, days_ago: int, action: str = "unlock") -> UnlockEvent:
    return UnlockEvent(
        topic=topic, action=action,
        at=(NOW - timedelta(days=days_ago)).isoformat(),
    )


def manifest_with(*events: UnlockEvent, unlocked: tuple[str, ...] = ()) -> Manifest:
    return Manifest(unlocked_topics=tuple(sorted(unlocked)), history=events)


# --- the clock ------------------------------------------------------------------


def test_age_counts_from_the_unlock():
    m = manifest_with(taught("dc_basics", 40), unlocked=("dc_basics",))
    age = age_of(m, "dc_basics", review_after_days=30, now=NOW)
    assert age.days == 40
    assert age.due_in_days == -10
    assert age.is_due


def test_a_review_resets_the_clock():
    """The point of the whole feature: showing it again buys another cycle."""
    m = manifest_with(
        taught("dc_basics", 40),
        taught("dc_basics", 2, action="review"),
        unlocked=("dc_basics",),
    )
    age = age_of(m, "dc_basics", review_after_days=30, now=NOW)
    assert age.days == 2
    assert not age.is_due


def test_the_most_recent_demonstration_wins_whatever_the_order():
    m = manifest_with(
        taught("dc_basics", 2, action="review"),
        taught("dc_basics", 40),
        unlocked=("dc_basics",),
    )
    assert last_demonstrated(m, "dc_basics") == NOW - timedelta(days=2)


def test_a_relock_does_not_count_as_a_demonstration():
    m = manifest_with(
        taught("dc_basics", 40),
        taught("dc_basics", 1, action="relock"),
        unlocked=("dc_basics",),
    )
    assert age_of(m, "dc_basics", review_after_days=30, now=NOW).days == 40


def test_a_timestamp_with_no_zone_is_read_as_utc():
    """Hand-edited or older history must not read as brand new.

    Discarding it would make an ancient topic look freshly taught, which is the
    one direction this is not allowed to fail in.
    """
    m = manifest_with(
        UnlockEvent(topic="dc_basics", action="unlock", at="2026-06-01T12:00:00"),
        unlocked=("dc_basics",),
    )
    age = age_of(m, "dc_basics", review_after_days=30, now=NOW)
    assert age.days == 61 and age.is_due


def test_an_unparseable_timestamp_leaves_the_age_unknown():
    m = manifest_with(
        UnlockEvent(topic="dc_basics", action="unlock", at="not a date"),
        unlocked=("dc_basics",),
    )
    assert age_of(m, "dc_basics", review_after_days=30, now=NOW).days is None


# --- the queue --------------------------------------------------------------------


def test_only_topics_past_the_interval_are_queued():
    m = manifest_with(
        taught("old_one", 60), taught("fresh_one", 3),
        unlocked=("old_one", "fresh_one"),
    )
    assert [a.topic for a in review_queue(m, review_after_days=30, now=NOW)] == ["old_one"]


def test_the_queue_is_oldest_first():
    m = manifest_with(
        taught("a_topic", 40), taught("b_topic", 90), taught("c_topic", 60),
        unlocked=("a_topic", "b_topic", "c_topic"),
    )
    assert [a.topic for a in review_queue(m, review_after_days=30, now=NOW)] == [
        "b_topic", "c_topic", "a_topic"
    ]


def test_a_locked_topic_is_never_queued():
    """It is already behind the gate; there is nothing to lose."""
    m = manifest_with(taught("gone", 90), taught("gone", 1, action="relock"))
    assert review_queue(m, review_after_days=30, now=NOW) == []


def test_unknown_age_sorts_as_due():
    """Unknown is not the same as recent and must not be treated as such."""
    m = manifest_with(
        UnlockEvent(topic="mystery", action="unlock", at=""),
        unlocked=("mystery",),
    )
    assert [a.topic for a in review_queue(m, review_after_days=30, now=NOW)] == ["mystery"]


def test_an_interval_of_zero_disables_the_whole_thing():
    m = manifest_with(taught("ancient", 9999), unlocked=("ancient",))
    assert review_queue(m, review_after_days=0, now=NOW) == []
    assert overdue_for_relock(m, review_after_days=0, grace_days=0, now=NOW) == []


def test_next_due_reports_the_soonest():
    m = manifest_with(
        taught("soon", 25), taught("later", 5),
        unlocked=("soon", "later"),
    )
    upcoming = next_due(m, review_after_days=30, now=NOW)
    assert upcoming.topic == "soon" and upcoming.due_in_days == 5


def test_summarize_names_a_few_and_counts_the_rest():
    m = manifest_with(
        *[taught(f"t{i}_x", 50 + i) for i in range(7)],
        unlocked=tuple(f"t{i}_x" for i in range(7)),
    )
    text = summarize(review_queue(m, review_after_days=30, now=NOW),
                     review_after_days=30)
    assert "7 topic(s) due" in text and "and 3 more" in text


def test_summarize_says_so_when_nothing_is_due():
    assert "Nothing due" in summarize([], review_after_days=30)


# --- auto relock ------------------------------------------------------------------


def test_grace_keeps_a_freshly_due_topic_out_of_the_relock_list():
    """Falling due and being cut off must not happen the same morning."""
    m = manifest_with(taught("dc_basics", 31), unlocked=("dc_basics",))
    assert review_queue(m, review_after_days=30, now=NOW)
    assert overdue_for_relock(m, review_after_days=30, grace_days=14, now=NOW) == []


def test_a_topic_past_the_grace_period_is_listed():
    m = manifest_with(taught("dc_basics", 45), unlocked=("dc_basics",))
    listed = overdue_for_relock(m, review_after_days=30, grace_days=14, now=NOW)
    assert [a.topic for a in listed] == ["dc_basics"]


def test_reporting_staleness_never_changes_access_by_itself():
    """This module reports. Relocking is the caller's decision, always."""
    m = manifest_with(taught("dc_basics", 999), unlocked=("dc_basics",))
    before = m
    review_queue(m, review_after_days=30, now=NOW)
    overdue_for_relock(m, review_after_days=30, grace_days=0, now=NOW)
    next_due(m, review_after_days=30, now=NOW)
    assert m == before and m.is_unlocked("dc_basics")


# --- recording a review -------------------------------------------------------------


def test_with_reviewed_adds_history_and_nothing_else():
    m = Manifest.initial().with_unlocked("dc_basics")
    reviewed = m.with_reviewed("dc_basics", source_notes=("a.md",), note="held up")

    assert reviewed.unlocked_topics == m.unlocked_topics
    assert reviewed.history[-1].action == "review"
    assert reviewed.history[-1].source_notes == ("a.md",)


def test_reviewing_a_locked_topic_is_a_caller_bug():
    with pytest.raises(SchemaError, match="not unlocked"):
        Manifest.initial().with_reviewed("dc_basics")


def test_review_survives_a_save_and_load_round_trip():
    """The clock lives in the history, so the history has to persist it."""
    m = Manifest.initial().with_unlocked("dc_basics").with_reviewed("dc_basics")
    restored = Manifest.from_json(m.to_json())
    assert [e.action for e in restored.history] == ["unlock", "review"]


def test_the_default_settings_are_conservative():
    """Auto-relock off: silently withdrawing access to something the user did
    learn is worse than letting a stale unlock stand."""
    from akira.schemas import Settings

    retention = Settings().retention
    assert retention.enabled is True
    assert retention.auto_relock is False
    assert retention.grace_days > 0


def test_the_settings_window_exposes_retention(clean_root, tmp_path):
    """A setting with no UI is an inert setting."""
    from akira import store
    from akira.personality.defaults import default_personality
    from akira.ui.settings_window import SettingsWindow

    vault = tmp_path / "vault"
    vault.mkdir()
    store.bootstrap_vault(vault)
    from akira.schemas import Settings

    window = SettingsWindow(clean_root, vault, Manifest.initial(), Settings(),
                            default_personality(), on_apply=lambda *_: None)
    try:
        window.update_idletasks()
        tabs = [window.notebook.tab(i, "text") for i in range(len(window.notebook.tabs()))]
        assert "Review" in tabs

        window.retention_relock.set(True)
        window.review_after_days.delete(0, "end")
        window.review_after_days.insert(0, "7")
        collected = window._collect()
        assert collected["retention"]["auto_relock"] is True
        assert collected["retention"]["review_after_days"] == 7
        # And it survives the schema, rather than being dropped on the way out.
        assert Settings.from_json(collected).retention.review_after_days == 7
    finally:
        window.destroy()
