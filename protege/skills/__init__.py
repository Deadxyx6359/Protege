"""Skill authoring and execution.

Authoring is gated by the lock system; execution is gated by explicit per-skill
approval bound to a content digest, plus trust tier 2. Read the candid note at
the top of `sandbox.py` about what a Python subprocess does and does not
protect against.
"""

from .author import AuthoredSkill, SkillAuthor, SkillAuthoringError
from .sandbox import SkillError, SkillRun, approve, digest_of, revoke, run_skill

__all__ = [
    "AuthoredSkill",
    "SkillAuthor",
    "SkillAuthoringError",
    "SkillError",
    "SkillRun",
    "approve",
    "digest_of",
    "revoke",
    "run_skill",
]
