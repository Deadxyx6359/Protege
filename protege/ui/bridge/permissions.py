"""The permission screen and the confirmation dialog, as QML sees them.

Two objects live here and they answer different questions. `PermissionsBridge`
is *what may be attempted* — the catalogue, the grants, and the record of what
was done with them. `ConfirmBridge` is *may this one thing happen now*, which a
grant never settles on its own.

## The confirmation is the interesting part

`ToolContext.confirm` is an ordinary synchronous callable returning a bool, and
the tool registry calls it from whichever thread the agent is running on —
never the main one. The dialog it has to raise lives on the main thread. So the
worker has to ask, block, and be woken by an answer that arrives from somewhere
else entirely.

Three ways that goes wrong, all of them guarded here:

  * **Asking from the main thread deadlocks the application.** The wait blocks
    the event loop, so the dialog it is waiting for can never render, and the
    window is frozen until the timeout expires. `ask` therefore refuses outright
    when it is called on the thread that owns the UI: it answers *no* and says
    why, which is a denied write rather than a hung app.
  * **Nobody answers.** A dialog dismissed by a window manager, or an agent
    still running while the interface is being torn down, would leave the
    worker parked forever holding a model. There is a timeout, and it expires
    to *no*.
  * **The answer arrives twice, or late, or for a request that is gone.** Each
    request carries a token and is removed from the pending table the moment it
    is answered, so a second answer finds nothing and does nothing.

Every path that is not an explicit approval resolves to **no**. That is the
same promise `ToolContext.confirm` makes by defaulting to `lambda summary:
False`, kept across a thread boundary.
"""

from __future__ import annotations

import secrets
import threading

from PySide6.QtCore import Property, QObject, Signal, Slot

from protege.core.permissions import CATALOGUE, AuditLog, Policy
from protege.core.permissions.capabilities import get

#: How long a worker waits for a person before giving up and treating silence
#: as refusal. Long enough to read a summary and think; short enough that a
#: forgotten dialog does not park an agent overnight.
CONFIRM_TIMEOUT_S = 300.0


class ConfirmBridge(QObject):
    """Asks a person to approve one irreversible action, across threads."""

    #: token, summary. QML connects this and raises the dialog.
    requested = Signal(str, str)

    #: token — the request is no longer waiting (answered, timed out, or the
    #: application is closing). QML uses it to take a stale dialog down.
    withdrawn = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending: dict[str, tuple[threading.Event, list]] = {}
        self._lock = threading.Lock()
        self._closing = False
        # The thread this object was built on is the one QML runs on. Recorded
        # rather than assumed so the guard in `ask` cannot be fooled by an
        # object constructed somewhere unusual.
        self._ui_thread = threading.get_ident()

    # -- the worker side ----------------------------------------------------

    def ask(self, summary: str) -> bool:
        """Block until a person answers. Anything other than yes is no.

        This is the callable handed to `ToolContext.confirm`.
        """
        if self._closing:
            return False

        if threading.get_ident() == self._ui_thread:
            # Waiting here would block the event loop that has to draw the
            # dialog. Refusing is the only answer that leaves a usable window.
            return False

        token = secrets.token_hex(8)
        answered = threading.Event()
        box = [False]

        with self._lock:
            if self._closing:
                return False
            self._pending[token] = (answered, box)

        self.requested.emit(token, summary)

        if not answered.wait(CONFIRM_TIMEOUT_S):
            with self._lock:
                self._pending.pop(token, None)
            self.withdrawn.emit(token)
            return False

        return bool(box[0])

    # -- the QML side -------------------------------------------------------

    @Slot(str, bool)
    def answer(self, token: str, approved: bool) -> None:
        """Called from QML when a person clicks. A stale token does nothing."""
        with self._lock:
            entry = self._pending.pop(token, None)
        if entry is None:
            return
        answered, box = entry
        box[0] = bool(approved)
        answered.set()

    @Property(int, constant=True)
    def timeoutSeconds(self) -> int:
        return int(CONFIRM_TIMEOUT_S)

    @Slot()
    def close(self) -> None:
        """Wake every waiting worker with a refusal. Call before shutdown."""
        self._closing = True
        with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for token, (answered, box) in pending:
            box[0] = False
            answered.set()
            self.withdrawn.emit(token)

    @Property(int, constant=True)
    def pendingCount(self) -> int:
        with self._lock:
            return len(self._pending)


class PermissionsBridge(QObject):
    """The capability catalogue and the grants held against it."""

    grantsChanged = Signal()

    def __init__(self, policy: Policy | None = None,
                 audit: AuditLog | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._policy = policy if policy is not None else Policy.load()
        self._audit = audit if audit is not None else AuditLog()

    @property
    def policy(self) -> Policy:
        """The live policy. Tool contexts are built against this object."""
        return self._policy

    # -- the catalogue ------------------------------------------------------

    @Property("QVariantList", constant=True)
    def catalogue(self) -> list:
        """Every capability, as plain dictionaries QML can repeat over.

        `leavesMachine` is carried separately from risk on purpose: it is the
        property most people actually care about, and it does not follow from
        read versus write.
        """
        return [self._describe(capability_id) for capability_id in sorted(CATALOGUE)]

    def _describe(self, capability_id: str) -> dict:
        capability = get(capability_id)
        grant = self._policy.granted(capability_id)
        return {
            "id": capability.id,
            "title": capability.title,
            "summary": capability.summary,
            "domain": capability.domain,
            "direction": capability.direction.value,
            "risk": capability.risk.value,
            "scopeKind": capability.scope.value,
            "irreversible": capability.irreversible,
            "leavesMachine": capability.leaves_machine,
            "granted": grant is not None,
            "scopes": list(grant.scopes) if grant else [],
        }

    @Slot(str, result="QVariantMap")
    def describe(self, capability_id: str) -> dict:
        try:
            return self._describe(capability_id)
        except KeyError:
            return {}

    @Property("QVariantList", notify=grantsChanged)
    def grants(self) -> list:
        return [
            {"id": grant.capability, "scopes": list(grant.scopes),
             "expires": grant.expires or 0}
            for grant in self._policy.active()
        ]

    # -- changing them ------------------------------------------------------

    @Slot(str, "QVariantList", result=str)
    def grant(self, capability_id: str, scopes: list) -> str:
        """Grant a capability. Returns "" on success, or why it was refused.

        A scoped capability with no scope is refused rather than quietly
        granted everywhere — that would turn "read this folder" into "read the
        disk", which is the exact mistake the scope exists to prevent.
        """
        try:
            self._policy.grant(capability_id, tuple(str(s) for s in scopes))
        except (KeyError, ValueError) as exc:
            return str(exc) or "that capability cannot be granted like that"
        self._policy.save()
        self.grantsChanged.emit()
        return ""

    @Slot(str)
    def revoke(self, capability_id: str) -> None:
        self._policy.revoke(capability_id)
        self._policy.save()
        self.grantsChanged.emit()

    @Slot()
    def revokeAll(self) -> None:
        self._policy.revoke_all()
        self._policy.save()
        self.grantsChanged.emit()

    # -- the record ---------------------------------------------------------

    @Slot(int, result="QVariantList")
    def recentActivity(self, limit: int = 200) -> list:
        """The audit log, newest first.

        Refusals are included and must stay included: the pattern of what an
        agent *tried* is the part worth looking at.
        """
        try:
            events = self._audit.read()
        except Exception:  # noqa: BLE001 - an unreadable log is not a crash
            return []
        rows = [
            {"at": event.at, "actor": event.actor, "action": event.action,
             "allowed": event.allowed, "detail": event.error or ""}
            for event in events[-max(1, limit):]
        ]
        rows.reverse()
        return rows
