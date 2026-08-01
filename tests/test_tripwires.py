"""Layer 4 -- deterministic tripwires."""

from __future__ import annotations

import json

import pytest

from protege.lock.tripwires import (
    MAX_SCAN_CHARS,
    TopicTripwires,
    TripwireError,
    TripwireSet,
    seed_topic,
    validate_pattern,
)
from protege.store import bootstrap_vault, tripwire_dir


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    bootstrap_vault(root)
    return root


def put(vault, topic, keywords=(), patterns=(), enabled=True, filename=None):
    payload = {"topic": topic, "keywords": list(keywords), "patterns": list(patterns), "enabled": enabled}
    name = filename or f"{topic}.json"
    (tripwire_dir(vault) / name).write_text(json.dumps(payload), encoding="utf-8")


# --- definitions -----------------------------------------------------------


def test_loads_a_topic_rule_set(vault):
    put(vault, "chemistry", keywords=["sodium"], patterns=[r"\bNaCl\b"])
    rules = TripwireSet.load(vault).by_topic["chemistry"]
    assert rules.keywords == ("sodium",)
    assert rules.patterns == (r"\bNaCl\b",)
    assert rules.rule_count == 2


def test_rejects_invalid_topic_id():
    with pytest.raises(TripwireError):
        TopicTripwires.from_json({"topic": "NOT VALID"})


def test_rejects_uncompilable_regex():
    # Discovered at load rather than mid-scan: a broken regex inside the gate
    # blocks forever with no explanation.
    with pytest.raises(TripwireError, match="invalid regex"):
        TopicTripwires.from_json({"topic": "chemistry", "patterns": ["[unclosed"]})


def test_rejects_non_string_entries():
    with pytest.raises(TripwireError):
        TopicTripwires.from_json({"topic": "chemistry", "keywords": [123]})


def test_filename_topic_mismatch_is_refused(vault):
    put(vault, "chemistry", keywords=["sodium"], filename="physics.json")
    loaded = TripwireSet.load(vault)
    assert "chemistry" not in loaded.by_topic
    assert any("refusing to guess" in e for e in loaded.load_errors)


def test_broken_file_is_reported_not_swallowed(vault):
    (tripwire_dir(vault) / "chemistry.json").write_text("{not json", encoding="utf-8")
    loaded = TripwireSet.load(vault)
    # "This topic has tripwires" and "this topic's tripwires are broken" must
    # not look the same to the user.
    assert loaded.load_errors
    assert "chemistry" not in loaded.by_topic


def test_missing_directory_is_not_an_error(tmp_path):
    assert TripwireSet.load(tmp_path).by_topic == {}


def test_roundtrip(vault):
    seed_topic(vault, "chemistry", keywords=["sodium"], patterns=[r"\bNaCl\b"])
    assert TripwireSet.load(vault).by_topic["chemistry"].keywords == ("sodium",)


# --- pattern validation ----------------------------------------------------


def test_validate_accepts_a_reasonable_pattern():
    assert validate_pattern(r"\bsodium\s+chloride\b") == ""


def test_validate_rejects_empty():
    assert "empty" in validate_pattern("   ")


def test_validate_rejects_uncompilable():
    assert "invalid regex" in validate_pattern("[unclosed")


@pytest.mark.parametrize("pattern", [r"(a+)+", r"(\d+)*", r"([a-z]+)+"])
def test_validate_rejects_nested_quantifiers(pattern):
    # Python's re has no execution timeout, so a catastrophic pattern would
    # hang the lock check -- which is a fail-closed violation, since a frozen
    # UI never reaches the block.
    assert "nested quantifier" in validate_pattern(pattern)


# --- scanning --------------------------------------------------------------


def test_keyword_hit_on_locked_topic(vault):
    put(vault, "chemistry", keywords=["sodium"])
    scan = TripwireSet.load(vault).scan("You add sodium to water.", ["chemistry"])
    assert scan.triggered
    assert scan.first_topic == "chemistry"
    assert "sodium" in scan.reason()


def test_unlocked_topic_rules_are_inert(vault):
    # The user taught it; mentioning it is the point.
    put(vault, "chemistry", keywords=["sodium"])
    scan = TripwireSet.load(vault).scan("You add sodium to water.", [])
    assert not scan.triggered


def test_keyword_matching_is_case_insensitive(vault):
    put(vault, "chemistry", keywords=["sodium"])
    assert TripwireSet.load(vault).scan("SODIUM reacts.", ["chemistry"]).triggered


def test_keyword_matching_respects_word_boundaries(vault):
    put(vault, "chemistry", keywords=["ion"])
    assert not TripwireSet.load(vault).scan("The onion is a vegetable.", ["chemistry"]).triggered
    assert TripwireSet.load(vault).scan("An ion has charge.", ["chemistry"]).triggered


def test_regex_pattern_hit(vault):
    put(vault, "chemistry", patterns=[r"\b[A-Z][a-z]?\d*(?:Cl|OH)\b"])
    assert TripwireSet.load(vault).scan("Add NaCl to the beaker.", ["chemistry"]).triggered


def test_clean_text_passes(vault):
    put(vault, "chemistry", keywords=["sodium"])
    assert not TripwireSet.load(vault).scan("Let's talk about poetry.", ["chemistry"]).triggered


def test_disabled_rule_set_does_not_fire(vault):
    put(vault, "chemistry", keywords=["sodium"], enabled=False)
    assert not TripwireSet.load(vault).scan("sodium", ["chemistry"]).triggered


def test_all_hits_are_reported_as_evidence(vault):
    put(vault, "chemistry", keywords=["sodium", "chloride"])
    scan = TripwireSet.load(vault).scan("sodium and chloride", ["chemistry"])
    assert len(scan.hits) == 2
    assert "sodium" in scan.evidence() and "chloride" in scan.evidence()


# --- the compliant-decline exemption ---------------------------------------


def test_a_compliant_decline_does_not_trip_its_own_topic(vault):
    # Without blanking, "[LOCKED: chemistry]" contains "chemistry" and Layer 4
    # would block the exact behavior Layer 2 asked for.
    put(vault, "chemistry", keywords=["chemistry"])
    scan = TripwireSet.load(vault).scan("[LOCKED: chemistry]", ["chemistry"])
    assert not scan.triggered


def test_a_decline_with_a_smuggled_hint_still_trips(vault):
    put(vault, "chemistry", keywords=["sodium"])
    scan = TripwireSet.load(vault).scan("[LOCKED: chemistry] but it involves sodium", ["chemistry"])
    assert scan.triggered


def test_blanking_preserves_offsets(vault):
    put(vault, "chemistry", keywords=["sodium"])
    text = "[LOCKED: chemistry] sodium"
    scan = TripwireSet.load(vault).scan(text, ["chemistry"])
    hit = scan.hits[0]
    assert text[hit.start:hit.end] == "sodium"


# --- fail-closed behaviors -------------------------------------------------


def test_oversized_output_is_reported_incomplete_and_blocks(vault):
    put(vault, "chemistry", keywords=["sodium"])
    scan = TripwireSet.load(vault).scan("x" * (MAX_SCAN_CHARS + 10), ["chemistry"])
    # Text this layer could not finish checking has not been cleared.
    assert scan.incomplete
    assert scan.triggered
    assert "could not be fully checked" in scan.reason()


def test_topics_without_rules_are_reported(vault):
    put(vault, "chemistry", keywords=["sodium"])
    put(vault, "physics", keywords=[])
    missing = TripwireSet.load(vault).topics_without_rules(["chemistry", "physics", "biology"])
    # A user who thinks Layer 4 covers a topic it has never heard of is worse
    # off than one who knows it does not.
    assert missing == ("biology", "physics")


def test_scan_with_no_locked_topics_is_clean(vault):
    put(vault, "chemistry", keywords=["sodium"])
    assert not TripwireSet.load(vault).scan("sodium sodium sodium", []).triggered
