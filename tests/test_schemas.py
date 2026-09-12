"""Schema validation tests.

The theme running through these: **every invalid input must raise, not
degrade.** A test that asserts a corrupt manifest produces an empty-but-usable
manifest would be asserting the exact bug the lock system cannot survive.
"""

from __future__ import annotations

import pytest

from akira.schemas import (
    BAND_COUNT,
    Manifest,
    Personality,
    PersonalityProfile,
    SchemaError,
    Settings,
    Trait,
    band_for_value,
    normalize_topic,
    normalize_topics,
)


# --- topic normalization ---------------------------------------------------


def test_topic_normalization_lowercases_and_strips():
    assert normalize_topic("  Python_Basics  ") == "python_basics"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        " ",
        "9leading_digit",
        "has-hyphen",
        "has space",
        "has.dot",
        "UPPER-CASE-HYPHEN",
        "a" * 65,
        "../escape",
        "topic/../../etc",
        "topic\\windows",
        "topic:ads",
    ],
)
def test_invalid_topic_ids_raise(bad):
    # Topic ids become filenames under tripwires/ and are matched against note
    # frontmatter. A permissive id here is a path-traversal primitive and a
    # silent retrieval mismatch at the same time.
    with pytest.raises(SchemaError):
        normalize_topic(bad)


def test_topic_list_dedupes_and_sorts():
    assert normalize_topics(["zeta", "alpha", "ZETA"]) == ("alpha", "zeta")


def test_non_string_topic_raises():
    with pytest.raises(SchemaError):
        normalize_topic(42)


# --- manifest --------------------------------------------------------------


def test_initial_manifest_unlocks_nothing():
    manifest = Manifest.initial()
    assert manifest.unlocked_topics == ()
    assert manifest.trust_tier == 0
    assert not manifest.pin.is_set


def test_initial_manifest_locks_the_scope_note_topics():
    # The brief is explicit that ethics, morality and literature are gated
    # identically to geography or mathematics at first launch. Nothing is seeded.
    manifest = Manifest.initial()
    for topic in ("ethics", "morality", "literature", "geography", "mathematics"):
        assert not manifest.is_unlocked(topic)


def test_unlock_records_provenance():
    manifest = Manifest.initial().with_unlocked("python_basics", ["skills/python-intro.md"], note="reviewed")
    assert manifest.is_unlocked("python_basics")
    assert len(manifest.history) == 1
    event = manifest.history[0]
    assert event.action == "unlock"
    assert event.source_notes == ("skills/python-intro.md",)
    assert event.at


def test_relock_removes_topic_but_keeps_history():
    manifest = Manifest.initial().with_unlocked("chemistry").with_relocked("chemistry")
    assert not manifest.is_unlocked("chemistry")
    # The unlock is not erased. The history is an audit trail of what the model
    # was permitted to know and when -- deleting the unlock event would hide
    # that it ever had access.
    assert [e.action for e in manifest.history] == ["unlock", "relock"]


def test_all_locked_returns_the_locked_subset():
    manifest = Manifest.initial().with_unlocked("physics")
    assert manifest.all_locked(["physics", "chemistry", "biology"]) == ("chemistry", "biology")


def test_unlock_is_idempotent():
    once = Manifest.initial().with_unlocked("physics")
    twice = once.with_unlocked("physics")
    assert twice is once
    assert len(twice.history) == 1


def test_manifest_roundtrips():
    original = (
        Manifest.initial()
        .with_unlocked("physics", ["a.md"])
        .with_trust_tier(2)
        .with_pin("$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA")
    )
    restored = Manifest.from_json(original.to_json())
    assert restored.unlocked_topics == original.unlocked_topics
    assert restored.trust_tier == 2
    assert restored.pin.hash == original.pin.hash


def test_manifest_rejects_future_schema_version():
    # Loading a newer schema means guessing what its fields mean. For a file
    # that defines what the model may discuss, guessing is not acceptable.
    with pytest.raises(SchemaError):
        Manifest.from_json({"schema_version": 99, "unlocked_topics": []})


def test_manifest_rejects_out_of_range_trust_tier():
    with pytest.raises(SchemaError):
        Manifest.from_json({"unlocked_topics": [], "trust_tier": 4})


def test_manifest_rejects_invalid_topic_in_unlocked_list():
    with pytest.raises(SchemaError):
        Manifest.from_json({"unlocked_topics": ["fine", "NOT FINE"]})


def test_manifest_rejects_non_object():
    with pytest.raises(SchemaError):
        Manifest.from_json(["unlocked_topics"])


def test_manifest_rejects_bad_pin_hash():
    with pytest.raises(SchemaError):
        Manifest.from_json({"unlocked_topics": [], "pin": {"algorithm": "argon2id", "hash": "plaintext1234"}})


def test_manifest_rejects_non_argon2_pin_algorithm():
    with pytest.raises(SchemaError):
        Manifest.from_json({"unlocked_topics": [], "pin": {"algorithm": "md5", "hash": ""}})


def test_manifest_has_no_unlock_all():
    # Guards against a future convenience method. The absence of a bulk unlock
    # is a design constraint from the brief, not an oversight to be fixed.
    names = [n for n in dir(Manifest) if "all" in n.lower() and n.startswith("with_")]
    assert names == []


def test_skill_approval_requires_valid_digest():
    with pytest.raises(SchemaError):
        Manifest.from_json(
            {
                "unlocked_topics": [],
                "approved_skills": {"p/s.py": {"sha256": "short", "approved_at": "now"}},
            }
        )


# --- settings --------------------------------------------------------------


def test_settings_defaults_have_every_lock_layer_on():
    settings = Settings()
    layers = settings.lock_layers
    assert layers.directive and layers.retrieval and layers.tripwires and layers.auditor
    assert not layers.any_disabled


def test_settings_default_system_prompt_is_empty():
    # No vendor safety preamble, no default persona, no behavioral boilerplate.
    # The system prompt is entirely user-authored.
    assert Settings().system_prompt == ""


def test_settings_default_trust_is_conversation_only():
    assert Manifest.initial().trust_tier == 0


def test_disabled_layers_are_reported_by_name():
    settings = Settings.from_json({"lock_layers": {"auditor": False, "tripwires": False}})
    assert settings.lock_layers.any_disabled
    assert settings.lock_layers.disabled_names == ("tripwires", "auditor")


def test_settings_roundtrip():
    original = Settings.from_json({"models": {"temperature": 0.2, "loading": "concurrent"}})
    restored = Settings.from_json(original.to_json())
    assert restored.models.temperature == 0.2
    assert restored.models.loading == "concurrent"


def test_settings_rejects_unknown_loading_mode():
    with pytest.raises(SchemaError):
        Settings.from_json({"models": {"loading": "parallel"}})


def test_settings_rejects_reserve_exceeding_budget():
    with pytest.raises(SchemaError):
        Settings.from_json({"context": {"total_budget_tokens": 1024, "reserve_for_response": 2048}})


def test_settings_rejects_overlap_exceeding_chunk():
    with pytest.raises(SchemaError):
        Settings.from_json({"context": {"chunk_tokens": 100, "chunk_overlap_tokens": 200}})


def test_settings_rejects_out_of_range_temperature():
    with pytest.raises(SchemaError):
        Settings.from_json({"models": {"temperature": 9.0}})


def test_settings_rejects_bad_project_name():
    with pytest.raises(SchemaError):
        Settings.from_json({"current_project": "../escape"})


def test_no_auditor_strictness_disables_blocking():
    # Strictness widens what counts as a clean PASS. There is deliberately no
    # value that makes the auditor fail open.
    from akira.schemas import AuditorSettings

    assert "off" not in AuditorSettings.VALID_STRICTNESS
    assert "disabled" not in AuditorSettings.VALID_STRICTNESS


# --- personality -----------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, 0), (20, 0),
        (21, 1), (40, 1),
        (41, 2), (50, 2), (60, 2),
        (61, 3), (80, 3),
        (81, 4), (100, 4),
    ],
)
def test_band_boundaries(value, expected):
    assert band_for_value(value) == expected


@pytest.mark.parametrize("bad", [-1, 101, 3.5, True, "50"])
def test_band_rejects_invalid_values(bad):
    with pytest.raises(SchemaError):
        band_for_value(bad)


def test_trait_requires_exactly_five_bands():
    for count in (0, 3, 4, 6):
        with pytest.raises(SchemaError):
            Trait.from_json({"id": "x", "label": "X", "bands": ["b"] * count})


def test_trait_rejects_empty_band_text():
    # The user authors band prose; the application cannot invent it. An empty
    # band would silently contribute nothing when the slider lands on it.
    bands = ["a", "b", "", "d", "e"]
    with pytest.raises(SchemaError):
        Trait.from_json({"id": "x", "label": "X", "bands": bands})


def test_trait_rejects_whitespace_only_band_text():
    bands = ["a", "b", "   ", "d", "e"]
    with pytest.raises(SchemaError):
        Trait.from_json({"id": "x", "label": "X", "bands": bands})


def test_shipped_traits_all_valid_and_neutral_by_default():
    from akira.personality.defaults import SHIPPED_TRAITS, default_personality

    for trait in SHIPPED_TRAITS:
        assert len(trait.bands) == BAND_COUNT
        assert all(b.strip() for b in trait.bands)
        assert band_for_value(trait.default_value) == 2

    personality = default_personality()
    profile = personality.active()
    assert set(profile.values) == {t.id for t in SHIPPED_TRAITS}


def test_shipped_trait_set_covers_the_brief():
    from akira.personality.defaults import SHIPPED_TRAITS

    ids = {t.id for t in SHIPPED_TRAITS}
    assert ids >= {
        "directness", "verbosity", "formality", "warmth", "humor",
        "curiosity", "pedagogy", "confidence_signaling",
        "technical_density", "proactivity",
    }


def test_personality_rejects_duplicate_trait_ids():
    trait = {"id": "dup", "label": "Dup", "bands": ["a", "b", "c", "d", "e"]}
    with pytest.raises(SchemaError):
        Personality.from_json({"traits": [trait, trait], "profiles": {}})


def test_personality_roundtrip():
    from akira.personality.defaults import default_personality

    original = default_personality()
    restored = Personality.from_json(original.to_json())
    assert [t.id for t in restored.traits] == [t.id for t in original.traits]
    assert restored.active().values == original.active().values


def test_missing_active_profile_falls_back_to_empty_not_error():
    # Personality is cosmetic. A missing profile must not block a response --
    # this is the one place a soft fallback is correct, and the lock system has
    # no equivalent.
    personality = Personality(traits=(), profiles=(), active_profile="gone")
    assert personality.active().values == {}


def test_profile_rejects_out_of_range_value():
    with pytest.raises(SchemaError):
        PersonalityProfile.from_json("p", {"values": {"directness": 150}})
