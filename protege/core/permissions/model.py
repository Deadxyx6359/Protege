"""What the user has actually allowed, and the check that enforces it.

Deny by default. A capability with no grant is refused, and there is no
"allow everything" — not as a setting, not as a debug flag. The absence of
that switch is the point: every mechanism that has one eventually has it
switched on.

Enforcement here is a *decision*, not an instruction. Nothing in this module
asks a model to behave; it answers yes or no, and the tool registry uses those
answers to build the tool list an agent is given. A capability that is not
granted produces no tool, so there is nothing for a jailbreak to reach for.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from protege.core.config import config_dir
from protege.security.paths import PathViolation, is_within, real, reject_dangerous

from . import capabilities as caps
from .capabilities import Capability, ScopeKind


class PermissionError_(PermissionError):
    """Raised when something is attempted that was not granted."""


@dataclass(frozen=True, slots=True)
class Decision:
    """The answer, and why — so refusals can be explained rather than just felt.

    A tool that fails with "not permitted" and no reason trains people to grant
    everything, because that is the only way to find out what was missing.
    """

    allowed: bool
    capability: str
    scope: str | None = None
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed

    def raise_if_denied(self) -> None:
        if not self.allowed:
            raise PermissionError_(self.reason or f"{self.capability} is not permitted")


@dataclass(frozen=True, slots=True)
class Grant:
    """One capability the user has allowed, optionally narrowed and time-limited."""

    capability: str
    scopes: tuple[str, ...] = ()
    granted: float = field(default_factory=time.time)
    expires: float | None = None
    note: str = ""

    def expired(self, now: float | None = None) -> bool:
        if self.expires is None:
            return False
        return (time.time() if now is None else now) >= self.expires

    def to_json(self) -> dict:
        return {
            "capability": self.capability,
            "scopes": list(self.scopes),
            "granted": self.granted,
            "expires": self.expires,
            "note": self.note,
        }

    @staticmethod
    def from_json(raw: dict) -> "Grant | None":
        """Parse one grant, returning None for anything malformed.

        A grant file that has been hand-edited into nonsense must not become an
        *unrestricted* grant. Anything unparseable is dropped, which fails
        closed.
        """
        if not isinstance(raw, dict):
            return None
        capability = raw.get("capability")
        if not isinstance(capability, str) or capability not in caps.CATALOGUE:
            return None
        scopes = raw.get("scopes")
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            return None
        expires = raw.get("expires")
        if expires is not None and not isinstance(expires, (int, float)):
            return None
        granted = raw.get("granted")
        return Grant(
            capability=capability,
            scopes=tuple(scopes),
            granted=float(granted) if isinstance(granted, (int, float)) else time.time(),
            expires=float(expires) if expires is not None else None,
            note=str(raw.get("note", "")),
        )


# -- scope matching ---------------------------------------------------------
#
# Each kind of scope has its own containment rule. They are separate functions
# rather than one clever comparison because the failure modes are different and
# each deserves to be read on its own.


def _path_allows(granted: str, candidate: str) -> bool:
    """A granted root covers itself and everything beneath it.

    Both sides are fully resolved first, so a symlink or junction pointing out
    of the root does not sneak past, and `..` cannot climb. `/vault-backup` is
    correctly outside `/vault` because containment is checked on path
    components, not on string prefixes.
    """
    try:
        reject_dangerous(candidate)
        return is_within(real(granted), real(candidate))
    except (PathViolation, OSError, ValueError):
        return False


def _host_allows(granted: str, candidate: str) -> bool:
    """Exact host, or a subdomain of the granted one.

    `example.com` covers `api.example.com` but not `notexample.com` — the dot
    is required, which string-prefix matching would miss.
    """
    g = granted.strip().lower().lstrip(".")
    c = candidate.strip().lower()
    if not g or not c:
        return False
    # Strip a port if one came along with the host.
    c = c.split("/")[0].split(":")[0]
    return c == g or c.endswith("." + g)


def _exact_allows(granted: str, candidate: str) -> bool:
    return granted.strip().lower() == candidate.strip().lower()


_MATCHERS = {
    ScopeKind.PATH: _path_allows,
    ScopeKind.HOST: _host_allows,
    ScopeKind.ACCOUNT: _exact_allows,
    ScopeKind.PROVIDER: _exact_allows,
}


# -- the policy -------------------------------------------------------------


class Policy:
    """The live set of grants, and the question `allows`.

    Held by the application and consulted by the tool registry. Cheap to query;
    every call is a dictionary lookup and at most a handful of scope
    comparisons.
    """

    def __init__(self, grants: list[Grant] | None = None) -> None:
        self._grants: dict[str, Grant] = {}
        for grant in grants or []:
            self._grants[grant.capability] = grant

    # -- queries ------------------------------------------------------------

    def allows(self, capability_id: str, scope: str | None = None) -> Decision:
        """Is \a capability_id permitted, for \a scope if it takes one?"""
        try:
            capability = caps.get(capability_id)
        except KeyError as exc:
            return Decision(False, capability_id, scope, str(exc))

        grant = self._grants.get(capability_id)
        if grant is None:
            return Decision(False, capability_id, scope,
                            f"{capability.title} has not been allowed")

        if grant.expired():
            return Decision(False, capability_id, scope,
                            f"{capability.title} was allowed but the permission has expired")

        if capability.scope is ScopeKind.NONE:
            return Decision(True, capability_id, None, "")

        if scope is None:
            return Decision(False, capability_id, None,
                            f"{capability.title} is limited to specific "
                            f"{capability.scope.value}s, and none was given")

        matcher = _MATCHERS[capability.scope]
        for granted_scope in grant.scopes:
            if matcher(granted_scope, scope):
                return Decision(True, capability_id, scope, "")

        return Decision(False, capability_id, scope,
                        f"{scope} is outside what {capability.title} was allowed for")

    def granted(self, capability_id: str) -> Grant | None:
        grant = self._grants.get(capability_id)
        return None if grant is None or grant.expired() else grant

    def active(self) -> list[Grant]:
        """Every grant currently in force, expired ones excluded."""
        return [g for g in self._grants.values() if not g.expired()]

    def holds_any(self, capability_ids: tuple[str, ...]) -> bool:
        return any(self.granted(c) is not None for c in capability_ids)

    # -- changes ------------------------------------------------------------

    def grant(self, capability_id: str, scopes: tuple[str, ...] = (),
              expires: float | None = None, note: str = "") -> Grant:
        """Allow a capability. Raises if it is not one that exists."""
        capability = caps.get(capability_id)
        if capability.scope is not ScopeKind.NONE and not scopes:
            raise ValueError(
                f"{capability.title} must be granted for at least one "
                f"{capability.scope.value}"
            )
        grant = Grant(capability_id, tuple(scopes), time.time(), expires, note)
        self._grants[capability_id] = grant
        return grant

    def revoke(self, capability_id: str) -> None:
        self._grants.pop(capability_id, None)

    def revoke_all(self) -> None:
        """Withdraw everything. The panic button, and the default state."""
        self._grants.clear()

    # -- persistence --------------------------------------------------------

    @staticmethod
    def path() -> Path:
        return config_dir() / "permissions.json"

    @classmethod
    def load(cls) -> "Policy":
        """Read the grants, failing closed on anything unreadable.

        A missing, truncated or corrupt file yields an empty policy — no
        permissions — rather than an error at startup. Losing grants is an
        inconvenience the user can repair in a minute; starting up with grants
        nobody can account for is not.
        """
        target = cls.path()
        if not target.is_file():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(raw, dict):
            return cls()

        parsed = []
        for entry in raw.get("grants", []):
            grant = Grant.from_json(entry)
            if grant is not None and not grant.expired():
                parsed.append(grant)
        return cls(parsed)

    def save(self) -> None:
        """Write atomically, in the same directory, so a crash cannot truncate."""
        target = self.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "grants": [g.to_json() for g in self._grants.values()]}

        handle, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=".permissions-", suffix=".tmp"
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
