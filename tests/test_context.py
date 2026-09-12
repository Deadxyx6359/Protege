"""Context assembly, token budgeting, and personality prompt rules."""

from __future__ import annotations

import pytest

from akira.chat import Conversation
from akira.context.assembly import ContextAssembler, estimate_tokens, truncate_to_tokens
from akira.lock.retrieval import RetrievalResult, retrieve
from akira.personality.defaults import default_personality
from akira.personality.prompt import active_traits, build_personality_prompt
from akira.projects import ensure_project, slugify, validate_name
from akira.schemas import Manifest, Personality, PersonalityProfile, SchemaError, Settings, Trait
from akira.vault import scan_vault


def words(text: str) -> int:
    """A token counter that is easy to reason about in assertions."""
    return len(text.split())


def _settings(**context):
    return Settings.from_json({"context": context} if context else {})


def _manifest(*unlocked):
    manifest = Manifest.initial()
    for topic in unlocked:
        manifest = manifest.with_unlocked(topic)
    return manifest


def _assemble(assembler, **kwargs):
    base = dict(
        manifest=_manifest("physics"),
        personality=Personality(),
        user_text="what is gravity?",
    )
    base.update(kwargs)
    return assembler.assemble(**base)


# --- personality prompt rules ----------------------------------------------


def test_all_neutral_personality_contributes_nothing():
    # A fresh install adds zero personality text. The baseline behavior is the
    # model's own; everything on top is something the user chose.
    prompt = build_personality_prompt(default_personality())
    assert prompt.text == ""
    assert prompt.used == ()


def test_only_non_neutral_traits_are_injected():
    personality = default_personality()
    profile = PersonalityProfile(name="p", values={"directness": 95, "warmth": 50, "humor": 50})
    prompt = build_personality_prompt(personality, profile)
    assert "Directness" in prompt.text
    assert "Warmth" not in prompt.text
    assert prompt.used == ("directness",)


def test_the_number_never_reaches_the_prompt():
    # The slider selects a band; the band's prose is what is injected.
    personality = default_personality()
    profile = PersonalityProfile(name="p", values={"directness": 75})
    text = build_personality_prompt(personality, profile).text
    assert "75" not in text
    assert "Direct. States positions plainly" in text


def test_band_prose_matches_the_slider_position():
    personality = default_personality()
    for value, expected in [(5, "Extremely hedged"), (30, "Cautious"), (70, "Direct"), (95, "Blunt")]:
        profile = PersonalityProfile(name="p", values={"directness": value})
        assert expected in build_personality_prompt(personality, profile).text


def test_active_traits_are_ordered_by_distance_from_neutral():
    # When the cap bites, the survivors should be the sliders the user moved
    # furthest, not whichever sort alphabetically first.
    personality = default_personality()
    profile = PersonalityProfile(name="p", values={"warmth": 65, "directness": 100, "humor": 5})
    order = [a.trait.id for a in active_traits(personality, profile)]
    assert order[0] in ("directness", "humor")
    assert order[-1] == "warmth"


def test_trait_cap_is_enforced():
    personality = default_personality()
    profile = PersonalityProfile(name="p", values={t.id: 100 for t in personality.traits})
    prompt = build_personality_prompt(personality, profile)
    assert len(prompt.used) == 8
    assert prompt.over_cap
    assert len(prompt.dropped) == len(personality.traits) - 8


def test_custom_traits_work_identically_to_shipped_ones():
    custom = Trait(
        id="pirate",
        label="Pirate",
        bands=("Never nautical.", "Rarely.", "Sometimes.", "Often.", "Always speak as a pirate."),
    )
    personality = Personality(traits=(custom,), profiles=(PersonalityProfile("p", {"pirate": 100}),),
                              active_profile="p")
    assert "Always speak as a pirate." in build_personality_prompt(personality).text


# --- token counting --------------------------------------------------------


def test_truncate_respects_the_limit_including_its_own_marker():
    # The marker is real text sent to the model. Excluding it from the count
    # would make every truncated section overshoot, and five sections of
    # overshoot add up to a budget that is quietly wrong.
    text = " ".join(f"word{i}" for i in range(200))
    cut, was_cut = truncate_to_tokens(text, 20, words)
    assert was_cut
    assert words(cut) <= 20


def test_truncate_drops_everything_when_there_is_no_room_for_the_marker():
    cut, was_cut = truncate_to_tokens("some text here", 2, words)
    assert cut == "" and was_cut


def test_truncate_leaves_short_text_alone():
    cut, was_cut = truncate_to_tokens("short text", 100, words)
    assert cut == "short text" and not was_cut


def test_truncate_to_zero_yields_nothing():
    cut, was_cut = truncate_to_tokens("anything", 0, words)
    assert cut == "" and was_cut


def test_estimate_tokens_is_monotonic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 400) > estimate_tokens("a" * 40)


# --- the directive is never truncated --------------------------------------


def test_directive_survives_an_absurdly_small_budget():
    # The property the whole layer depends on. Everything else negotiates over
    # what is left; the directive is allocated first and cannot be evicted.
    assembler = ContextAssembler(_settings(total_budget_tokens=600, reserve_for_response=64), words)
    result = _assemble(
        assembler,
        project_doc="x " * 5000,
        live_memory="y " * 5000,
    )
    assert "KNOWLEDGE CONSTRAINT" in result.system_prompt
    assert result.system_prompt.rstrip().endswith("the list above still governs.")
    directive_section = result.section("lock directive")
    assert directive_section is not None and not directive_section.evictable
    assert not directive_section.truncated


def test_directive_is_last_even_with_everything_present(tmp_path):
    vault = tmp_path / "vault"
    (vault / "global" / "notes").mkdir(parents=True)
    (vault / "global" / "notes" / "a.md").write_text(
        "---\ntopics: [physics]\n---\n\nGravity accelerates objects.\n", encoding="utf-8"
    )
    scan = scan_vault(vault)
    retrieval = retrieve(scan, _manifest("physics"), "gravity")

    personality = default_personality()
    profile = PersonalityProfile(name="p", values={"directness": 100})
    conversation = Conversation()
    conversation.add_user("earlier")
    conversation.add_assistant("reply")

    assembler = ContextAssembler(
        Settings.from_json({"system_prompt": "Be concise.", "context": {"total_budget_tokens": 4096}}), words
    )
    result = assembler.assemble(
        manifest=_manifest("physics"),
        personality=personality,
        profile=profile,
        project_doc="# Project\n\nWe are learning physics.",
        retrieval=retrieval,
        live_memory="User prefers metric units.",
        conversation=conversation,
        user_text="what is gravity?",
    )
    prompt = result.system_prompt
    positions = [
        prompt.index("Be concise."),
        prompt.index("RESPONSE STYLE:"),
        prompt.index("PROJECT CONTEXT:"),
        prompt.index("NOTES FROM YOUR VAULT:"),
        prompt.index("THIS SESSION'S MEMORY:"),
        prompt.index("KNOWLEDGE CONSTRAINT"),
    ]
    assert positions == sorted(positions)


def test_personality_loses_to_the_directive_under_pressure():
    # If personality won, lock compliance would degrade in proportion to how
    # much personality the user configured.
    # Custom traits with long, user-authored band prose -- the realistic way a
    # personality profile grows large enough to contend with the directive.
    verbose = "and then " * 40
    traits = tuple(
        Trait(
            id=f"custom_{i}",
            label=f"Custom {i}",
            bands=("low", "lowish", "neutral", "highish", f"Behave as follows: {verbose}"),
        )
        for i in range(8)
    )
    personality = Personality(
        traits=traits,
        profiles=(PersonalityProfile("p", {t.id: 100 for t in traits}),),
        active_profile="p",
    )
    assembler = ContextAssembler(_settings(total_budget_tokens=512, reserve_for_response=64), words)
    result = _assemble(assembler, personality=personality)

    assert "KNOWLEDGE CONSTRAINT" in result.system_prompt
    assert result.system_prompt.rstrip().endswith("the list above still governs.")
    personality_section = result.section("personality bands")
    assert personality_section is not None
    assert personality_section.truncated
    assert any("keep the lock directive intact" in n for n in result.notices)

    directive_section = result.section("lock directive")
    assert directive_section is not None and not directive_section.truncated


# --- truncation is always announced ----------------------------------------


def test_dropped_note_chunks_are_announced(tmp_path):
    vault = tmp_path / "vault"
    (vault / "global" / "notes").mkdir(parents=True)
    for i in range(6):
        (vault / "global" / "notes" / f"n{i}.md").write_text(
            f"---\ntopics: [physics]\n---\n\ngravity note {i} " + "filler " * 60,
            encoding="utf-8",
        )
    scan = scan_vault(vault)
    retrieval = retrieve(scan, _manifest("physics"), "gravity")
    assembler = ContextAssembler(_settings(total_budget_tokens=512, reserve_for_response=64), words)
    result = _assemble(assembler, retrieval=retrieval)
    assert any("did not fit" in n for n in result.notices)
    section = result.section("retrieved notes")
    assert section is not None and section.dropped_items > 0


def test_dropped_conversation_turns_are_announced():
    conversation = Conversation()
    for i in range(40):
        conversation.add_user(f"question {i} " + "filler " * 30)
        conversation.add_assistant(f"answer {i} " + "filler " * 30)
    assembler = ContextAssembler(_settings(total_budget_tokens=512, reserve_for_response=64), words)
    result = _assemble(assembler, conversation=conversation)
    assert any("conversation turn" in n for n in result.notices)


def test_current_user_message_is_never_dropped():
    conversation = Conversation()
    for i in range(50):
        conversation.add_user("filler " * 50)
    assembler = ContextAssembler(_settings(total_budget_tokens=512, reserve_for_response=64), words)
    result = _assemble(assembler, conversation=conversation, user_text="THE ACTUAL QUESTION")
    assert result.messages[-1].content == "THE ACTUAL QUESTION"
    assert result.messages[-1].role == "user"


def test_over_budget_is_reported_not_hidden():
    assembler = ContextAssembler(_settings(total_budget_tokens=512, reserve_for_response=64), words)
    result = _assemble(assembler, user_text="word " * 600)
    assert result.over_budget
    assert "OVER BUDGET" in result.usage_line


def test_trait_cap_overflow_is_announced():
    personality = default_personality()
    profile = PersonalityProfile(name="p", values={t.id: 100 for t in personality.traits})
    assembler = ContextAssembler(_settings(total_budget_tokens=4096), words)
    result = _assemble(assembler, personality=personality, profile=profile)
    assert any("beyond the 8-trait cap" in n for n in result.notices)


# --- the viewer ------------------------------------------------------------


def test_viewer_shows_budget_sections_and_the_prompt():
    assembler = ContextAssembler(_settings(total_budget_tokens=2048), words)
    view = _assemble(assembler).render_for_viewer()
    assert "ASSEMBLED SYSTEM PROMPT" in view
    assert "lock directive" in view
    assert "never truncated" in view
    assert "KNOWLEDGE CONSTRAINT" in view


def test_usage_line_reports_percentage():
    assembler = ContextAssembler(_settings(total_budget_tokens=2048), words)
    assert "tokens (" in _assemble(assembler).usage_line


def test_sections_are_in_priority_order():
    assembler = ContextAssembler(_settings(), words)
    priorities = [s.priority for s in _assemble(assembler).sections]
    assert priorities == sorted(priorities)


# --- retrieval integration --------------------------------------------------


def test_disabled_retrieval_reason_reaches_the_viewer():
    assembler = ContextAssembler(_settings(), words)
    result = _assemble(assembler, retrieval=RetrievalResult(disabled_reason="trust tier 0"))
    section = result.section("retrieved notes")
    assert section is not None and "trust tier 0" in section.note


def test_no_notes_means_the_directive_says_so():
    assembler = ContextAssembler(_settings(), words)
    result = _assemble(assembler)
    assert "No notes have been provided" in result.system_prompt


# --- projects ---------------------------------------------------------------


def test_ensure_project_creates_the_tree(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    project = ensure_project(vault, "demo")
    for directory in (project.notes_dir, project.memory_live_dir, project.memory_pending_dir,
                      project.memory_holding_dir, project.skills_dir):
        assert directory.is_dir()
    assert project.doc_path.is_file()


def test_ensure_project_never_overwrites_an_existing_doc(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    project = ensure_project(vault, "demo")
    project.doc_path.write_text("MY OWN CONTENT", encoding="utf-8")
    ensure_project(vault, "demo")
    assert project.read_doc() == "MY OWN CONTENT"


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", " ", "..", "x" * 100, "con:stream"])
def test_invalid_project_names_are_refused(bad):
    with pytest.raises(SchemaError):
        validate_name(bad)


def test_slugify_produces_safe_filenames():
    assert slugify("Notes on Python 3.12!") == "notes-on-python-3-12"
    assert slugify("") == "note"
    assert "/" not in slugify("a/b/c")
