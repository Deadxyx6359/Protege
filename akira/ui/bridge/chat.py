"""The conversation, as QML sees it.

Generation blocks for seconds at a time and Qt's scene graph must never wait on
it, so a turn runs on a worker thread and reports back through Qt signals.
Because this object lives on the main thread, those emissions are queued
automatically — nothing here touches the model or a QML property from the
worker.

When given a `context` callable, each turn first asks it what to know for this
message — the open project, passages from the person's own sources — and sends
that with the turn without saving it. What was used is shown as `lastSources`.
The callable decides everything; this bridge only carries its answer.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

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

from akira.core.config import AppConfig
from akira.core.conversation import Cancelled, Conversation, Responder, route_for
from akira.core.conversations import ConversationError, ConversationStore, relative_time
from akira.core.models import ModelRouter, Route
from akira.models.base import ModelError
from akira.security.qtguard import inert_markdown

if TYPE_CHECKING:
    from akira.core.brain.recall import TurnContext


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
                # A reply is shown as Markdown, so a picture in it is served as
                # a link and never loaded: its address could name a server (see
                # qtguard). The person's own words and an error are shown as
                # plain text, as written. The transcript keeps everything as is.
                if message.role != "assistant" or message.error:
                    return message.text
                return inert_markdown(message.text)
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
    sourcesChanged = Signal()

    _tokenArrived = Signal(str)
    _turnEnded = Signal(str)
    _stageRequested = Signal(str)
    _contextReady = Signal(object)

    def __init__(
        self,
        router: ModelRouter,
        config: AppConfig,
        store: ConversationStore | None = None,
        parent: QObject | None = None,
        *,
        context: Callable[[str], TurnContext] | None = None,
        project: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._router = router
        self._config = config
        self._responder = Responder(router, config)
        self._store = store if store is not None else ConversationStore()
        self._context = context
        # The open project's id, stamped on a conversation when it begins.
        self._project = project

        self._conversation = Conversation()
        self._model = MessageListModel(self)
        self._model.reset(self._conversation.messages)

        self._busy = False
        self._stage = ""
        self._route = Route.CHAT
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._sources: list = []
        self._context_note = ""

        # Queued across the thread boundary because this object lives on the
        # main thread and the worker does not.
        self._tokenArrived.connect(self._on_token)
        self._turnEnded.connect(self._on_ended)
        self._stageRequested.connect(self._on_stage)
        self._contextReady.connect(self._on_context)

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

    @Property(str, notify=titleChanged)
    def conversationProject(self) -> str:
        """The project this conversation was filed under, empty for personal."""
        return self._conversation.project

    @Property("QVariantList", notify=sourcesChanged)
    def lastSources(self) -> list:
        """What the last turn drew on: `source` (`notes`, `documents` or
        `conversations`) and `cite`, where to find it. Empty when nothing was."""
        return self._sources

    @Property(str, notify=sourcesChanged)
    def lastContextNote(self) -> str:
        """What the last turn's search found and could not search, in a sentence."""
        return self._context_note

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
        self._set_sources([], "")
        self.titleChanged.emit()
        self._refresh_recents()

    @Slot(str)
    def deleteConversation(self, conversation_id: str) -> None:
        self._store.delete(conversation_id)
        if conversation_id == self._conversation.id:
            self._conversation = Conversation()
            self._model.reset(self._conversation.messages)
            self._set_sources([], "")
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
            # Filed under the project open when it began, not whichever is open
            # when it is next read.
            if self._project is not None:
                self._conversation.project = self._project() or ""
            self.titleChanged.emit()

        if not self._router.any_usable:
            self._conversation.add(
                "assistant",
                "No model is configured yet, so there is nothing to answer with.\n\n"
                "Put a .gguf file in the models/ folder, or point Akira at one "
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

        self._set_sources([], "")
        opening = self._opening_stage()
        self._set_busy(True)
        self._set_stage(opening)

        self._cancel.clear()
        self._worker = threading.Thread(target=self._run_turn, args=(payload, opening),
                                        daemon=True)
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
        self._set_sources([], "")
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

    def _gather(self, payload: str, opening: str) -> str:
        """Worker thread. This turn's context, or none if it could not be had."""
        self._stageRequested.emit("Looking through your notes")
        try:
            found = self._context(payload)
        except Exception as exc:  # noqa: BLE001 - failing to look must not cost the answer
            self._contextReady.emit(
                ([], f"Could not look through your notes: {type(exc).__name__}: {exc}"))
            text = ""
        else:
            self._contextReady.emit((list(found.sources), found.note))
            text = found.text
        self._stageRequested.emit(opening)
        return text

    def _run_turn(self, payload: str = "", opening: str = "Thinking") -> None:
        """Worker thread. Emits only signals; touches no Qt property directly."""
        try:
            extra = self._gather(payload, opening) if self._context is not None else ""
            if self._cancel.is_set():
                raise Cancelled()
            self._responder.respond(
                self._conversation,
                route=self._route,
                on_token=lambda chunk: self._tokenArrived.emit(chunk),
                is_cancelled=self._cancel.is_set,
                extra_system=extra,
            )
            self._turnEnded.emit("")
        except Cancelled:
            self._turnEnded.emit("cancelled")
        except ModelError as exc:
            self._turnEnded.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - a crashed worker must not be silent
            self._turnEnded.emit(f"{type(exc).__name__}: {exc}")

    @Slot(str)
    def _on_stage(self, value: str) -> None:
        if not self._cancel.is_set():
            self._set_stage(value)

    @Slot(object)
    def _on_context(self, result) -> None:
        sources, note = result
        self._set_sources(sources, note)

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

    def _set_sources(self, sources: list, note: str) -> None:
        self._sources, self._context_note = sources, note
        self.sourcesChanged.emit()
