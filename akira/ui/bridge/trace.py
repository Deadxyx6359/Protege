"""The agent trace, as a list model QML can watch a run in.

`Trace.listen` fires on whichever thread the agent is running on, which is
never the one QML lives on. Touching a `QAbstractListModel` from there corrupts
it — usually not immediately, which is worse. So every event crosses the
boundary through a private signal, connected without an explicit type so Qt
makes it a queued connection automatically once the threads differ.

The model is capped. A long run emits thousands of events, and an interface
holding all of them ends up spending its frame budget on scrollback nobody is
reading. Old rows fall off the front; `Trace` itself keeps the full history if
something needs it later.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Qt,
    Signal,
    Slot,
)

from akira.core.agents import Event, Trace

#: Rows kept in the view. Beyond this the oldest are dropped.
MAX_ROWS = 500


class TraceListModel(QAbstractListModel):
    """Trace events, oldest first."""

    AtRole = Qt.ItemDataRole.UserRole + 1
    KindRole = Qt.ItemDataRole.UserRole + 2
    AgentRole = Qt.ItemDataRole.UserRole + 3
    TextRole = Qt.ItemDataRole.UserRole + 4
    ToolRole = Qt.ItemDataRole.UserRole + 5
    OkRole = Qt.ItemDataRole.UserRole + 6
    ToRole = Qt.ItemDataRole.UserRole + 7
    StepRole = Qt.ItemDataRole.UserRole + 8

    countChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[Event] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        event = self._rows[index.row()]
        match role:
            case self.AtRole:
                return event.at
            case self.KindRole:
                return event.kind.value
            case self.AgentRole:
                return event.agent
            case self.TextRole:
                return event.text
            case self.ToolRole:
                return event.tool
            case self.OkRole:
                return event.ok
            case self.ToRole:
                return event.to
            case self.StepRole:
                return event.step
        return None

    def roleNames(self) -> dict:
        return {
            self.AtRole: QByteArray(b"at"),
            self.KindRole: QByteArray(b"kind"),
            self.AgentRole: QByteArray(b"agent"),
            self.TextRole: QByteArray(b"text"),
            self.ToolRole: QByteArray(b"tool"),
            self.OkRole: QByteArray(b"ok"),
            self.ToRole: QByteArray(b"recipient"),
            self.StepRole: QByteArray(b"step"),
        }

    def append(self, event: Event) -> None:
        if len(self._rows) >= MAX_ROWS:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self._rows.pop(0)
            self.endRemoveRows()
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append(event)
        self.endInsertRows()
        self.countChanged.emit()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows = []
        self.endResetModel()
        self.countChanged.emit()

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._rows)


class TraceBridge(QObject):
    """A live view of one `Trace`."""

    activeAgentsChanged = Signal()

    #: Private: carries an event from the worker thread to this one.
    _arrived = Signal(object)

    def __init__(self, trace: Trace | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._trace = trace if trace is not None else Trace()
        self._model = TraceListModel(self)
        self._stop = None
        self._active: list[str] = []

        # No connection type given: Qt picks direct within a thread and queued
        # across, which is exactly the behaviour wanted in both cases.
        self._arrived.connect(self._on_event)
        self.attach(self._trace)

    @Property(QObject, constant=True)
    def events(self) -> TraceListModel:
        return self._model

    @Property("QVariantList", notify=activeAgentsChanged)
    def activeAgents(self) -> list:
        """Who has started and not yet finished — the graph's nodes."""
        return list(self._active)

    @property
    def trace(self) -> Trace:
        return self._trace

    def attach(self, trace: Trace) -> None:
        """Watch \a trace, replaying what it already holds."""
        self.detach()
        self._trace = trace
        self._model.clear()
        self._active = []
        for event in trace.replay():
            self._on_event(event)
        self._stop = trace.listen(self._arrived.emit)

    def detach(self) -> None:
        if self._stop is not None:
            self._stop()
            self._stop = None

    @Slot()
    def clear(self) -> None:
        self._model.clear()
        self._active = []
        self.activeAgentsChanged.emit()

    def _on_event(self, event: Event) -> None:
        """Runs on the UI thread, whichever thread emitted it."""
        self._model.append(event)

        kind = event.kind.value
        changed = False
        if kind == "started" and event.agent not in self._active:
            self._active.append(event.agent)
            changed = True
        elif kind in ("answer", "failed") and event.agent in self._active:
            self._active.remove(event.agent)
            changed = True
        if changed:
            self.activeAgentsChanged.emit()
