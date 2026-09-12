"""Watched folders, pages and feeds, and the notices jobs put up — the `Monitor` bridge.

A watch turns changes into events that scheduled jobs wait for (see
`akira.core.agents.monitor`). Adding one is held to its permission,
`files.read` for a folder and `net.http` for a page's or a feed's site, and
recorded in the activity log. The looking happens on its own thread; this
bridge only hears about it, on a queued signal.

Notices come from the `notify` action, on the scheduler's thread, and cross to
this one the same way. `noticed` is the moment to put something on screen. A
notice can quote a web page or a feed, so its text is shown as plain text.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Property, QObject, Signal, Slot

from akira.core.agents.monitor import FEED, FOLDER, PAGE, WEB_EVERY_S, Monitor, MonitorError
from akira.core.permissions import AuditLog

#: Notices kept for the list; older ones fall off the end.
MAX_NOTICES = 50

#: Who the activity log records as adding or removing a watch.
ACTOR = "person"


class MonitorBridge(QObject):
    """What is being watched, and the notices jobs have shown."""

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
        """Each watch: `id`, `kind` (`folder`, `page` or `feed`), `folder`, `url`
        (without its query), `title` (a page's or feed's own, once looked at),
        `patterns` (file patterns for a folder, words for a page or feed),
        `every` (minutes between looks at a page or feed, 0 for a folder),
        `paused` (why it is not reporting, or ""), `lastChange` and `lastLook`
        (epoch seconds, 0 if never)."""
        rows = []
        for w in self._monitor.watches():
            web = w.kind != FOLDER
            rows.append({"id": w.id, "kind": w.kind, "folder": w.folder,
                         "url": w.target if web else "",
                         "title": self._monitor.title(w.id), "patterns": list(w.patterns),
                         "every": w.every_s // 60 if web else 0, "paused": w.paused,
                         "lastChange": self._monitor.last_change.get(w.id, 0.0),
                         "lastLook": self._monitor.looked(w.id)})
        return rows

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

    @Slot(str, "QVariantList", int, result=str)
    def addPageWatch(self, url: str, words: list, minutes: int) -> str:
        """Watch a web page for new lines, optionally only lines with one of
        `words`, looked at every `minutes` (0 for hourly). Returns "" or why not."""
        return self._add_web(PAGE, url, words, minutes)

    @Slot(str, "QVariantList", int, result=str)
    def addFeedWatch(self, url: str, words: list, minutes: int) -> str:
        """Watch an RSS or Atom feed for new entries, as `addPageWatch` does a page."""
        return self._add_web(FEED, url, words, minutes)

    def _add_web(self, kind: str, url: str, words: list, minutes: int) -> str:
        every = int(minutes) * 60 if minutes else WEB_EVERY_S
        add = self._monitor.add_page if kind == PAGE else self._monitor.add_feed
        try:
            watch = add(url, words or (), every)
        except MonitorError as exc:
            return str(exc)
        self._audit.tool_call(ACTOR, f"watch_{kind}", {"url": watch.target,
                                                       "words": list(watch.patterns),
                                                       "every": watch.every_s},
                              allowed=True, capability="net.http", scope=watch.site)
        return ""

    @Slot(str, result=str)
    def removeWatch(self, watch_id: str) -> str:
        if not self._monitor.remove(watch_id):
            return "That is not being watched."
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
