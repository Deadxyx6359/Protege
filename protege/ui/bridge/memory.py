"""Notes distilled from conversations, waiting for a person — the `Memory` bridge.

The nightly job (`protege.core.brain.distil`) proposes; this is where someone
decides. Nothing reaches the vault until `accept` is called, and `accept` is held
to the permission to write that note, checked when it is pressed and recorded in
the audit log.

As with every bridge, work started here runs off the UI thread and comes back on
a queued signal; the job's own thread only ever emits.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from protege.core.brain import Vault, VaultError
from protege.core.brain.distil import (DISTIL_ACTION, PendingStore, accept, ensure_distil_job,
                                       preview, vault_of)
from protege.core.permissions import AuditLog, Policy
from protege.core.schedule import Scheduler
from protege.security.paths import PathViolation, real

#: Who the audit log records as accepting a note.
ACTOR = "person"


class MemoryBridge(QObject):
    """Choose the vault, run distillation, and accept or reject what it proposes."""

    pendingChanged = Signal()
    vaultChanged = Signal()
    busyChanged = Signal()

    #: Private: from the job's thread, or a run started here, to this one.
    _proposed = Signal()
    _ran = Signal(str)

    def __init__(self, scheduler: Scheduler, *, policy: Callable[[], Policy], audit: AuditLog,
                 pending: PendingStore | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._scheduler = scheduler
        self._policy = policy
        self._audit = audit
        self._pending = pending if pending is not None else PendingStore()
        self._busy = False
        self._last = ""
        self._proposed.connect(self.pendingChanged)
        self._ran.connect(self._on_ran)

    def on_proposed(self, report=None) -> None:
        """For the distillation job. Safe from any thread."""
        self._proposed.emit()

    def _open(self) -> Vault | None:
        path = vault_of(self._scheduler)
        if not path:
            return None
        policy = self._policy()
        try:
            return Vault(path, may_read=lambda p: bool(policy.allows("vault.read", str(p))))
        except VaultError:
            return None

    # -- state ---------------------------------------------------------------------------

    @Property(str, notify=vaultChanged)
    def vault(self) -> str:
        """The vault memory is kept in. Empty until one is chosen."""
        return vault_of(self._scheduler)

    @Property("QVariantList", notify=pendingChanged)
    def pending(self) -> list:
        """Each proposal: `id`, `title`, `target` (its path in the vault), `addsTo`
        (whether it adds to an existing note), `preview` (the new note, or a diff
        of the addition), `sources` (conversation titles) and `created`."""
        vault = self._open()
        return [{"id": p.id, "title": p.title, "target": p.target, "addsTo": p.adds_to,
                 "preview": preview(p, vault) if vault is not None else p.body,
                 "sources": [str(s.get("title", "")) for s in p.sources],
                 "project": next((str(s["project"]) for s in p.sources if s.get("project")), ""),
                 "created": p.created}
                for p in self._pending.all()]

    @Property(int, notify=pendingChanged)
    def pendingCount(self) -> int:
        return len(self._pending.all())

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=busyChanged)
    def lastRun(self) -> str:
        """What the last run started here found, in a sentence."""
        return self._last

    # -- choosing and running ----------------------------------------------------------------

    @Slot(str, result=str)
    def setVault(self, path: str) -> str:
        """Keep memory in this vault. Returns "" or why not.

        Sets up the nightly job. It still reads only with the permissions to
        read conversations and the vault, which the person grants separately.
        """
        text = path.strip()
        if not text:
            return "Choose the vault to keep memory in."
        try:
            folder = real(text)
        except (PathViolation, OSError, ValueError) as exc:
            return f"{text} cannot be used: {exc}"
        if not folder.is_dir():
            return f"{text} is not a folder."
        ensure_distil_job(self._scheduler, str(folder))
        self.vaultChanged.emit()
        self.pendingChanged.emit()
        return ""

    @Slot(result=str)
    def distilNow(self) -> str:
        """Read recent conversations now rather than tonight. Returns "" or why not."""
        jobs = self._scheduler.find(DISTIL_ACTION)
        if not jobs:
            return "Choose a vault first."
        if self._busy:
            return "Already reading conversations."
        self._busy = True
        self.busyChanged.emit()
        threading.Thread(target=self._run, args=(jobs[0].id,), name="memory", daemon=True).start()
        return ""

    def _run(self, job_id: str) -> None:
        """Worker thread. Emits a signal; touches no Qt property."""
        try:
            record = self._scheduler.run_now(job_id)
            self._ran.emit(record.summary if record is not None else "The memory job has gone.")
        except Exception as exc:  # noqa: BLE001 - a crashed run must still report back
            self._ran.emit(f"{type(exc).__name__}: {exc}")

    def _on_ran(self, summary: str) -> None:
        self._busy, self._last = False, summary
        self.busyChanged.emit()
        self.pendingChanged.emit()

    # -- deciding ----------------------------------------------------------------------------

    @Slot(str, result=str)
    def accept(self, proposal_id: str) -> str:
        """Write a proposal into the vault. Returns "" or why it was not written."""
        proposal = self._pending.get(proposal_id)
        if proposal is None:
            return "That proposal is no longer waiting."
        root = vault_of(self._scheduler)
        if not root:
            return "Choose a vault first."
        target = str(Path(root) / proposal.target)
        policy = self._policy()
        decision = policy.allows("vault.write", target)
        if not decision:
            self._audit.tool_call(ACTOR, "accept_memory", {"target": proposal.target},
                                  allowed=False, capability="vault.write", scope=target,
                                  error=decision.reason)
            return f"Not permitted: {decision.reason}."
        try:
            vault = Vault(root, may_read=lambda p: bool(policy.allows("vault.read", str(p))))
            accept(self._pending, proposal_id, vault)
        except VaultError as exc:
            # A conflict re-bases the proposal, so what is shown has changed too.
            self.pendingChanged.emit()
            return str(exc)
        self._audit.tool_call(ACTOR, "accept_memory", {"target": proposal.target},
                              allowed=True, capability="vault.write", scope=target)
        self.pendingChanged.emit()
        return ""

    @Slot(str, result=str)
    def reject(self, proposal_id: str) -> str:
        """Discard a proposal. The conversation it came from is untouched."""
        if not self._pending.remove(proposal_id):
            return "That proposal is no longer waiting."
        self.pendingChanged.emit()
        return ""
