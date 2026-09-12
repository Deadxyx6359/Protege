"""Running an approved skill.

**What this is and is not.** A Python subprocess is not a security boundary.
Code running as your user can read your files, spawn processes, and call the OS
directly through `ctypes` without ever touching the modules this guards. Nothing
in this file changes that, and presenting it as a sandbox in the strong sense
would be dishonest.

What actually protects the user, in descending order of strength:

1. **Skills are never auto-executed.** Authoring writes a file; running it is a
   separate, explicit act. This is the real control.
2. **Approval is bound to the file's SHA-256.** Approving a skill approves
   *that exact content*. If the model rewrites the file afterwards, the digest
   no longer matches and the approval is void -- otherwise "approve once" would
   quietly become "approve whatever this file says later".
3. **Execution requires trust tier 2.** Approval is necessary but not
   sufficient; "no shell access at the default trust tier" cannot coexist with a
   tier-0 subprocess escape hatch.
4. Then, and only then, the softer measures below: the network guard in the
   child, a scrubbed environment, a working directory outside the vault, a wall
   clock timeout, and output caps.

An OS-level firewall rule and a real container are both stronger than any of
this, and the README says so.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..schemas import ApprovedSkill, Manifest, utcnow_iso
from ..security.paths import PathPolicy, PathViolation, capabilities

RUNNER = Path(__file__).with_name("_runner.py")

DEFAULT_TIMEOUT_S = 30.0
MAX_OUTPUT_CHARS = 64_000

# Environment variables passed through to the child. Everything else is
# dropped: the parent's environment can carry tokens, proxy settings, and
# machine identifiers that a skill has no business reading.
ENV_ALLOWLIST = ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "PATHEXT", "COMSPEC", "LANG", "LC_ALL")


class SkillError(RuntimeError):
    """A skill could not be run."""


def digest_of(path: Path) -> str:
    """SHA-256 of a skill file, as stored in the approval record."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class SkillRun:
    """The outcome of one execution."""

    ok: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    timed_out: bool = False
    truncated: bool = False
    error: str = ""

    def summary(self) -> str:
        if self.error:
            return self.error
        if self.timed_out:
            return f"timed out after {self.duration_s:.1f}s"
        return f"exit code {self.exit_code} in {self.duration_s:.1f}s"


def approval_for(manifest: Manifest, policy: PathPolicy, skill_path: Path) -> ApprovedSkill:
    """Find and verify the approval covering `skill_path`.

    Raises unless there is an approval whose digest still matches the file on
    disk. This is the check that makes approval mean something.
    """
    rel = Path(skill_path).resolve().relative_to(policy.vault_root).as_posix()
    approval = manifest.skill_approval(rel)
    if approval is None:
        raise SkillError(f"{rel} has not been approved for execution")

    current = digest_of(skill_path)
    if current != approval.sha256:
        raise SkillError(
            f"{rel} has changed since it was approved.\n"
            f"  approved: {approval.sha256[:16]}...\n"
            f"  on disk:  {current[:16]}...\n"
            "Approval covers exact file content. Review the new version and approve it again."
        )
    if approval.topic and not manifest.is_unlocked(approval.topic):
        raise SkillError(
            f"{rel} was approved for topic {approval.topic!r}, which is now locked. "
            "Re-locking a topic withdraws execution rights for its skills."
        )
    return approval


def approve(manifest: Manifest, policy: PathPolicy, skill_path: Path, topic: str = "") -> Manifest:
    """Record approval for a skill's current content."""
    resolved = policy.resolve_app(skill_path)
    if not resolved.is_file():
        raise SkillError(f"no such skill file: {skill_path}")
    rel = resolved.relative_to(policy.vault_root).as_posix()
    return manifest.with_skill_approved(
        ApprovedSkill(
            path=rel,
            sha256=digest_of(resolved),
            approved_at=utcnow_iso(),
            topic=topic,
        )
    )


def revoke(manifest: Manifest, policy: PathPolicy, skill_path: Path) -> Manifest:
    resolved = Path(skill_path).resolve()
    try:
        rel = resolved.relative_to(policy.vault_root).as_posix()
    except ValueError:
        rel = Path(skill_path).as_posix()
    return manifest.with_skill_revoked(rel)


def run_skill(
    manifest: Manifest,
    policy: PathPolicy,
    skill_path: Path,
    *,
    args: Sequence[str] = (),
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_output: int = MAX_OUTPUT_CHARS,
) -> SkillRun:
    """Execute an approved skill. Never raises; failures come back as a SkillRun.

    `args` becomes the skill's own `sys.argv[1:]`. Every skill in the shipped
    library is documented as `something.py <file>`, and without a way to pass
    that file they could only ever be run against themselves -- a code reviewer
    whose only subject was the code reviewer.

    The arguments come from the user through the Skills window, never from
    MAIN. A skill's *code* is what approval covers; letting the model choose
    what to point that code at would hand it a general-purpose file reader that
    nobody approved.
    """
    started = time.monotonic()
    try:
        if not capabilities(manifest.trust_tier).skill_execution:
            raise SkillError(
                f"skill execution is not available at {capabilities(manifest.trust_tier).label}. "
                "Raise the trust tier to 2 in Settings."
            )
        resolved = policy.resolve_app(skill_path)
        if not resolved.is_file():
            raise SkillError(f"no such skill file: {skill_path}")
        approval_for(manifest, policy, resolved)
    except (SkillError, PathViolation) as exc:
        return SkillRun(ok=False, error=str(exc), duration_s=time.monotonic() - started)

    env = {name: os.environ[name] for name in ENV_ALLOWLIST if name in os.environ}
    # Unbuffered so output survives a kill; no user site-packages, no
    # environment-driven import paths.
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    with tempfile.TemporaryDirectory(prefix="akira-skill-") as workdir:
        try:
            completed = subprocess.run(
                # -I: isolated mode. Ignores PYTHON* env vars and the user site
                # directory, so a skill cannot be fed a doctored module by
                # anything that has touched the environment.
                [sys.executable, "-I", str(RUNNER), str(resolved), *map(str, args)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                cwd=workdir,
                env=env,
                # Never inherit the parent's stdin: a skill that reads from it
                # would block forever behind a GUI with no console.
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            return SkillRun(
                ok=False,
                timed_out=True,
                stdout=_clip(exc.stdout, max_output)[0],
                stderr=_clip(exc.stderr, max_output)[0],
                duration_s=time.monotonic() - started,
                error=f"skill exceeded its {timeout_s:.0f}s time limit and was terminated",
            )
        except OSError as exc:
            return SkillRun(ok=False, error=f"could not start skill: {exc}",
                            duration_s=time.monotonic() - started)

    stdout, out_clipped = _clip(completed.stdout, max_output)
    stderr, err_clipped = _clip(completed.stderr, max_output)
    return SkillRun(
        ok=completed.returncode == 0,
        exit_code=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        duration_s=time.monotonic() - started,
        truncated=out_clipped or err_clipped,
    )


def _clip(text: str | bytes | None, limit: int) -> tuple[str, bool]:
    """Cap output size.

    A runaway `while True: print(...)` would otherwise fill memory in the parent
    process, which is a denial of service against Akira itself.
    """
    if text is None:
        return "", False
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n[... output truncated at {limit} characters ...]", True
