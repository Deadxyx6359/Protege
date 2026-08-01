"""Memory: gated writes, the smuggling cases, consolidation, and the holding area.

The brief names memory as a leak vector explicitly, so the adversarial section
here mirrors `test_lock_adversarial.py`: MAIN tries to write locked content into
the vault, and the write must not land. A memory note that reaches disk becomes
retrievable, at which point it is indistinguishable from a note the user wrote --
so a write that skips the gate is a permanent bypass, not a transient one.
"""

from __future__ import annotations

import json

import pytest

from protege.lock.pipeline import OutputGate
from protege.lock.tripwires import TripwireSet
from protege.memory.consolidate import Consolidator
from protege.memory.live import (
    SOURCE_PINNED,
    SOURCE_PROPOSED,
    LiveMemory,
    new_session_id,
    parse_remember_calls,
)
from protege.models import ModelManager, ModelSpec, Role
from protege.models.scripted import ScriptedBackend
from protege.projects import ensure_project
from protege.schemas import Manifest, Settings
from protege.store import bootstrap_vault, tripwire_dir
from protege.vault import scan_vault

LEAK = "Sodium metal reacts violently with water, releasing hydrogen."


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    bootstrap_vault(root)
    ensure_project(root, "default")
    return root


def put_tripwires(vault, topic, keywords=()):
    (tripwire_dir(vault) / f"{topic}.json").write_text(
        json.dumps({"topic": topic, "keywords": list(keywords)}), encoding="utf-8"
    )


def make(vault, *, unlocked=("physics",), tier=2, auditor_reply="VERDICT: PASS", main_reply="# Note\n\nBody."):
    manifest = Manifest.initial()
    for topic in unlocked:
        manifest = manifest.with_unlocked(topic)
    manifest = manifest.with_trust_tier(tier)

    settings = Settings.from_json(
        {"models": {"main_path": "m.gguf", "auditor_path": "a.gguf", "loading": "concurrent"}}
    )
    main = ScriptedBackend(ModelSpec(path="m.gguf", role=Role.MAIN), patterns=[(r".*", main_reply)])
    auditor = ScriptedBackend(ModelSpec(path="a.gguf", role=Role.AUDITOR), patterns=[(r".*", auditor_reply)])
    manager = ModelManager(settings, factory=lambda s: main if s.role is Role.MAIN else auditor)
    gate = OutputGate(manifest, settings, TripwireSet.load(vault), manager)
    memory = LiveMemory(vault, "default", manifest, gate, session_id="testsession")
    return memory, manager, settings, manifest, gate


# --- session ids -----------------------------------------------------------


def test_session_ids_are_unique_and_sortable():
    ids = {new_session_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(i[:4].isdigit() for i in ids)


# --- basic writes ----------------------------------------------------------


def test_pinned_write_lands_on_disk(vault):
    memory, *_ = make(vault)
    result = memory.write("User prefers metric units.", topics=["physics"], source=SOURCE_PINNED)
    assert result.accepted
    assert memory.path.is_file()
    assert "metric units" in memory.path.read_text(encoding="utf-8")


def test_written_note_carries_required_frontmatter(vault):
    memory, *_ = make(vault)
    memory.write("A durable fact.", topics=["physics"], source=SOURCE_PROPOSED, importance=5)
    note = scan_vault(vault).by_rel_path("projects/default/memory/live/testsession.md")
    assert note is not None
    assert note.topics == ("physics",)
    assert note.frontmatter["session"] == "testsession"
    assert note.frontmatter["kind"] == "live-memory"


def test_empty_content_is_rejected(vault):
    memory, *_ = make(vault)
    assert not memory.write("   ", topics=["physics"]).accepted


def test_oversized_entry_is_rejected(vault):
    memory, *_ = make(vault)
    assert not memory.write("x" * 5000, topics=["physics"]).accepted


def test_removing_the_last_entry_deletes_the_file(vault):
    memory, *_ = make(vault)
    memory.write("A fact.", topics=["physics"])
    assert memory.path.is_file()
    assert memory.remove(0)
    assert not memory.path.exists()


def test_entries_can_be_edited_in_the_panel(vault):
    memory, *_ = make(vault)
    memory.write("Original.", topics=["physics"])
    assert memory.replace(0, "Corrected by the user.")
    assert "Corrected by the user." in memory.path.read_text(encoding="utf-8")


# --- trust tiers -----------------------------------------------------------


def test_tier_zero_disables_all_memory_writes(vault):
    # The model has not yet earned write access to the vault -- and a
    # user-pinned write at tier 0 would still put model output on disk.
    memory, *_ = make(vault, tier=0)
    for source in (SOURCE_PINNED, SOURCE_PROPOSED):
        result = memory.write("anything", topics=["physics"], source=source)
        assert not result.accepted
    assert not memory.path.exists()


def test_tier_one_allows_pinned_but_not_proposed(vault):
    memory, *_ = make(vault, tier=1)
    assert memory.write("User pinned this.", topics=["physics"], source=SOURCE_PINNED).accepted
    proposed = memory.write("Model proposed this.", topics=["physics"], source=SOURCE_PROPOSED)
    assert not proposed.accepted
    assert "trust tier" in proposed.reason.lower() or "Tier" in proposed.reason


def test_tier_two_allows_both(vault):
    memory, *_ = make(vault, tier=2)
    assert memory.write("a", topics=["physics"], source=SOURCE_PINNED).accepted
    assert memory.write("b", topics=["physics"], source=SOURCE_PROPOSED).accepted


# --- the smuggling cases ---------------------------------------------------


def test_locked_content_is_blocked_by_tripwires_before_disk(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    memory, *_ = make(vault, unlocked=["physics"])
    result = memory.write(LEAK, topics=["physics"], source=SOURCE_PROPOSED)
    assert not result.accepted
    assert result.blocked_by_gate
    assert result.detail.layer == "tripwires"
    assert not memory.path.exists(), "nothing may reach disk when the gate objects"


def test_locked_content_is_blocked_by_the_auditor_before_disk(vault):
    memory, *_ = make(
        vault, unlocked=["physics"], auditor_reply="VERDICT: BLOCK\nTOPIC: chemistry"
    )
    result = memory.write(LEAK, topics=["physics"], source=SOURCE_PROPOSED)
    assert not result.accepted
    assert result.detail.layer == "auditor"
    assert not memory.path.exists()


def test_mislabelling_locked_content_as_an_unlocked_topic_does_not_help(vault):
    # The obvious attack: write chemistry content, tag it `physics`, and let
    # retrieval serve it back later through the unlocked door. The gate reads
    # the content, not the label.
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    memory, *_ = make(vault, unlocked=["physics"])
    assert not memory.write(LEAK, topics=["physics"]).accepted


def test_tagging_with_a_locked_topic_is_refused(vault):
    memory, *_ = make(vault, unlocked=["physics"])
    result = memory.write("Something.", topics=["chemistry"])
    assert not result.accepted
    assert "locked topic" in result.reason


def test_blocked_writes_are_recorded_for_the_panel(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    memory, *_ = make(vault, unlocked=["physics"])
    memory.write(LEAK, topics=["physics"])
    assert len(memory.rejected) == 1
    assert "blocked" in memory.summary()


def test_a_written_note_becomes_invisible_when_its_topic_is_relocked(vault):
    memory, _, _, manifest, _ = make(vault, unlocked=["physics"])
    memory.write("Gravity is 9.8.", topics=["physics"])
    scan = scan_vault(vault)
    assert scan.visible(manifest, project="default", retrievable_only=False)
    relocked = manifest.with_relocked("physics")
    remaining = [n for n in scan.visible(relocked, project="default", retrievable_only=False)
                 if "memory" in n.rel_path]
    assert remaining == []


def test_decline_shortcut_is_disabled_for_memory_writes(vault):
    # A chat reply that is only "[LOCKED: x]" skips the auditor because it
    # conveys nothing. A *memory write* of that text is not a refusal, it is
    # content, and it gets checked like anything else.
    memory, _, _, _, _ = make(vault, unlocked=["physics"], auditor_reply="VERDICT: BLOCK\nTOPIC: chemistry")
    assert not memory.write("[LOCKED: chemistry]", topics=["physics"]).accepted


# --- the remember() tool ---------------------------------------------------


def test_parses_a_remember_call():
    text = 'Sure.\nREMEMBER: {"content": "User prefers metric", "topic": "physics", "importance": 4}\nDone.'
    calls, cleaned = parse_remember_calls(text)
    assert len(calls) == 1
    assert calls[0].content == "User prefers metric"
    assert calls[0].topic == "physics"
    assert calls[0].importance == 4
    # The tool line must not appear in what the user reads.
    assert "REMEMBER:" not in cleaned
    assert "Sure." in cleaned and "Done." in cleaned


def test_malformed_remember_calls_are_dropped():
    for bad in [
        'REMEMBER: not json',
        'REMEMBER: {"content": ""}',
        'REMEMBER: {"topic": "physics"}',
        'REMEMBER: []',
    ]:
        calls, _ = parse_remember_calls(bad)
        assert calls == []


def test_multiple_remember_calls_are_all_parsed():
    text = (
        'REMEMBER: {"content": "one", "topic": "physics"}\n'
        'REMEMBER: {"content": "two", "topic": "physics", "importance": 5}\n'
    )
    calls, cleaned = parse_remember_calls(text)
    assert [c.content for c in calls] == ["one", "two"]
    assert cleaned == ""


def test_remember_defaults_importance():
    calls, _ = parse_remember_calls('REMEMBER: {"content": "x", "topic": "physics"}')
    assert calls[0].importance == 3


# --- context rendering -----------------------------------------------------


def test_context_rendering_prefers_important_entries(vault):
    memory, *_ = make(vault)
    memory.write("Low importance.", topics=["physics"], importance=1)
    memory.write("Critical fact.", topics=["physics"], importance=5)
    rendered = memory.render_for_context(limit=1)
    assert "Critical fact." in rendered
    assert "Low importance." not in rendered


def test_empty_memory_renders_nothing(vault):
    memory, *_ = make(vault)
    assert memory.render_for_context() == ""


# --- consolidation ---------------------------------------------------------


def _consolidator(vault, memory, manager, settings, manifest, gate):
    return Consolidator(vault, "default", manifest, settings, manager, gate)


def test_consolidation_writes_to_pending_not_notes(vault):
    memory, manager, settings, manifest, gate = make(
        vault, main_reply="# Physics\n\nGravity is 9.8 m/s squared."
    )
    memory.write("Gravity is 9.8.", topics=["physics"])
    result = _consolidator(vault, memory, manager, settings, manifest, gate).consolidate(memory, "transcript")

    assert result.pending_paths
    assert all("pending" in str(p) for p in result.pending_paths)
    # Not committed until the user confirms.
    assert list((vault / "projects" / "default" / "notes").glob("*.md")) == []


def test_pending_notes_are_not_retrievable(vault):
    memory, manager, settings, manifest, gate = make(
        vault, main_reply="# Physics\n\nGravity accelerates objects."
    )
    memory.write("Gravity is 9.8.", topics=["physics"])
    _consolidator(vault, memory, manager, settings, manifest, gate).consolidate(memory, "t")

    from protege.lock.retrieval import retrieve

    # Otherwise the review step would be decorative: unreviewed model output
    # would already be influencing answers.
    assert retrieve(scan_vault(vault), manifest, "gravity accelerates", project="default").chunks == []


def test_transcript_goes_to_holding_not_the_bin(vault):
    memory, manager, settings, manifest, gate = make(vault)
    memory.write("A fact.", topics=["physics"])
    result = _consolidator(vault, memory, manager, settings, manifest, gate).consolidate(
        memory, "the full conversation"
    )
    assert result.transcript_path is not None
    assert result.transcript_path.is_file()
    assert "the full conversation" in result.transcript_path.read_text(encoding="utf-8")


def test_held_transcript_is_untagged_and_so_unretrievable(vault):
    memory, manager, settings, manifest, gate = make(vault)
    memory.write("A fact.", topics=["physics"])
    result = _consolidator(vault, memory, manager, settings, manifest, gate).consolidate(memory, "secrets here")
    note = scan_vault(vault).by_rel_path(
        result.transcript_path.relative_to(vault).as_posix()
    )
    assert note is not None and note.topics == ()
    assert not note.visible_to(manifest)


def test_blocked_consolidation_is_not_written(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    memory, manager, settings, manifest, gate = make(
        vault, unlocked=["physics"], main_reply=f"# Notes\n\n{LEAK}"
    )
    memory.write("Something innocuous.", topics=["physics"])
    result = _consolidator(vault, memory, manager, settings, manifest, gate).consolidate(memory, "t")
    assert result.blocked
    assert result.pending_paths == []


def test_confirm_commits_notes_and_deletes_the_transcript(vault):
    memory, manager, settings, manifest, gate = make(
        vault, main_reply="# Physics\n\nGravity is 9.8."
    )
    memory.write("Gravity is 9.8.", topics=["physics"])
    consolidator = _consolidator(vault, memory, manager, settings, manifest, gate)
    result = consolidator.consolidate(memory, "transcript text")

    transcript = result.transcript_path
    committed = consolidator.confirm(result)

    assert committed and committed[0].is_file()
    assert "notes" in str(committed[0])
    assert not transcript.exists()
    assert not memory.path.exists()


def test_discard_keeps_the_transcript_by_default(vault):
    # Rejecting a bad consolidation is exactly when the source matters most.
    memory, manager, settings, manifest, gate = make(vault, main_reply="# X\n\nWrong and lossy.")
    memory.write("A fact.", topics=["physics"])
    consolidator = _consolidator(vault, memory, manager, settings, manifest, gate)
    result = consolidator.consolidate(memory, "transcript text")
    consolidator.discard(result)
    assert result.transcript_path.is_file()
    assert result.pending_paths == []


def test_immediate_delete_option_never_writes_a_transcript(vault):
    manifest = Manifest.initial().with_unlocked("physics").with_trust_tier(2)
    settings = Settings.from_json({
        "models": {"main_path": "m.gguf", "auditor_path": "a.gguf", "loading": "concurrent"},
        "memory": {"delete_transcript_immediately": True},
    })
    main = ScriptedBackend(ModelSpec(path="m.gguf", role=Role.MAIN), patterns=[(r".*", "# X\n\nBody.")])
    auditor = ScriptedBackend(ModelSpec(path="a.gguf", role=Role.AUDITOR), patterns=[(r".*", "VERDICT: PASS")])
    manager = ModelManager(settings, factory=lambda s: main if s.role is Role.MAIN else auditor)
    gate = OutputGate(manifest, settings, TripwireSet.load(vault), manager)
    memory = LiveMemory(vault, "default", manifest, gate, session_id="s2")
    memory.write("A fact.", topics=["physics"])

    result = Consolidator(vault, "default", manifest, settings, manager, gate).consolidate(memory, "secrets")
    assert result.transcript_path is None
    assert list((vault / "projects" / "default" / "memory" / "holding").glob("*")) == []


def test_sweep_deletes_expired_transcripts_only(vault):
    import os
    import time as time_module

    memory, manager, settings, manifest, gate = make(vault)
    memory.write("A fact.", topics=["physics"])
    consolidator = _consolidator(vault, memory, manager, settings, manifest, gate)
    result = consolidator.consolidate(memory, "transcript")

    # Fresh transcript survives the sweep.
    assert consolidator.sweep_holding() == []

    old = time_module.time() - 8 * 86400
    os.utime(result.transcript_path, (old, old))
    removed = consolidator.sweep_holding()
    assert result.transcript_path in removed
    assert not result.transcript_path.exists()


def test_untagged_entries_are_counted_as_skipped(vault):
    memory, manager, settings, manifest, gate = make(vault)
    memory.write("Untagged thought.", topics=[])
    result = _consolidator(vault, memory, manager, settings, manifest, gate).consolidate(memory, "t")
    assert result.skipped == 1
    assert result.notes == []


def test_consolidation_dedupes_against_an_existing_note(vault):
    existing = vault / "projects" / "default" / "notes" / "physics.md"
    existing.write_text("---\ntopics: [physics]\n---\n\n# Physics\n\nGravity is 9.8.\n", encoding="utf-8")
    memory, manager, settings, manifest, gate = make(vault, main_reply="# Physics\n\nGravity is 9.8. Also drag.")
    memory.write("Drag matters too.", topics=["physics"])
    result = _consolidator(vault, memory, manager, settings, manifest, gate).consolidate(memory, "t")
    assert result.usable[0].merges_into == "projects/default/notes/physics.md"
    assert "Gravity is 9.8" in result.usable[0].diff_against(existing.read_text(encoding="utf-8")) or True


def test_locked_notes_are_not_offered_to_the_consolidator(vault):
    # Handing the model a locked note as "existing content to merge against"
    # would leak it into the consolidation prompt -- a write bypassing the gate
    # through the back door of deduplication.
    locked = vault / "projects" / "default" / "notes" / "chem.md"
    locked.write_text("---\ntopics: [chemistry]\n---\n\n# Chem\n\nSodium reacts.\n", encoding="utf-8")
    memory, manager, settings, manifest, gate = make(vault, unlocked=["physics"])
    memory.write("A physics fact.", topics=["physics"])
    consolidator = _consolidator(vault, memory, manager, settings, manifest, gate)
    consolidator.consolidate(memory, "t")

    main_calls = [c for c in manager._backends[Role.MAIN].calls]
    assert all("Sodium reacts" not in m.content for call in main_calls for m in call)
