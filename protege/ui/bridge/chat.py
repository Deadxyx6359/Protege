"""The conversation, as QML sees it.

Generation blocks for seconds at a time and Qt's scene graph must never wait on
it, so a turn runs on a worker thread and reports back through Qt signals.
Because this object lives on the main thread, those emissions are queued
automatically — nothing here touches the model or a QML property from the
worker.
"""

from __future__ import annotations

import threading

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

from protege.core.config import AppConfig
from protege.core.conversation import Cancelled, Conversation, Responder, route_for
from protege.core.conversations import ConversationError, ConversationStore, relative_time
from protege.core.models import ModelRouter, Route
from protege.models.base import ModelError


class MessageListModel(QAbstractListModel):
    """The transcript, as a list model QML can repeat over."""

    IdRole = Qt.ItemDataRole.UserRole + 1
    RoleRole = Qt.ItemDataRole.UserRole + 2
    TextRole = Qt.ItemDataRole.UserRole + 3
    ErrorRole = Qt.ItemDataRole.UserRole + 4

    countChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._messages: list = []

    # -- QAbstractListModel -------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._messages)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._messages)):
            return None
        message = self._messages[index.row()]
        match role:
            case self.IdRole:
                return message.id
            case self.RoleRole:
                return message.role
            case self.TextRole:
                return message.text
            case self.ErrorRole:
                return message.error
        return None

    def roleNames(self) -> dict:
        return {
            self.IdRole: QByteArray(b"messageId"),
            self.RoleRole: QByteArray(b"role"),
            self.TextRole: QByteArray(b"text"),
            self.ErrorRole: QByteArray(b"isError"),
        }

    # -- mutation -----------------------------------------------------------

    def reset(self, messages: list) -> None:
        self.beginResetModel()
        self._messages = messages
        self.endResetModel()
        self.countChanged.emit()

    def appended(self) -> None:
        """Announce that one message was added to the end of the backing list."""
        row = len(self._messages) - 1
        self.beginInsertRows(QModelIndex(), row, row)
        self.endInsertRows()
        self.countChanged.emit()

    def touched(self, row: int) -> None:
        """Announce that a message's text changed in place — used for streaming."""
        if not (0 <= row < len(self._messages)):
            return
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [self.TextRole, self.ErrorRole])

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._messages)


class ChatBridge(QObject):
    """One conversation, its model, and the turn currently running."""

    busyChanged = Signal()
    stageChanged = Signal()
    titleChanged = Signal()
    readyChanged = Signal()
    routeChanged = Signal()
    recentsChanged = Signal()

    _tokenArrived = Signal(str)
    _turnEnded = Signal(str)

    def __init__(
        self,
        router: ModelRouter,
        config: AppConfig,
        store: ConversationStore | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._router = router
        self._config = config
        self._responder = Responder(router, config)
        self._store = store if store is not None else ConversationStore()

        self._conversation = Conversation()
        self._model = MessageListModel(self)
        self._model.reset(self._conversation.messages)

        self._busy = False
        self._stage = ""
        self._route = Route.CHAT
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None

        # Queued across the thread boundary because this object lives on the
        # main thread and the worker does not.
        self._tokenArrived.connect(self._on_token)
        self._turnEnded.connect(self._on_ended)

        self._recents: list = []
        self._refresh_recents()

    # -- properties ---------------------------------------------------------

    @Property(QObject, constant=True)
    def messages(self) -> MessageListModel:
        return self._model

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=stageChanged)
    def stage(self) -> str:
        return self._stage

    @Property(str, notify=titleChanged)
    def title(self) -> str:
        return self._conversation.title or "New chat"

    @Property(bool, notify=readyChanged)
    def ready(self) -> bool:
        """Whether any model is present. False makes the composer explain why."""
        return self._router.any_usable

    @Property(str, notify=routeChanged)
    def routeLabel(self) -> str:
        """What the footnote under the composer shows."""
        status = self._router.status(self._router.resolve(self._route))
        if not status.usable:
            return "No model configured"
        return f"{status.label} · local"

    @Property("QVariantList", notify=recentsChanged)
    def recents(self) -> list:
        """Saved conversations, newest first, shaped for the sidebar."""
        return self._recents

    @Property(str, notify=titleChanged)
    def conversationId(self) -> str:
        return self._conversation.id

    # -- actions ------------------------------------------------------------

    @Slot(str)
    def openConversation(self, conversation_id: str) -> None:
        """Load a saved conversation, putting the current one away first."""
        if conversation_id == self._conversation.id:
            return
        if self._busy:
            self.stop()

        self._persist()
        try:
            self._conversation = self._store.load(conversation_id)
        except ConversationError:
            # A file that will not load should not take the window with it.
            # Leaving the current conversation in place is the safe outcome.
            self._refresh_recents()
            return

        self._model.reset(self._conversation.messages)
        self.titleChanged.emit()
        self._refresh_recents()

    @Slot(str)
    def deleteConversation(self, conversation_id: str) -> None:
        self._store.delete(conversation_id)
        if conversation_id == self._conversation.id:
            self._conversation = Conversation()
            self._model.reset(self._conversation.messages)
            self.titleChanged.emit()
        self._refresh_recents()


    @Slot(str)
    def send(self, text: str) -> None:
        payload = text.strip()
        if not payload or self._busy:
            return

        first = not any(m.role == "user" for m in self._conversation.messages)
        self._conversation.add("user", payload)
        self._model.appended()

        if first:
            self._conversation.title = self._conversation.derive_title()
            self.titleChanged.emit()

        if not self._router.any_usable:
            self._conversation.add(
                "assistant",
                "No model is configured yet, so there is nothing to answer with.\n\n"
                "Put a .gguf file in the models/ folder, or point Protégé at one "
                "in Settings.",
                error=True,
            )
            self._model.appended()
            return

        self._route = route_for(payload)
        self.routeChanged.emit()

        # The placeholder the stream writes into. Created before the worker
        # starts so the view has somewhere to put the first token.
        self._conversation.add("assistant")
        self._model.appended()

        self._set_busy(True)
        self._set_stage(self._opening_stage())

        self._cancel.clear()
        self._worker = threading.Thread(target=self._run_turn, daemon=True)
        self._worker.start()

    @Slot()
    def stop(self) -> None:
        """Ask the running turn to unwind.

        Cooperative, and it has to be: a Python thread cannot be killed. The
        token callback raises on the next token, which unwinds llama.cpp's
        stream from the inside.
        """
        self._cancel.set()
        self._set_stage("Stopping")

    @Slot()
    def newChat(self) -> None:
        if self._busy:
            self.stop()
        self._persist()
        self._conversation = Conversation()
        self._model.reset(self._conversation.messages)
        self.titleChanged.emit()
        self._refresh_recents()

    @Slot()
    def flush(self) -> None:
        """Persist now. Called on shutdown so the last turn is not lost."""
        self._persist()

    # -- the turn -----------------------------------------------------------

    def _opening_stage(self) -> str:
        resolved = self._router.resolve(self._route)
        if not self._router.status(resolved).loaded:
            # Several seconds of silence with no explanation reads as a crash.
            return f"Loading {self._router.status(resolved).label}"
        return "Thinking"

    def _run_turn(self) -> None:
        """Worker thread. Emits only signals; touches no Qt property directly."""
        try:
            self._responder.respond(
                self._conversation,
                route=self._route,
                on_token=lambda chunk: self._tokenArrived.emit(chunk),
                is_cancelled=self._cancel.is_set,
            )
            self._turnEnded.emit("")
        except Cancelled:
            self._turnEnded.emit("cancelled")
        except ModelError as exc:
            self._turnEnded.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - a crashed worker must not be silent
            self._turnEnded.emit(f"{type(exc).__name__}: {exc}")

    @Slot(str)
    def _on_token(self, chunk: str) -> None:
        messages = self._conversation.messages
        if not messages:
            return
        messages[-1].text += chunk
        if self._stage != "Writing":
            self._set_stage("Writing")
        self._model.touched(len(messages) - 1)

    @Slot(str)
    def _on_ended(self, problem: str) -> None:
        messages = self._conversation.messages
        last = messages[-1] if messages else None

        if last is not None and last.role == "assistant":
            if problem == "cancelled":
                # Keep whatever arrived — a partial answer is often still
                # useful, and silently discarding it punishes pressing Stop.
                if not last.text:
                    last.text = "Stopped before anything was generated."
                    last.error = True
            elif problem:
                last.text = problem
                last.error = True
            elif not last.text.strip():
                last.text = "The model returned nothing."
                last.error = True
            self._model.touched(len(messages) - 1)

        self._set_busy(False)
        self._set_stage("")
        self.routeChanged.emit()

        # Saved at the end of a turn rather than on every token: a write per
        # token would be hundreds of fsyncs for one answer.
        self._persist()
        self._refresh_recents()

    # -- helpers ------------------------------------------------------------

    def _persist(self) -> None:
        try:
            self._store.save(self._conversation)
        except OSError:
            # A conversation that could not be saved is still on screen. Losing
            # the history is bad; interrupting the person mid-thought over it
            # is worse.
            pass

    def _refresh_recents(self) -> None:
        self._recents = [
            {
                "id": summary.id,
                "title": summary.title,
                "when": relative_time(summary.updated),
                "turns": summary.turns,
            }
            for summary in self._store.list(limit=40)
        ]
        self.recentsChanged.emit()

    def _set_busy(self, value: bool) -> None:
        if value != self._busy:
            self._busy = value
            self.busyChanged.emit()

    def _set_stage(self, value: str) -> None:
        if value != self._stage:
            self._stage = value
            self.stageChanged.emit()
