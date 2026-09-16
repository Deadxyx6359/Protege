"""Every distinct power the application can hold.

The catalogue is declared in one place, and deliberately not next to the tools
that use it, for two reasons:

  * the permission screen can be built from this alone. It does not need to
    know that tools exist, and it cannot fall out of step with them.
  * "what is this application able to do at all" has a single answer that can
    be read in one sitting. A capability list scattered across the code that
    uses it is not a security boundary, it is a search problem.

Nothing here grants anything. This is the vocabulary; `model.py` holds what the
user has actually allowed.

Read and write are separate capabilities throughout. "Read my email" and "send
email as me" are wildly different powers and must be grantable apart — the
inability to express read-only access is how tools end up asking for far more
than they need.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Direction(Enum):
    """Which way information flows."""

    READ = "read"
    """Observes. Cannot change anything outside Akira."""

    WRITE = "write"
    """Changes something — a file, a message, a booking, a remote record."""


class Risk(Enum):
    """How much damage a mistake under this capability can do.

    Drives how prominently the permission screen warns, and whether a grant is
    offered a default expiry. It does not weaken enforcement: a low-risk
    capability is enforced exactly as strictly as a high-risk one.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScopeKind(Enum):
    """What a grant's scope strings mean, so the UI can pick the right editor."""

    NONE = "none"
    """Unscoped: the grant is simply on or off."""

    PATH = "path"
    """Filesystem roots. A grant covers a directory and everything beneath it."""

    HOST = "host"
    """Network hostnames. Matched on the exact host or a `.suffix` parent."""

    ACCOUNT = "account"
    """A named external account — a mailbox, a bank login, a course."""

    PROVIDER = "provider"
    """A named third-party service the request is sent to."""


@dataclass(frozen=True, slots=True)
class Capability:
    """One power, as offered to the user."""

    id: str
    """Dotted, `domain.action`. Stable: grants are stored against it."""

    title: str
    """Short label for the permission screen."""

    summary: str
    """One sentence, in plain language, describing what it actually permits.
    Written for someone deciding whether to allow it, not for a developer."""

    direction: Direction
    risk: Risk
    scope: ScopeKind = ScopeKind.NONE

    #: True when actions under this capability can be impossible to undo.
    #: Such actions confirm individually, every time, regardless of the grant.
    #: The grant says the agent *may* try; the confirmation is still required.
    irreversible: bool = False

    #: True when exercising this sends data off the machine. Surfaced
    #: separately because it is the property most people actually care about,
    #: and it does not follow from read/write.
    leaves_machine: bool = False

    @property
    def domain(self) -> str:
        return self.id.split(".", 1)[0]


def _c(*args, **kwargs) -> Capability:
    return Capability(*args, **kwargs)


CATALOGUE: dict[str, Capability] = {
    c.id: c
    for c in (
        # -- the machine ---------------------------------------------------
        _c("files.read", "Read files",
           "Open and read files in folders you choose.",
           Direction.READ, Risk.MEDIUM, ScopeKind.PATH),
        _c("files.write", "Write files",
           "Create, change and move files in folders you choose.",
           Direction.WRITE, Risk.HIGH, ScopeKind.PATH, irreversible=True),
        _c("shell.run", "Run commands",
           "Run programs and scripts on this computer.",
           Direction.WRITE, Risk.HIGH, ScopeKind.PATH, irreversible=True),
        # High, though it only reads: a screenshot shows whatever is open, and
        # that can be a password being typed or a bank balance.
        _c("screen.capture", "See your screen",
           "Take screenshots and read the words on them: everything that is open.",
           Direction.READ, Risk.HIGH),
        _c("clipboard.read", "Read the clipboard",
           "Read whatever you last copied.",
           Direction.READ, Risk.MEDIUM),
        _c("clipboard.write", "Write the clipboard",
           "Replace the clipboard contents.",
           Direction.WRITE, Risk.LOW),
        _c("location.read", "Know where you are",
           "Use this computer's approximate location and time zone.",
           Direction.READ, Risk.MEDIUM),
        _c("audio.record", "Listen",
           "Use the microphone, for dictation and calls.",
           Direction.READ, Risk.HIGH),
        _c("audio.play", "Speak",
           "Play audio through the speakers.",
           Direction.WRITE, Risk.LOW),
        _c("notify.send", "Send notifications",
           "Show desktop notifications.",
           Direction.WRITE, Risk.LOW),

        # -- your own knowledge --------------------------------------------
        _c("vault.read", "Read your notes",
           "Read the Obsidian vault.",
           Direction.READ, Risk.MEDIUM, ScopeKind.PATH),
        _c("vault.write", "Write your notes",
           "Add and edit notes in the Obsidian vault.",
           Direction.WRITE, Risk.MEDIUM, ScopeKind.PATH),
        _c("memory.read", "Remember past conversations",
           "Search your earlier conversations for what was said.",
           Direction.READ, Risk.MEDIUM),
        _c("docs.read", "Read documents",
           "Read Word, Excel, PowerPoint and PDF files.",
           Direction.READ, Risk.MEDIUM, ScopeKind.PATH),
        _c("docs.write", "Write documents",
           "Create and edit Word, Excel and PowerPoint files.",
           Direction.WRITE, Risk.MEDIUM, ScopeKind.PATH, irreversible=True),

        # -- version control -----------------------------------------------
        _c("vcs.read", "Read repositories",
           "Inspect git history, branches and diffs.",
           Direction.READ, Risk.LOW, ScopeKind.PATH),
        _c("vcs.write", "Change repositories",
           "Commit, branch and push. Pushing publishes your work.",
           Direction.WRITE, Risk.HIGH, ScopeKind.PATH,
           irreversible=True, leaves_machine=True),

        # -- the network ---------------------------------------------------
        _c("web.search", "Search the web",
           "Send search queries to DuckDuckGo, and nowhere else.",
           Direction.READ, Risk.MEDIUM, leaves_machine=True),
        _c("net.http", "Fetch web pages",
           "Request pages and data from sites you allow.",
           Direction.READ, Risk.MEDIUM, ScopeKind.HOST, leaves_machine=True),
        _c("web.browse", "Drive a browser",
           "Open pages from sites you allow in a real browser and read them. Like any "
           "browser, it loads what a page needs from other sites.",
           Direction.READ, Risk.HIGH, ScopeKind.HOST, leaves_machine=True),
        _c("web.submit", "Fill in and submit forms",
           "Enter information into web forms and send it.",
           Direction.WRITE, Risk.HIGH, ScopeKind.HOST,
           irreversible=True, leaves_machine=True),

        # -- talking to people ---------------------------------------------
        _c("mail.read", "Read email",
           "Read messages in mailboxes you choose.",
           Direction.READ, Risk.HIGH, ScopeKind.ACCOUNT, leaves_machine=True),
        _c("mail.send", "Send email",
           "Send email from your address.",
           Direction.WRITE, Risk.HIGH, ScopeKind.ACCOUNT,
           irreversible=True, leaves_machine=True),
        _c("messages.read", "Read messages",
           "Read texts and chat messages.",
           Direction.READ, Risk.HIGH, ScopeKind.ACCOUNT, leaves_machine=True),
        _c("messages.send", "Send messages",
           "Send texts and chat messages as you.",
           Direction.WRITE, Risk.HIGH, ScopeKind.ACCOUNT,
           irreversible=True, leaves_machine=True),
        _c("calendar.read", "Read your calendar",
           "See your events and free time.",
           Direction.READ, Risk.MEDIUM, ScopeKind.ACCOUNT, leaves_machine=True),
        _c("calendar.write", "Change your calendar",
           "Create, move and cancel events.",
           Direction.WRITE, Risk.MEDIUM, ScopeKind.ACCOUNT,
           irreversible=True, leaves_machine=True),

        # -- study ----------------------------------------------------------
        _c("lms.read", "Read your courses",
           "Read Canvas courses, assignments and grades.",
           Direction.READ, Risk.MEDIUM, ScopeKind.ACCOUNT, leaves_machine=True),
        _c("lms.write", "Submit coursework",
           "Submit assignments and post to course discussions.",
           Direction.WRITE, Risk.HIGH, ScopeKind.ACCOUNT,
           irreversible=True, leaves_machine=True),

        # -- money ------------------------------------------------------------
        #
        # Read only, and there is deliberately no matching write. Reading
        # balances and transactions is a reasonable thing to automate. Moving
        # money is not, and no capability exists for it — so no tool can ask
        # for one, and no jailbreak can invent one. See PLATFORM.md.
        _c("bank.read", "Read account balances",
           "See balances and transactions. Cannot move money.",
           Direction.READ, Risk.HIGH, ScopeKind.ACCOUNT, leaves_machine=True),

        # -- models ------------------------------------------------------------
        _c("model.cloud", "Use cloud models",
           "Send your conversation to a third-party model provider.",
           Direction.WRITE, Risk.HIGH, ScopeKind.PROVIDER, leaves_machine=True),
    )
}
"""Every capability, keyed by id. The single answer to "what can this do"."""


def get(capability_id: str) -> Capability:
    """Look one up, refusing anything not declared.

    Unknown ids are a programming error rather than a permission question:
    a tool that asks for a capability nobody declared must not quietly be
    treated as either allowed or denied.
    """
    try:
        return CATALOGUE[capability_id]
    except KeyError:
        raise KeyError(
            f"no such capability: {capability_id!r}. "
            "Capabilities must be declared in capabilities.py before use."
        ) from None


def by_domain() -> dict[str, list[Capability]]:
    """Grouped for display, domains in catalogue order."""
    groups: dict[str, list[Capability]] = {}
    for capability in CATALOGUE.values():
        groups.setdefault(capability.domain, []).append(capability)
    return groups


#: Capabilities that send something off this machine. The permission screen
#: shows these together, because "does this leave my computer" is the question
#: people actually ask.
def leaving_machine() -> list[Capability]:
    return [c for c in CATALOGUE.values() if c.leaves_machine]
