"""The unlock flow and re-locking."""

from __future__ import annotations

import json

import pytest

from protege.lock.tripwires import TripwireSet
from protege.models import ModelManager, ModelSpec, Role
from protege.models.scripted import ScriptedBackend
from protege.schemas import Manifest, SchemaError, Settings
from protege.store import bootstrap_vault, tripwire_dir
from protege.unlock import (
    UnlockError,
    UnlockFlow,
    available_topics,
    validate_new_topic,
)
from protege.vault import scan_vault


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    bootstrap_vault(root)
    (root / "global" / "notes").mkdir(parents=True, exist_ok=True)
    (root / "projects" / "default" / "memory" / "live").mkdir(parents=True)
    return root


def put_note(vault, rel, topics, body="Photosynthesis converts light into chemical energy."):
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    joined = ", ".join(topics)
    path.write_text(f"---\ntopics: [{joined}]\n---\n\n{body}\n", encoding="utf-8")


def put_tripwires(vault, topic, keywords=()):
    (tripwire_dir(vault) / f"{topic}.json").write_text(
        json.dumps({"topic": topic, "keywords": list(keywords)}), encoding="utf-8"
    )


def make_flow(vault, *, unlocked=(), main_replies=None, auditor_reply="VERDICT: PASS"):
    manifest = Manifest.initial()
    for topic in unlocked:
        manifest = manifest.with_unlocked(topic)
    settings = Settings.from_json(
        {"models": {"main_path": "m.gguf", "auditor_path": "a.gguf", "loading": "concurrent"}}
    )
    replies = main_replies or [
        "These notes explain that plants convert light into chemical energy.",
        "1. What do plants convert light into?\n2. What is the process called?",
        "Chemical energy.",
        "Photosynthesis.",
    ]
    main = ScriptedBackend(ModelSpec(path="m.gguf", role=Role.MAIN), replies=replies)
    auditor = ScriptedBackend(ModelSpec(path="a.gguf", role=Role.AUDITOR), patterns=[(r".*", auditor_reply)])
    manager = ModelManager(settings, factory=lambda s: main if s.role is Role.MAIN else auditor)
    return UnlockFlow(vault, manifest, settings, manager, tripwires=TripwireSet.load(vault)), main


# --- source loading --------------------------------------------------------


def test_demonstration_reads_a_currently_invisible_note(vault):
    # The whole point: the note is locked, so retrieval cannot see it, but the
    # user picked it explicitly and the flow reads it by path.
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, main = make_flow(vault)
    proposal = flow.demonstrate("biology", ["global/notes/bio.md"])
    assert "Photosynthesis converts light" in main.calls[0][1].content
    assert proposal.usable


def test_missing_source_note_is_an_error(vault):
    flow, _ = make_flow(vault)
    with pytest.raises(UnlockError, match="not found"):
        flow.demonstrate("biology", ["global/notes/absent.md"])


def test_no_sources_is_an_error(vault):
    flow, _ = make_flow(vault)
    with pytest.raises(UnlockError, match="at least one"):
        flow.demonstrate("biology", [])


def test_source_outside_the_vault_is_refused(vault):
    flow, _ = make_flow(vault)
    with pytest.raises(UnlockError):
        flow.demonstrate("biology", ["../../../etc/passwd"])


def test_unreadable_source_is_an_error(vault):
    (vault / "global" / "notes" / "bad.md").write_text("---\ntopics: [x\n---\nbody", encoding="utf-8")
    flow, _ = make_flow(vault)
    with pytest.raises(UnlockError, match="could not be read"):
        flow.demonstrate("biology", ["global/notes/bad.md"])


def test_already_unlocked_topic_is_refused(vault):
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, _ = make_flow(vault, unlocked=["biology"])
    with pytest.raises(UnlockError, match="already unlocked"):
        flow.demonstrate("biology", ["global/notes/bio.md"])


# --- the demonstration -----------------------------------------------------


def test_demonstration_produces_summary_and_self_test(vault):
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, _ = make_flow(vault)
    proposal = flow.demonstrate("biology", ["global/notes/bio.md"])
    assert "chemical energy" in proposal.summary
    assert len(proposal.questions) == 2
    assert len(proposal.answers) == 2
    assert "SELF-TEST" in proposal.render()


def test_demonstration_prompts_forbid_outside_knowledge(vault):
    # Judging what the model already knew rather than what the notes say would
    # make the demonstration meaningless.
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, main = make_flow(vault)
    flow.demonstrate("biology", ["global/notes/bio.md"])
    assert "Use ONLY the notes provided" in main.calls[0][0].content


def test_warns_when_source_notes_lack_the_topic_tag(vault):
    # Unlocking from notes that do not carry the topic means retrieval finds
    # nothing afterwards, which looks like the unlock failed.
    put_note(vault, "global/notes/bio.md", ["something_else"])
    flow, _ = make_flow(vault)
    proposal = flow.demonstrate("biology", ["global/notes/bio.md"])
    assert any("not tagged" in w or "tagged" in w for w in proposal.warnings)


def test_demonstration_is_not_blocked_by_the_topic_being_unlocked(vault):
    # The topic under review must be exempt from its own unlock, or no
    # demonstration could ever pass.
    put_tripwires(vault, "biology", keywords=["photosynthesis", "chemical"])
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, _ = make_flow(vault)
    proposal = flow.demonstrate("biology", ["global/notes/bio.md"])
    assert not proposal.blocked


def test_demonstration_wandering_into_another_locked_topic_is_blocked(vault):
    # Exactly one topic is exempt. A demonstration that also explains chemistry
    # is refused and cannot be approved.
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, _ = make_flow(
        vault,
        main_replies=[
            "These notes cover photosynthesis. Incidentally, sodium reacts with water.",
            "1. A question about this?",
            "An answer.",
        ],
    )
    proposal = flow.demonstrate("biology", ["global/notes/bio.md"])
    assert proposal.blocked
    assert "chemistry" in proposal.block_reason or "sodium" in proposal.block_reason
    assert "BLOCKED" in proposal.render()


def test_a_blocked_proposal_cannot_be_approved(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, _ = make_flow(
        vault,
        main_replies=["Photosynthesis, and also sodium reacts with water.", "1. Question?", "Answer."],
    )
    proposal = flow.demonstrate("biology", ["global/notes/bio.md"])
    with pytest.raises(UnlockError, match="cannot be approved"):
        flow.approve(proposal)


# --- approval --------------------------------------------------------------


def test_approval_records_provenance(vault):
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, _ = make_flow(vault)
    proposal = flow.demonstrate("biology", ["global/notes/bio.md"])
    manifest = flow.approve(proposal)
    assert manifest.is_unlocked("biology")
    event = manifest.history[-1]
    assert event.action == "unlock"
    assert event.source_notes == ("global/notes/bio.md",)
    assert event.at


def test_nothing_changes_until_approval(vault):
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, _ = make_flow(vault)
    flow.demonstrate("biology", ["global/notes/bio.md"])
    # Constructing a proposal is inert.
    assert not flow.manifest.is_unlocked("biology")


# --- re-locking ------------------------------------------------------------


def test_relock_removes_the_topic(vault):
    flow, _ = make_flow(vault, unlocked=["biology"])
    manifest = flow.relock("biology")
    assert not manifest.is_unlocked("biology")
    assert manifest.history[-1].action == "relock"


def test_relock_hides_memory_notes_too(vault):
    # Called out in the brief. Nothing has to be *done* to hide them --
    # visibility is computed from the manifest on every scan -- but the effect
    # must actually hold.
    put_note(vault, "projects/default/memory/live/s1.md", ["biology"], "Remembered biology fact.")
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, _ = make_flow(vault, unlocked=["biology"])
    scan = scan_vault(vault)

    assert len(scan.visible(flow.manifest, project="default", retrievable_only=False)) == 2
    relocked = flow.relock("biology")
    assert scan.visible(relocked, project="default", retrievable_only=False) == []


def test_relock_impact_separates_memory_from_knowledge_notes(vault):
    put_note(vault, "global/notes/bio.md", ["biology"])
    put_note(vault, "projects/default/memory/live/s1.md", ["biology"], "A remembered fact.")
    flow, _ = make_flow(vault, unlocked=["biology"])
    impact = flow.relock_impact("biology")
    assert impact.notes == ("global/notes/bio.md",)
    assert impact.memory_notes == ("projects/default/memory/live/s1.md",)
    assert impact.total == 2
    assert "memory note" in impact.describe()


def test_relock_impact_on_an_untouched_topic_is_empty(vault):
    flow, _ = make_flow(vault, unlocked=["biology"])
    assert flow.relock_impact("biology").total == 0


def test_unlock_then_relock_leaves_a_full_audit_trail(vault):
    put_note(vault, "global/notes/bio.md", ["biology"])
    flow, _ = make_flow(vault)
    flow.approve(flow.demonstrate("biology", ["global/notes/bio.md"]))
    flow.relock("biology", note="changed my mind")
    assert [e.action for e in flow.manifest.history] == ["unlock", "relock"]


# --- pickers ---------------------------------------------------------------


def test_available_topics_excludes_already_unlocked(vault):
    put_note(vault, "global/notes/a.md", ["biology"])
    put_note(vault, "global/notes/b.md", ["chemistry"])
    manifest = Manifest.initial().with_unlocked("biology")
    assert available_topics(scan_vault(vault), manifest) == ("chemistry",)


def test_validate_new_topic_rejects_duplicates():
    manifest = Manifest.initial().with_unlocked("biology")
    with pytest.raises(SchemaError, match="already unlocked"):
        validate_new_topic("biology", manifest)


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("Chemistry", "chemistry"),
        ("DC_Basics", "dc_basics"),
        ("DC Basics", "dc_basics"),
        ("DC-Basics", "dc_basics"),
        ("  dc basics  ", "dc_basics"),
        ("#DC Basics", "dc_basics"),
    ],
)
def test_typed_topics_coerce_exactly_like_note_tags(typed, expected):
    """The dialog and note frontmatter must agree on what a name means.

    They used to disagree: `topics: [DC Basics]` in a note coerced happily
    while typing the identical string into the unlock dialog was rejected as a
    malformed id -- one input, two answers, no way to tell which rule applied.
    """
    from protege.vault import coerce_topic

    assert validate_new_topic(typed, Manifest.initial()) == expected
    assert coerce_topic(typed) == expected


@pytest.mark.parametrize("typed", ["", "   ", "!!!", "###"])
def test_unreadable_topic_names_are_still_refused(typed):
    with pytest.raises(SchemaError, match="cannot read"):
        validate_new_topic(typed, Manifest.initial())
