"""The tag map and the link graph — the `Graph` bridge.

`build(folder, width, height)` reads the vault holding `folder`, limited to the
notes under it, with the grants work started from the interface runs under: the
global ones and the open project's. The reading happens off the UI thread and
comes back as plain data — the tag map already laid out for a canvas that size,
and the link graph as nodes and edges. Nothing is written.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from protege.core.brain import Vault, find_root
from protege.core.brain.graph import layout, link_graph, tag_map
from protege.core.permissions import AuditLog, Policy
from protege.security.paths import PathViolation, real

#: Who the activity log records as asking for the map.
ACTOR = "person"


class GraphBridge(QObject):
    """Draw what a folder of notes knows."""

    builtChanged = Signal()
    busyChanged = Signal()

    #: Private: carries a finished build from the worker thread to this one.
    _done = Signal(object)

    def __init__(self, *, policy: Callable[[], Policy], audit: AuditLog,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._policy = policy
        self._audit = audit
        self._busy = False
        self._tags: dict = {}
        self._links: dict = {}
        self._error = ""
        self._done.connect(self._on_done)

    @Property("QVariantMap", notify=builtChanged)
    def tags(self) -> dict:
        """The tag map: `nodes` (with `x`, `y`, `radius`), `edges`, `summary`."""
        return self._tags

    @Property("QVariantMap", notify=builtChanged)
    def links(self) -> dict:
        """The link graph: `nodes`, `edges`, `unresolved`, `summary`. Not laid out."""
        return self._links

    @Property(str, notify=builtChanged)
    def error(self) -> str:
        return self._error

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Slot(str, float, float, result=str)
    def build(self, folder: str, width: float, height: float) -> str:
        """Read \a folder and draw it. Returns "" once started, or why not."""
        text = folder.strip()
        if not text:
            return "Choose a folder of notes."
        try:
            path = real(text)
        except (PathViolation, OSError, ValueError) as exc:
            return f"{text} cannot be used: {exc}"
        if not path.is_dir():
            return f"{text} is not a folder."
        policy = self._policy()
        decision = policy.allows("vault.read", str(path))
        if not decision:
            self._audit.tool_call(ACTOR, "draw_map", {"folder": str(path)}, allowed=False,
                                  capability="vault.read", scope=str(path),
                                  error=decision.reason)
            return f"Not permitted: {decision.reason}."
        if self._busy:
            return "Already drawing the map."
        self._audit.tool_call(ACTOR, "draw_map", {"folder": str(path)}, allowed=True,
                              capability="vault.read", scope=str(path))
        self._busy = True
        self.busyChanged.emit()
        threading.Thread(target=self._work, args=(path, policy, width, height),
                         name="graph", daemon=True).start()
        return ""

    def _work(self, folder: Path, policy: Policy, width: float, height: float) -> None:
        """Worker thread. Emits a signal; touches no Qt property."""
        try:
            vault = Vault(find_root(folder) or folder,
                          may_read=lambda p: bool(policy.allows("vault.read", str(p))))
            tags = layout(tag_map(vault, folder), width, height).to_json()
            self._done.emit((tags, link_graph(vault, folder).to_json(), ""))
        except Exception as exc:  # noqa: BLE001 - a failed build must still report back
            self._done.emit(({}, {}, f"{type(exc).__name__}: {exc}"))

    def _on_done(self, result) -> None:
        self._tags, self._links, self._error = result
        self._busy = False
        self.busyChanged.emit()
        self.builtChanged.emit()
