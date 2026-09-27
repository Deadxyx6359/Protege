"""Asking the person, there and then, for a site or a folder a grant does not cover.

A grant to read wikipedia.org says nothing about bbc.co.uk. An agent that
reached bbc.co.uk used to stop; the person went to Settings, allowed the site,
and started the work again. Now the person is asked in place: allow it once,
for this piece of work; always, which adds it to the grant; or no.

What may be asked for is narrow on purpose:

  * Only reading, and only a capability already granted somewhere: a site
    under `net.http`, a folder under `files.read`, `docs.read`, `vault.read`
    or `vcs.read`. With no grant at all the tool is not offered, so nothing
    here allows something new in kind.
  * A web page only when its address came from this piece of work: the
    person's own words, a search result, or a page already read. An address
    the model wrote itself is refused as before, without asking: that is the
    address that could carry what was read to somewhere it should not go.
  * Never somewhere secret: Akira's own settings, application data, a folder
    of keys such as .ssh, or a whole drive or home folder.
  * A few times per piece of work, and never twice for the same thing. Asked
    again and again, anyone stops reading and says yes.

Silence, a closed window, or no way to ask all mean no.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from akira.core.config import config_dir
from akira.security.paths import PathViolation, real, reject_dangerous

from . import capabilities as caps
from .model import _MATCHERS, Decision, Grant, Policy

if TYPE_CHECKING:
    from akira.core.tools.schema import ToolContext

#: What may be asked for in place. Reading only.
ASKABLE = frozenset({"net.http", "files.read", "docs.read", "vault.read", "vcs.read"})

#: The most a piece of work asks. After that it is refused, as before.
MAX_ASKS = 6

ONCE, ALWAYS, NO = "once", "always", "no"

#: Where the addresses a piece of work came across are kept, in `ToolContext.extra`.
SEEN = "seen_addresses"
_ASKED = "asked_in_place"

#: Said when an address came from nowhere: the agent can still find the page.
SEARCH_FIRST = "find the page through web_search first"

_ADDRESS = re.compile(r"https://[^\s<>\"'`\])}]+", re.IGNORECASE)

#: Folders under the home folder that hold keys and sign-ins.
_SECRET_FOLDERS = frozenset({".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker",
                             ".config", ".password-store", "appdata"})


@dataclass(frozen=True)
class Request:
    """One question for the person."""

    capability: str
    scope: str
    """What this piece of work asked for: a site, or a file or folder."""
    detail: str
    """The page's address, or the path, in full."""
    always: str
    """What "always" adds to the grant: the site, or the folder."""
    actor: str
    why: str
    """What the tool was doing, in a line."""

    @property
    def title(self) -> str:
        if self.capability == "net.http":
            return f"Read a page on {self.scope}?"
        return f"Read {Path(self.detail).name or self.detail}?"


#: What `ToolContext.ask_scope` is: a request in, `ONCE`, `ALWAYS` or `NO` out.
AskScope = Callable[[Request], str]


class Allowances(Policy):
    """A policy, and what the person allowed once for this piece of work. Read-only."""

    def __init__(self, inner: Policy) -> None:
        super().__init__()
        self.inner = inner
        self._once: list[tuple[str, str]] = []

    def add(self, capability_id: str, scope: str) -> None:
        self._once.append((capability_id, scope))

    def allows(self, capability_id: str, scope: str | None = None) -> Decision:
        decision = self.inner.allows(capability_id, scope)
        if decision or scope is None or self.inner.granted(capability_id) is None:
            return decision
        matcher = _MATCHERS[caps.get(capability_id).scope]
        if any(held == capability_id and matcher(allowed, scope)
               for held, allowed in self._once):
            return Decision(True, capability_id, scope, "")
        return decision

    def granted(self, capability_id: str) -> Grant | None:
        grant = self.inner.granted(capability_id)
        extra = tuple(s for held, s in self._once if held == capability_id)
        if grant is None or not extra:
            return grant
        return Grant(grant.capability, tuple(dict.fromkeys((*grant.scopes, *extra))),
                     grant.granted, grant.expires, grant.note)

    def active(self) -> list[Grant]:
        return [g for g in map(self.granted, (g.capability for g in self.inner.active()))
                if g is not None]

    def _read_only(self, *_args, **_kwargs):
        raise RuntimeError("what is allowed once is not saved; grant in Settings instead")

    grant = revoke = revoke_all = save = _read_only


# -- where an address came from ---------------------------------------------------------------


def note_seen(context: "ToolContext", text: str) -> None:
    """Remember the web addresses in \a text: the person's words or what a tool returned."""
    if not text or "https://" not in text.lower():
        return
    seen = context.extra.setdefault(SEEN, set())
    for found in _ADDRESS.findall(text):
        seen.add(_plain(found))


def _plain(address: str) -> str:
    return address.rstrip(".,;:!?'\"").split("#", 1)[0]


def came_across(context: "ToolContext", address: str) -> bool:
    return _plain(address) in context.extra.get(SEEN, ())


# -- where it is safe to ask about -----------------------------------------------------------


def secret_place(path: str) -> str:
    """Why \a path is never asked about, or "" when it may be."""
    try:
        reject_dangerous(path)
        target = real(path)
    except (PathViolation, OSError, ValueError):
        return "it is not a usable path"
    if target.parent == target:
        return "it is a whole drive"
    home = real(Path.home())
    if target == home or target == home.parent:
        return "it is a whole home folder"
    settings = real(config_dir())
    if target == settings or settings in target.parents:
        return "it is where Akira keeps its own settings"
    try:
        inside = target.relative_to(home).parts
    except ValueError:
        inside = ()
    if inside and inside[0].lower() in _SECRET_FOLDERS:
        return f"{inside[0]} holds keys, sign-ins or application data"
    return ""


def _site(host: str) -> str:
    """The site a host is on, as a grant names it: www.bbc.co.uk is bbc.co.uk."""
    host = host.strip().lower().strip(".")
    return host[4:] if host.startswith("www.") and host.count(".") >= 2 else host


def request_for(context: "ToolContext", capability: str, scope: str | None, *,
                detail: str, why: str) -> tuple[Request | None, str]:
    """The question to ask for this refused scope, or None and why not."""
    if capability not in ASKABLE or not scope:
        return None, ""
    if context.ask_scope is None:
        return None, ""
    if context.policy.granted(capability) is None:
        return None, ""
    asked = context.extra.setdefault(_ASKED, {})
    if (capability, scope) in asked:
        return None, "" if asked[(capability, scope)] else "the person said no to it"
    if len(asked) >= MAX_ASKS:
        return None, "the person has been asked enough times in this piece of work"

    if capability == "net.http":
        host = scope.strip().lower()
        if "." not in host or any(mark in host for mark in "/:*@\\ \t"):
            return None, ""
        if not came_across(context, detail):
            return None, ("the person is asked about a site only for an address that came "
                          "from their own words, a search result or a page already read: "
                          + SEARCH_FIRST)
        return Request(capability, host, _plain(detail), _site(host), context.actor, why), ""

    why_not = secret_place(scope)
    if why_not:
        return None, f"it is not asked about, because {why_not}"
    folder = scope
    try:
        if Path(scope).is_file():
            folder = str(Path(scope).parent)
    except OSError:
        pass
    if secret_place(folder):
        folder = scope
    return Request(capability, scope, scope, folder, context.actor, why), ""


def ask_in_place(context: "ToolContext", capability: str, scope: str | None, *,
                 detail: str = "", why: str = "") -> tuple[bool, str]:
    """Ask the person to allow \a scope for \a capability. True when they did.

    The second value says why nobody was asked, for the refusal the agent is
    given, or is "" when there is nothing to add.
    """
    request, why_not = request_for(context, capability, scope, detail=detail or scope or "",
                                   why=why)
    if request is None:
        return False, why_not
    asked = context.extra[_ASKED]
    try:
        answer = str(context.ask_scope(request))
    except Exception:  # noqa: BLE001 - a broken prompt must mean "no"
        answer = NO
    allowed = answer in (ONCE, ALWAYS)
    asked[(capability, request.scope)] = allowed
    context.audit.confirmation(
        context.actor, f"allow {capability}", approved=allowed,
        summary=f"{request.title} {request.detail} ({answer})")
    if not allowed:
        return False, "the person said no to it"
    if not isinstance(context.policy, Allowances):
        context.policy = Allowances(context.policy)
    context.policy.add(capability, request.scope)
    return True, ""


def widen(policy: Policy, capability: str, scope: str) -> None:
    """Add \a scope to \a policy's grant of \a capability, keeping when it expires."""
    grant = policy.granted(capability)
    if grant is None:
        raise ValueError(f"{capability} is not granted there")
    if scope in grant.scopes:
        return
    policy.grant(capability, (*grant.scopes, scope), expires=grant.expires, note=grant.note)


__all__ = ["ALWAYS", "ASKABLE", "Allowances", "AskScope", "MAX_ASKS", "NO", "ONCE", "Request", "SEARCH_FIRST",
           "ask_in_place", "came_across", "note_seen", "request_for", "secret_place", "widen"]
