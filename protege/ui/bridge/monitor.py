"""Watched folders, and the notices jobs put up — the `Monitor` bridge.

A watch turns changes in a folder into events that scheduled jobs wait for (see
`protege.core.agents.monitor`). Adding one is held to `files.read` for the
folder and recorded in the activity log. The looking happens on its own thread;
this bridge only hears about it, on a queued signal.

Notices come from the `notify` action, on the scheduler's thread, and cross to
this one the same way. `noticed` is the moment to put something on screen.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Property, QObject, Signal, Slot

from protege.core.agents.monitor import Monitor, MonitorError
from protege.core.permissions import AuditLog

#: Notices kept for the list; older ones fall off the end.
MAX_NOTICES = 50

#: Who the activity log records as adding or removing a watch.
ACTOR = "person"


class MonitorBridge(QObject):
    """Folders being watched, and the notices jobs have shown."""

    watchesChanged = Signal()
    noticesChanged = Signal()

    #: title, text — once per notice, as it arrives.
    noticed = Signal(str, str)

    #: Private: from the looking thread, or a job, to this one.
    _changed = Signal()
    _notice = Signal(str, str)

    def __init__(self, monitor: Monitor, *, audit: AuditLog,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._monitor = monitor
        self._audit = audit
        self._notices: list[dict] = []
        self._changed.connect(self.watchesChanged)
        self._notice.connect(self._on_notice)

    @property
    def monitor(self) -> Monitor:
        return self._monitor

    def changed(self) -> None:
        """For the monitor. Safe from any thread."""
        self._changed.emit()

    def notify(self, title: str, text: str) -> None:
        """For the `notify` action. Safe from any thread."""
        self._notice.emit(title, text)

    # -- watches ------------------------------------------------------------------------------

    @Property("QVariantList", notify=watchesChanged)
    def watches(self) -> list:
        """Each watch: `id`, `folder`, `patterns`, `paused` (why it is not being
        looked at, or ""), and `lastChange` (epoch seconds, 0 if never)."""
        return [{"id": w.id, "folder": w.folder, "patterns": list(w.patterns),
                 "paused": w.paused, "lastChange": self._monitor.last_change.get(w.id, 0.0)}
                for w in self._monitor.watches()]

    @Property("QVariantList", notify=watchesChanged)
    def warnings(self) -> list:
        return self._monitor.warnings

    @Slot(str, "QVariantList", result=str)
    def addWatch(self, folder: str, patterns: list) -> str:
        """Watch a folder, optionally only files matching `patterns` such as
        `*.pdf`. Returns "" or why not."""
        try:
            watch = self._monitor.add(folder, patterns or ())
        except MonitorError as exc:
            return str(exc)
        self._audit.tool_call(ACTOR, "watch_folder", {"folder": watch.folder,
                                                      "patterns": list(watch.patterns)},
                              allowed=True, capability="files.read", scope=watch.folder)
        return ""

    @Slot(str, result=str)
    def removeWatch(self, watch_id: str) -> str:
        if not self._monitor.remove(watch_id):
            return "That folder is not being watched."
        return ""

    # -- notices ------------------------------------------------------------------------------

    @Property("QVariantList", notify=noticesChanged)
    def notices(self) -> list:
        """Newest first: `title`, `text`, `at` (epoch seconds)."""
        return list(self._notices)

    @Slot()
    def clearNotices(self) -> None:
        self._notices.clear()
        self.noticesChanged.emit()

    @Slot(str, str)
    def _on_notice(self, title: str, text: str) -> None:
        self._notices.insert(0, {"title": title, "text": text, "at": time.time()})
        del self._notices[MAX_NOTICES:]
        self.noticesChanged.emit()
        self.noticed.emit(title, text)
