"""Path resolution and trust-tier capability gating.

Two jobs, kept together because they are always used together:

1. **Containment.** Every path is resolved to a real location and checked
   against an explicit set of permitted roots before any operation. Traversal is
   blocked at all tiers, including tier 3.

2. **Capability lookup.** What the *model* is permitted to do at the current
   trust tier.

The distinction that matters throughout: trust tiers gate **the model**, not the
application. Protege itself always reads `vault/.protege/manifest.json` -- it has
to, that file is what defines the gate. Tier 0 means the model gets no
retrieval, no memory, and no note contents; it does not mean Protege cannot
find its own config. Anything the user explicitly points at in the UI (the
source notes chosen during an unlock, for instance) is a user action, not a
model action, and is not gated by tier.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Iterable, Sequence

# Windows treats these as device names in any directory, with or without an
# extension. Creating one can hang on legacy handlers, so they are refused.
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

# NTFS alternate data streams: "note.md:hidden" writes a second, invisible
# stream on the same file. A vault scan would never show it and retrieval would
# never index it, which makes it an ideal place to smuggle locked content.
_ADS_RE = re.compile(r":")


class PathViolation(PermissionError):
    """A path escaped its permitted roots, or the tier forbids the operation.

    Always fatal to the operation that raised it. Never downgraded to a warning
    and never retried with a relaxed policy.
    """


@dataclass(frozen=True)
class TierCapabilities:
    """What the model may do at a given trust tier."""

    tier: int
    label: str
    model_reads_vault: bool
    model_writes_vault: bool
    retrieval_enabled: bool
    model_proposed_memory: bool
    user_pinned_memory: bool
    external_roots_enabled: bool
    skill_authoring: bool
    skill_execution: bool

    @property
    def any_memory_writes(self) -> bool:
        return self.model_proposed_memory or self.user_pinned_memory


# Tier 0 is the default and the one the application must be correct at. Note
# that memory writes are off entirely -- the model has not yet earned write
# access to the vault, and a user-pinned write at tier 0 would still put model
# output on disk.
#
# Skill execution requires tier 2. The brief ties execution to per-skill
# approval rather than to a tier, but execution spawns a subprocess, and "no
# shell access at the default trust tier" cannot coexist with a tier-0 subprocess
# escape hatch. Approval is necessary but not sufficient.
TIERS: dict[int, TierCapabilities] = {
    0: TierCapabilities(
        tier=0,
        label="Tier 0 - conversation only",
        model_reads_vault=False,
        model_writes_vault=False,
        retrieval_enabled=False,
        model_proposed_memory=False,
        user_pinned_memory=False,
        external_roots_enabled=False,
        skill_authoring=False,
        skill_execution=False,
    ),
    1: TierCapabilities(
        tier=1,
        label="Tier 1 - read-only vault",
        model_reads_vault=True,
        model_writes_vault=False,
        retrieval_enabled=True,
        model_proposed_memory=False,
        user_pinned_memory=True,
        external_roots_enabled=False,
        skill_authoring=False,
        skill_execution=False,
    ),
    2: TierCapabilities(
        tier=2,
        label="Tier 2 - read/write vault",
        model_reads_vault=True,
        model_writes_vault=True,
        retrieval_enabled=True,
        model_proposed_memory=True,
        user_pinned_memory=True,
        external_roots_enabled=False,
        skill_authoring=True,
        skill_execution=True,
    ),
    3: TierCapabilities(
        tier=3,
        label="Tier 3 - vault plus allowlisted directories",
        model_reads_vault=True,
        model_writes_vault=True,
        retrieval_enabled=True,
        model_proposed_memory=True,
        user_pinned_memory=True,
        external_roots_enabled=True,
        skill_authoring=True,
        skill_execution=True,
    ),
}


def capabilities(tier: int) -> TierCapabilities:
    """Capabilities for a tier. Unknown tiers collapse to tier 0, not to the
    nearest match -- an unrecognized tier is a corrupt manifest, and the safe
    reading of a corrupt manifest is 'no privileges'."""
    return TIERS.get(tier, TIERS[0])


def real(path: str | os.PathLike[str]) -> Path:
    """Fully resolve a path without requiring it to exist.

    `os.path.realpath(strict=False)` resolves every symlink, junction, and
    `..` segment it can and leaves the non-existent tail intact. This is what
    makes containment checks meaningful for files we are about to create.
    """
    return Path(os.path.realpath(os.fspath(path)))


def _reject_dangerous_components(candidate: PurePath) -> None:
    parts = list(candidate.parts)
    # Skip the drive/root component ("C:\\"), whose colon is legitimate.
    if parts and (candidate.drive or candidate.root):
        parts = parts[1:]
    for part in parts:
        if "\x00" in part:
            raise PathViolation("path contains a NUL byte")
        if _ADS_RE.search(part):
            raise PathViolation(
                f"path component {part!r} contains ':' -- NTFS alternate data streams are refused "
                "because content stored in them is invisible to vault scans and retrieval"
            )
        stem = part.split(".")[0].strip().lower()
        if stem in _WINDOWS_RESERVED:
            raise PathViolation(f"path component {part!r} is a reserved Windows device name")


def reject_dangerous(candidate: str | os.PathLike[str]) -> None:
    """Public wrapper over the component checks.

    Exposed so the capability layer can validate a path without importing a
    private name across modules. The checks themselves — NUL bytes, NTFS
    alternate data streams, reserved Windows device names — are the same ones
    the vault has always used, and are worth applying to every path the
    application touches, not only vault notes.
    """
    _reject_dangerous_components(PurePath(os.fspath(candidate)))


def is_within(root: Path, candidate: Path) -> bool:
    """True if `candidate` is `root` or lies beneath it.

    Both arguments must already be fully resolved. Uses `Path.is_relative_to`
    rather than string prefixing, so `/vault-backup` is correctly rejected as
    outside `/vault`.
    """
    try:
        return candidate == root or candidate.is_relative_to(root)
    except (ValueError, OSError):
        return False


@dataclass(frozen=True)
class PathPolicy:
    """Resolves and validates every path Protege touches.

    Construct one per (vault, manifest) pair and pass it down. Nothing in the
    codebase should call `open()` on a model-supplied or note-derived path
    without routing it through here first.
    """

    vault_root: Path
    trust_tier: int = 0
    external_roots: tuple[Path, ...] = ()
    caps: TierCapabilities = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "vault_root", real(self.vault_root))
        object.__setattr__(self, "external_roots", tuple(real(p) for p in self.external_roots))
        object.__setattr__(self, "caps", capabilities(self.trust_tier))

    @staticmethod
    def build(vault_root: str | os.PathLike[str], trust_tier: int, external_roots: Sequence[str] = ()) -> "PathPolicy":
        return PathPolicy(
            vault_root=Path(vault_root),
            trust_tier=trust_tier,
            external_roots=tuple(Path(r) for r in external_roots),
        )

    # -- roots --------------------------------------------------------------

    @property
    def model_read_roots(self) -> tuple[Path, ...]:
        """Roots the *model* may read from at this tier."""
        if not self.caps.model_reads_vault:
            return ()
        roots = [self.vault_root]
        if self.caps.external_roots_enabled:
            roots.extend(self.external_roots)
        return tuple(roots)

    @property
    def model_write_roots(self) -> tuple[Path, ...]:
        if not self.caps.model_writes_vault:
            return ()
        roots = [self.vault_root]
        if self.caps.external_roots_enabled:
            roots.extend(self.external_roots)
        return tuple(roots)

    @property
    def app_roots(self) -> tuple[Path, ...]:
        """Roots Protege itself may touch, independent of tier.

        The application always needs its own config. Only the vault -- never
        the tier-3 external allowlist, which exists for the model's benefit.
        """
        return (self.vault_root,)

    # -- resolution ---------------------------------------------------------

    def _resolve(self, candidate: str | os.PathLike[str], roots: Iterable[Path], what: str) -> Path:
        roots = tuple(roots)
        if not roots:
            raise PathViolation(
                f"{what} is not permitted at {self.caps.label}"
            )
        raw = PurePath(os.fspath(candidate))
        _reject_dangerous_components(raw)
        resolved = real(candidate) if raw.is_absolute() else real(self.vault_root / raw)
        for root in roots:
            if is_within(root, resolved):
                return resolved
        raise PathViolation(
            f"{what} refused: {os.fspath(candidate)!r} resolves to {resolved} which is outside "
            f"the permitted roots {[str(r) for r in roots]}"
        )

    def resolve_app(self, candidate: str | os.PathLike[str]) -> Path:
        """Resolve a path Protege itself owns (manifest, settings, tripwires)."""
        return self._resolve(candidate, self.app_roots, "application path access")

    def resolve_model_read(self, candidate: str | os.PathLike[str]) -> Path:
        return self._resolve(candidate, self.model_read_roots, "model read")

    def resolve_model_write(self, candidate: str | os.PathLike[str]) -> Path:
        return self._resolve(candidate, self.model_write_roots, "model write")

    # -- capability assertions ---------------------------------------------

    def require(self, capability: str) -> None:
        """Raise unless the named capability is available at this tier.

        Named rather than boolean so the error message can say which capability
        was missing and at which tier, which is what the UI shows the user.
        """
        value = getattr(self.caps, capability, None)
        if value is None:
            raise PathViolation(f"unknown capability {capability!r}")
        if not value:
            raise PathViolation(f"{capability} is not available at {self.caps.label}")
