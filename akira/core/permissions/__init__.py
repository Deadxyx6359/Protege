"""Capabilities, grants, the audit log, and credential storage.

Deny by default, enforced structurally: the tool registry builds an agent's
tool list from the policy, so an ungranted capability produces no tool and
there is nothing for a jailbreak to reach for.
"""

from .audit import AuditLog, Event, redact
from .capabilities import CATALOGUE, Capability, Direction, Risk, ScopeKind, get
from .model import Decision, Grant, PermissionError_, Policy
from .secrets import SecretError, SecretStore

__all__ = [
    "AuditLog", "Event", "redact",
    "CATALOGUE", "Capability", "Direction", "Risk", "ScopeKind", "get",
    "Decision", "Grant", "PermissionError_", "Policy",
    "SecretError", "SecretStore",
]
