"""PIN hashing and attempt throttling."""

from __future__ import annotations

import pytest

from protege.schemas import Manifest, PinRecord
from protege.security.pin import (
    ATTEMPT_DELAYS,
    MIN_PIN_LENGTH,
    AttemptTracker,
    PinError,
    hash_pin,
    strength_note,
    validate_pin,
    verify_pin,
)


def test_hash_is_argon2id_and_not_the_pin():
    encoded = hash_pin("1234")
    assert encoded.startswith("$argon2id$")
    assert "1234" not in encoded


def test_verify_accepts_the_right_pin():
    assert verify_pin(hash_pin("correct horse"), "correct horse")


def test_verify_rejects_the_wrong_pin():
    assert not verify_pin(hash_pin("1234"), "1235")


def test_each_hash_uses_a_fresh_salt():
    # Identical PINs must not produce identical hashes, or the manifest would
    # leak which of two vaults share a PIN.
    assert hash_pin("1234") != hash_pin("1234")


@pytest.mark.parametrize("bad", ["", "123", " 1234", "1234 ", "x" * 200])
def test_policy_rejects_bad_pins(bad):
    with pytest.raises(PinError):
        validate_pin(bad)


def test_policy_accepts_the_minimum_length():
    assert validate_pin("1" * MIN_PIN_LENGTH)


def test_non_string_pin_is_refused():
    with pytest.raises(PinError):
        validate_pin(1234)


@pytest.mark.parametrize("encoded", ["", "not-a-hash", "$argon2id$garbage", None])
def test_corrupt_stored_hash_never_grants_access(encoded):
    # A corrupt hash must be indistinguishable from a wrong PIN, and must
    # certainly not open the door.
    assert not verify_pin(encoded, "1234")


def test_empty_pin_never_verifies():
    assert not verify_pin(hash_pin("1234"), "")


def test_strength_note_warns_about_short_numeric_pins():
    note = strength_note("1234")
    assert "guess" in note
    assert "not encryption" in note


def test_strength_note_is_quiet_for_a_passphrase():
    assert strength_note("a longer passphrase here") == ""


def test_manifest_round_trips_the_hash():
    encoded = hash_pin("1234")
    manifest = Manifest.initial().with_pin(encoded)
    assert Manifest.from_json(manifest.to_json()).pin.hash == encoded


def test_manifest_without_a_pin_reports_not_set():
    assert not Manifest.initial().pin.is_set
    assert PinRecord().is_set is False


# --- throttling ------------------------------------------------------------


def test_failures_escalate_the_delay():
    tracker = AttemptTracker()
    delays = [tracker.record_failure() for _ in range(len(ATTEMPT_DELAYS) + 2)]
    assert delays == sorted(delays)
    assert delays[-1] == ATTEMPT_DELAYS[-1]


def test_success_resets_the_tracker():
    tracker = AttemptTracker()
    tracker.record_failure()
    tracker.record_failure()
    tracker.record_failure()
    assert tracker.failures == 3
    tracker.record_success()
    assert tracker.failures == 0
    assert not tracker.locked_out


def test_early_failures_are_not_throttled():
    # Typos should not be punished; sustained guessing should.
    tracker = AttemptTracker()
    assert tracker.record_failure() == 0.0
    assert not tracker.locked_out
