"""PIN handling.

Stored as a salted argon2id hash, never plaintext. The salt is generated per
hash and embedded in argon2's encoded string; we neither generate nor store one
separately.

**Be clear about what this is for.** The PIN keeps a housemate or a colleague
from opening Akira on an unlocked machine and reading the conversation. It is
not encryption. The vault sits on disk as plain markdown and JSON, readable by
anything that can read the filesystem, PIN or no PIN. Nothing here protects
against someone with access to the drive, and the README says so in those words
rather than leaving it to be inferred.

Argon2id parameters are argon2-cffi's defaults, which target roughly 50ms on
ordinary hardware. That is not a meaningful brute-force barrier for a 4-digit
PIN considered on its own -- 10,000 candidates at 50ms is under ten minutes --
which is precisely why the docstring above says what it says, and why
`AttemptTracker` adds escalating delays to make an interactive attack tedious
rather than pretending the hash alone is sufficient.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PIN_LENGTH = 4
MAX_PIN_LENGTH = 128

# Escalating lockout after repeated failures. Not a defense against an attacker
# with the vault directory -- they would attack the files, not the dialog -- but
# it makes shoulder-surfed guessing at a borrowed laptop impractical.
ATTEMPT_DELAYS = (0.0, 0.0, 0.5, 2.0, 5.0, 15.0, 30.0)

_hasher = PasswordHasher()


class PinError(ValueError):
    """The PIN did not satisfy policy."""


def validate_pin(pin: str) -> str:
    if not isinstance(pin, str):
        raise PinError("PIN must be text")
    if len(pin) < MIN_PIN_LENGTH:
        raise PinError(f"PIN must be at least {MIN_PIN_LENGTH} characters")
    if len(pin) > MAX_PIN_LENGTH:
        raise PinError(f"PIN must be at most {MAX_PIN_LENGTH} characters")
    if pin.strip() != pin:
        raise PinError("PIN must not start or end with whitespace")
    return pin


def hash_pin(pin: str) -> str:
    """Hash a PIN for storage in the manifest."""
    return _hasher.hash(validate_pin(pin))


def verify_pin(encoded: str, pin: str) -> bool:
    """Check a PIN against its stored hash.

    Returns False for every failure mode -- wrong PIN, corrupt hash, empty
    stored value. A corrupt hash must not be distinguishable from a wrong PIN
    by anything but the logs, and it must certainly not grant access.
    """
    if not encoded or not isinstance(pin, str) or not pin:
        return False
    try:
        return _hasher.verify(encoded, pin)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:  # noqa: BLE001 - unknown failure is still a failure
        return False


def needs_rehash(encoded: str) -> bool:
    """Whether a stored hash was made with weaker parameters than current."""
    if not encoded:
        return False
    try:
        return _hasher.check_needs_rehash(encoded)
    except (InvalidHashError, Exception):  # noqa: BLE001
        return False


def strength_note(pin: str) -> str:
    """Advisory shown while setting a PIN. Never blocks."""
    if pin.isdigit() and len(pin) <= 6:
        return (
            f"A {len(pin)}-digit numeric PIN is quick to type and quick to guess. "
            "It is an access convenience, not encryption -- see the README."
        )
    if len(pin) < 8:
        return "Short PINs are easy to guess. Consider a longer passphrase."
    return ""


@dataclass
class AttemptTracker:
    """Escalating delay after failed PIN entries.

    In-memory only. Restarting the application resets it, which is fine: the
    goal is to make interactive guessing tedious, not to build a lockout an
    attacker with filesystem access would ever encounter.
    """

    failures: int = 0
    _blocked_until: float = field(default=0.0, repr=False)

    def record_failure(self) -> float:
        self.failures += 1
        index = min(self.failures, len(ATTEMPT_DELAYS) - 1)
        delay = ATTEMPT_DELAYS[index]
        self._blocked_until = time.monotonic() + delay
        return delay

    def record_success(self) -> None:
        self.failures = 0
        self._blocked_until = 0.0

    @property
    def wait_remaining(self) -> float:
        return max(0.0, self._blocked_until - time.monotonic())

    @property
    def locked_out(self) -> bool:
        return self.wait_remaining > 0
