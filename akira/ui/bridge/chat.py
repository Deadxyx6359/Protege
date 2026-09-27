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

One chat takes everything: each message is sorted as everyday, code or research
(`akira.core.intent`) and answered on the model for it. A research message is
looked up first, by the `researcher` given, and answered from what it read.
The person can pin a kind with `setMode`; `intent` says what the turn used.
"""

from __future__ import annotations

import re
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
from akira.core.conversation import Cancelled, Conversation, Responder
from akira.core.conversations import ConversationError, ConversationStore, relative_time
from akira.core.intent import LABELS, MODES, ROUTES, Intent, choose
from akira.core.models import ModelRouter, Route
from akira.models.base import ModelError
from akira.security.qtguard import inert_markdown
from akira.ui.history_search import HistorySearch

if TYPE_CHECKING:
    from akira.core.brain.recall import TurnContext
    from akira.core.brain.research import Findings

#: How much of the conversation a research turn is told, for what a follow-up
#: such as "what about Webb?" refers to.
EARLIER_CHARS = 1_500

#: An answer that says it did not know, or has nothing current. Chat looks the
#: question up once instead, when the web may be searched. Not "I couldn't find
#: that in your notes": the web does not know the person's dentist either.
DID_NOT_KNOW = re.compile(
    r"\bI\s+(?:do\s+not|don't)\s+have\s+(?:access\s+to\s+)?(?:any\s+)?"
    r"(?:real[- ]time|current|up[- ]to[- ]date|live|the\s+latest|recent)\b|"
    r"\bas\s+of\s+my\s+(?:last\s+(?:update|training)|knowledge\s+cut-?off)\b|"
    r"\bmy\s+(?:knowledge|training)(?:\s+data)?\s+(?:cut-?off|only\s+goes|ends)\b|"
    r"\bI\s+(?:can't|cannot|am\s+unable\s+to)\s+(?:browse|search|access|check)\s+"
    r"(?:the\s+)?(?:internet|web|online|live)\b|"
    r"\bI\s+(?:do\s+not|don't)\s+know\b|\bI(?:'m|\s+am)\s+not\s+(?:sure|certain)\b",
    re.IGNORECASE)

#: Sources found by searching before the answer, kept only when it cites them.
#: What research read (`web`, `files`, `drive`) was read for the answer and stays.
SEARCHED = frozenset({"notes", "documents", "conversations"})


def cited(sources: list, reply: str) -> list:
    """\a sources without the passages searched for and not drawn on in \a reply.

    A passage counts as drawn on when the reply names it as it was labelled,
    "[notes: Garden.md › Tomatoes]", or names its note or file, "Garden.md".
    """
    text = reply.lower()
    kept = []
    for source in sources:
        cite = str(source.get("cite", "")).strip().lower()
        if source.get("source") not in SEARCHED or (
                cite and (cite in text or cite.split(" › ")[0] in text)):
            kept.append(source)
    return kept


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
    modeChanged = Signal()

    #: The reply so far, each time it grows: for reading it aloud as it comes.
    replyGrew = Signal(str)

    #: The reply is over: its whole text, or "" when it was stopped, failed or
    #: came back empty, and nothing more of it should be read.
    replyEnded = Signal(str)

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
        researcher: Callable[..., Findings] | None = None,
    ) -> None:
        super().__init__(parent)
        self._router = router
        self._config = config
        self._responder = Responder(router, config)
        self._store = store if store is not None else ConversationStore()
        self._context = context
        # The open project's id, stamped on a conversation when it begins.
        self._project = project
        # Looks a research message up before it is answered. Without one, such
        # a message is answered as it would be anyway, on the research route.
        self._researcher = researcher
        self._mode = "auto"
        self._intent = Intent.EVERYDAY
        self._why = ""
        # The kind of the last turn, so a short follow-up keeps it.
        self._previous: Intent | None = None
        # Where the last turn looked things up, for a follow-up to look there too.
        self._looked_in: list[str] = []
        # Whether this message was looked up after an answer that did not know.
        self._looked_up = False
        # Why nothing could be read for a research turn, or "" when something was.
        self._nothing_read = ""

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
        self._search_candidates: list = []
        self._history_search = HistorySearch(self._store, lambda: self._search_candidates, self)
        self._refresh_recents()

    # -- properties ---------------------------------------------------------

    @Property(QObject, constant=True)
    def historySearch(self):
        return self._history_search

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

    @Property(str, notify=routeChanged)
    def intent(self) -> str:
        """`everyday`, `code` or `research`: what the current or last message was
        sorted as, and so which model answered it."""
        return self._intent.value

    @Property(str, notify=routeChanged)
    def intentLabel(self) -> str:
        """`intent` as a word to show: "Everyday", "Code", "Research"."""
        return LABELS[self._intent]

    @Property(str, notify=routeChanged)
    def intentReason(self) -> str:
        """Why, in a few words: "about code", "follows the last answer", "chosen"."""
        return self._why

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        """`auto`, which sorts each message, or the kind the person pinned."""
        return self._mode

    @Property("QVariantList", constant=True)
    def modes(self) -> list:
        """What `setMode` takes, with a word for each: `id` and `label`."""
        return [{"id": mode, "label": "Auto" if mode == "auto" else LABELS[Intent(mode)]}
                for mode in MODES]

    @Slot(str, result=bool)
    def setMode(self, mode: str) -> bool:
        """Sort each message (`auto`) or answer every one as \a mode. From the next
        message on; a turn already running keeps its kind. False if unknown."""
        if mode not in MODES:
            return False
        if mode != self._mode:
            self._mode = mode
            self.modeChanged.emit()
        return True

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

        self._previous = self._last_kind()
        self._model.reset(self._conversation.messages)
        self._set_sources([], "")
        self.titleChanged.emit()
        self._refresh_recents()

    @Slot(str)
    def deleteConversation(self, conversation_id: str) -> None:
        self._store.delete(conversation_id)
        if conversation_id == self._conversation.id:
            self._conversation = Conversation()
            self._previous = None
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

        # Everyday, code or research, and so which model answers. A short
        # follow-up keeps the kind of the turn before it.
        self._looked_up = False
        self._nothing_read = ""
        choice = choose(payload, previous=self._previous, mode=self._mode)
        self._intent, self._why, self._route = choice.intent, choice.why, choice.route
        self.routeChanged.emit()
        # What the last turn read, before this turn's sources replace it.
        self._looked_in = [str(source.get("cite", "")) for source in self._sources
                           if source.get("source") in ("web", "files", "drive")][:5]

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
        self._previous = None
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
        if self._researching():
            return "Researching"
        resolved = self._router.resolve(self._route)
        if not self._router.status(resolved).loaded:
            # Several seconds of silence with no explanation reads as a crash.
            return f"Loading {self._router.status(resolved).label}"
        return "Thinking"

    def _researching(self) -> bool:
        return self._intent is Intent.RESEARCH and self._researcher is not None

    def _last_kind(self) -> Intent | None:
        """The kind a reopened conversation left off in, as far as its text says."""
        answers = [m for m in self._conversation.messages
                   if m.role == "assistant" and not m.error]
        return Intent.CODE if answers and "```" in answers[-1].text else None

    def _earlier(self) -> str:
        """The conversation before this message, briefly, latest kept."""
        lines = [f"{'Person' if m.role == 'user' else 'Akira'}: {m.text.strip()}"
                 for m in self._conversation.messages[:-2]
                 if m.role in ("user", "assistant") and m.text.strip() and not m.error]
        return "\n".join(lines)[-EARLIER_CHARS:]

    def _gather(self, payload: str, opening: str) -> tuple[str, list, str]:
        """Worker thread. This turn's context, its sources and a note on them."""
        self._stageRequested.emit("Looking through your notes")
        try:
            found = self._context(payload)
        except Exception as exc:  # noqa: BLE001 - failing to look must not cost the answer
            result = ("", [], f"Could not look through your notes: {type(exc).__name__}: {exc}")
        else:
            result = (found.text, list(found.sources), found.note)
        self._stageRequested.emit(opening)
        return result

    def _look_up(self, payload: str) -> tuple[str, list, str]:
        """Worker thread. What was looked up for a research message, for the prompt."""
        self._stageRequested.emit("Researching")
        try:
            # "What about Webb?" after an answer from Wikipedia is looked up
            # there first, not in the person's files.
            findings = self._researcher(payload, earlier=self._earlier(),
                                        looked_in=self._looked_in,
                                        on_step=self._stageRequested.emit,
                                        is_cancelled=self._cancel.is_set)
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - failing to look must not cost the answer
            from akira.core.brain.research import Findings

            findings = Findings(note=f"The research failed: {type(exc).__name__}: {exc}")
        self._stageRequested.emit("Writing")
        self._nothing_read = "" if findings.found else findings.note
        return findings.for_prompt(), list(findings.sources), findings.note

    def _run_turn(self, payload: str = "", opening: str = "Thinking") -> None:
        """Worker thread. Emits only signals; touches no Qt property directly."""
        try:
            extra, sources, note = (self._gather(payload, opening) if self._context is not None
                                    else ("", [], ""))
            if self._researching() and not self._cancel.is_set():
                found, more, noted = self._look_up(payload)
                extra = "\n\n".join(part for part in (extra, found) if part)
                sources = sources + [s for s in more if s not in sources]
                note = "; ".join(part for part in (note, noted) if part)
            if self._context is not None or self._researching():
                self._contextReady.emit((sources, note))
            if self._cancel.is_set():
                raise Cancelled()
            said: list[str] = []

            def token(chunk: str) -> None:
                said.append(chunk)
                self._tokenArrived.emit(chunk)

            self._responder.respond(
                self._conversation,
                route=self._route,
                on_token=token,
                is_cancelled=self._cancel.is_set,
                extra_system=extra,
            )
            if self._researching() and self._nothing_read:
                # Told to say so, an answer with nothing read gave a prime
                # minister two out of date as "as of" today. Said here instead.
                self._tokenArrived.emit(
                    f"\n\nNote: nothing could be looked up for this "
                    f"({self._nothing_read.rstrip('.')}), so this answer is from memory and may "
                    "be out of date.")
            if self._researching():
                # A source the answer names and nothing was read from, checked
                # rather than trusted: told not to, answers still did.
                from akira.core.brain.research import unread_note

                warning = unread_note("".join(said), sources)
                if warning:
                    self._tokenArrived.emit(warning)
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
        self.replyGrew.emit(messages[-1].text)

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
            finished = "" if problem or last.error else last.text
        else:
            finished = ""
        if finished and self._should_look_up(finished):
            # Replaced in place, not added to: the answer that did not know is
            # not worth keeping beside the one that looked.
            self._look_up_instead(last)
            return
        if finished:
            # What was looked through but not drawn on is not a source of the
            # answer: a note about the allotment was shown under "15% of 240".
            self._set_sources(cited(self._sources, finished), self._context_note)
        # A follow-up to this turn keeps its kind.
        self._previous = self._intent

        # Before the chat is idle again, so that whatever waits for it to be
        # idle, a call with the next thing said, finds this reply finished.
        self.replyEnded.emit(finished)
        self._set_busy(False)
        self._set_stage("")
        self.routeChanged.emit()

        # Saved at the end of a turn rather than on every token: a write per
        # token would be hundreds of fsyncs for one answer.
        self._persist()
        self._refresh_recents()

    def _should_look_up(self, reply: str) -> bool:
        """An everyday answer that did not know, where the web may be searched."""
        return (self._intent is Intent.EVERYDAY and self._mode == "auto"
                and not self._looked_up and self._researcher is not None
                and bool(getattr(self._researcher, "searches_web", lambda: False)())
                and DID_NOT_KNOW.search(reply) is not None
                and "in your notes" not in reply.lower())

    def _look_up_instead(self, answer) -> None:
        """Look the question up, and answer it again in the place of \a answer."""
        question = next((m.text for m in reversed(self._conversation.messages)
                         if m.role == "user"), "")
        self._looked_up = True
        self._intent, self._why = Intent.RESEARCH, "the answer needed looking up"
        self._route = ROUTES[Intent.RESEARCH]
        self.routeChanged.emit()
        answer.text = ""
        self._model.touched(len(self._conversation.messages) - 1)
        self._set_sources([], "")
        self._set_stage("Looking it up")
        self._cancel.clear()
        self._worker = threading.Thread(target=self._run_turn, args=(question, "Looking it up"),
                                        daemon=True)
        self._worker.start()

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
        self._search_candidates = [
            {
                "id": summary.id,
                "title": summary.title,
                "when": relative_time(summary.updated),
                "turns": summary.turns,
            }
            for summary in self._store.list(limit=200)
        ]
        self._recents = self._search_candidates[:40]
        self._history_search.refresh()
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
