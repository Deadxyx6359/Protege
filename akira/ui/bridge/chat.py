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
from datetime import datetime
import time
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
from akira.core import agenda, handoff, planner, quiet, reminders
from akira.core.cloud import Claude
from akira.core.brain.grounding import TEACHING, Grounding, subject_of, teaching
from akira.core.intent import LABELS, MODES, ROUTES, Intent, choose
from akira.core.plain_maths import plain_maths
from akira.core.planner import PlannerError, PlannerStore
from akira.core.reminders import Asked
from akira.core.models import ModelRouter, Route
from akira.models.base import ModelError
from akira.security.qtguard import inert_markdown
from akira.ui.history_search import HistorySearch

if TYPE_CHECKING:
    from akira.core.brain.recall import TurnContext
    from akira.core.brain.research import Findings

#: The longest name a person may give a chat.
MAX_TITLE = 120

#: How much of the conversation a research turn is told, for what a follow-up
#: such as "what about Webb?" refers to.
EARLIER_CHARS = 1_500

#: A question about the person themselves: "my dentist", "my password". The web
#: does not know it, and is not asked.
ABOUT_THEM = re.compile(r"\b(?:my|mine|me|I|I'm|I've|we|our)\b")

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
    r"\bI\s+(?:do\s+not|don't)\s+(?:know|recogni[sz]e)\b|"
    r"\bI(?:'m|\s+am)\s+not\s+(?:sure|certain|familiar\s+with|aware\s+of)\b",
    re.IGNORECASE)

#: Writing slower than this, in tokens a second, on the graphics card is worth a word:
#: the person's card gives 30 to 40.
SLOW_TOKENS_PER_S = 5.0

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


_nvidia: quiet.Nvidia | None = None


def _card() -> quiet.Nvidia:
    """The NVIDIA card, opened the first time it is asked about."""
    global _nvidia
    if _nvidia is None:
        _nvidia = quiet.Nvidia()
    return _nvidia


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
                # LaTeX the model writes despite being told not to is shown plainly.
                return inert_markdown(plain_maths(message.text))
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


def _older_than(days: int):
    """Chats not touched in \a days days; every chat for 0."""
    if days <= 0:
        return lambda summary: True
    cutoff = time.time() - days * 86_400
    return lambda summary: summary.updated < cutoff


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
    #: Whether "Do it" is offered, where, and whether the team is at it.
    handOffChanged = Signal()
    #: Which model answers, and whether Claude is connected.
    modelChanged = Signal()
    #: ok, message — once a Claude key has been checked, however it went.
    claudeFinished = Signal(bool, str)
    #: Private: the key's check, from its worker to this thread.
    _claudeDone = Signal(bool, str)

    #: The reply so far, each time it grows: for reading it aloud as it comes.
    replyGrew = Signal(str)

    #: The reply is over: its whole text, or "" when it was stopped, failed or
    #: came back empty, and nothing more of it should be read.
    replyEnded = Signal(str)

    #: The model wrote far slower than it should, and why, for the person: once a
    #: session. A research answer came at half a word a second, with no word why.
    slowNoticed = Signal(str)
    #: message — the graphics card is held by another program as a model is about
    #: to load, so the answer will be slow. Once a session.
    cardBusy = Signal(str)

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
        remind: Callable[[str, float], str] | None = None,
        notices: Callable[[], bool] | None = None,
        ground: Callable[[str, str], Grounding] | None = None,
        calendar: PlannerStore | None = None,
        hand_off: Callable[[str, str], str] | None = None,
        folder: Callable[[], str] | None = None,
        stop_hand_off: Callable[[], None] | None = None,
        claude: "Claude | None" = None,
        allow_cloud: Callable[[], str] | None = None,
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
        # The reply, as it is, when no page the person gave could be read (`Findings.said`).
        self._said_instead = ""
        # Sets a reminder, what and when: "" or why not. Without one, a request
        # for a reminder goes to the model, which says it cannot.
        self._remind = remind
        # Whether a notice can reach the person now.
        self._notices = notices
        # A reminder asked for and not yet agreed to: what, and when or None.
        self._reminder: Asked | None = None
        # The calendar kept in Akira, which "add ... to my calendar" is put in on
        # the person's yes. Without one, such a message goes to the model.
        self._calendar = calendar
        # An event asked for and not yet agreed to: its title, and when or None.
        self._event: agenda.Asked | None = None
        # Whether the person was told this session that the model writes slowly.
        self._told_slow = False
        # Whether they were told this session that another program held the card.
        self._told_card = False
        # For a message about a chip or board: the vendor's own names before the
        # answer, and a check of the answer's after (`akira.core.brain.grounding`).
        self._ground = ground
        # "Do it": the answer handed to the software team, in a folder: "" or why
        # not. The open project's folder is offered first.
        self._hand_off = hand_off
        self._folder = folder or (lambda: "")
        self._stop_hand_off = stop_hand_off
        # The conversation the team's work is for, while it works; "" otherwise.
        self._handed_from = ""
        # Claude, when the person chooses it in the chat window (`akira.core.cloud`),
        # and how the permission to send chats to it is given on connecting.
        self._claude = claude
        self._allow_cloud = allow_cloud or (lambda: "")
        self._claude_checking = False
        self._chosen = "claude" if claude is not None and config.chat_model == "claude" \
            else "local"
        self._claudeDone.connect(self._on_claude_done)

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

        # Whether "Do it" is offered follows what is on screen.
        for changed in (self._model.modelReset, self._model.rowsInserted,
                        self._model.dataChanged, self.busyChanged):
            changed.connect(self.handOffChanged)

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
        """Whether any model is present, or Claude chosen. False makes the composer
        explain why."""
        return self._router.any_usable or self._cloud()

    @Property(str, notify=routeChanged)
    def routeLabel(self) -> str:
        """What the footnote under the composer shows."""
        if self._cloud():
            return "Claude Opus 5.5 · sent to Anthropic"
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

    # -- the person's changes to their chats (the sidebar's right-click menu) ---

    @Slot(str, str, result=str)
    def renameConversation(self, conversation_id: str, title: str) -> str:
        """Give a chat a name of the person's own: "" or why not."""
        name = " ".join(str(title or "").split())
        if not name:
            return "Give the chat a name."
        if len(name) > MAX_TITLE:
            return f"A chat's name is at most {MAX_TITLE} characters."
        return self._change(conversation_id, title=name)

    @Slot(str, bool, result=str)
    def pinConversation(self, conversation_id: str, pinned: bool) -> str:
        """Keep a chat at the top of the list, or stop: "" or why not."""
        return self._change(conversation_id, pinned=bool(pinned))

    @Slot(str, str, result=str)
    def moveConversation(self, conversation_id: str, project_id: str) -> str:
        """File a chat under another project, or "" for none: "" or why not.

        Where it is filed decides which project's work may find it again (see
        `search_conversations`) and where memory files what is kept from it.
        Moving the open chat does not change the project open: the interface
        switches to it, as it does when a chat is opened.
        """
        if self._busy and conversation_id == self._conversation.id:
            return "Wait for the reply to finish first."
        return self._change(conversation_id, project=str(project_id or ""))

    @Slot("QVariantList", result=int)
    def deleteConversations(self, conversation_ids: list) -> int:
        """Delete these chats, for good. Returns how many were deleted."""
        return self._delete_where(lambda summary: summary.id in {str(i) for i in conversation_ids},
                                  keep_pinned=False)

    @Slot(bool, result=int)
    def deleteAllConversations(self, keep_pinned: bool) -> int:
        """Delete every chat, for good, or every one but the pinned. Returns how many."""
        return self._delete_where(_older_than(0), keep_pinned=keep_pinned)

    @Slot(int, bool, result=int)
    def deleteConversationsOlderThan(self, days: int, keep_pinned: bool) -> int:
        """Delete chats not touched in \a days days, for good. Returns how many."""
        if days < 1:
            return 0
        return self._delete_where(_older_than(days), keep_pinned=keep_pinned)

    @Slot(int, bool, result=int)
    def countConversations(self, days: int, keep_pinned: bool) -> int:
        """How many chats a bulk delete would take, to say so before asking.

        \a days 0 counts for `deleteAllConversations`, more for
        `deleteConversationsOlderThan`.
        """
        return len(self._doomed(_older_than(days), keep_pinned=keep_pinned))

    def _change(self, conversation_id: str, **changes) -> str:
        if conversation_id == self._conversation.id:
            if not any(m.role == "user" and m.text.strip() for m in self._conversation.messages):
                return "Say something in the chat first; an empty chat is not kept."
            # The open chat: changed here too, so its next save keeps the change.
            for key, value in changes.items():
                setattr(self._conversation, key, value)
            self.titleChanged.emit()
        try:
            self._store.update(conversation_id, **changes)
        except ConversationError:
            # The open chat's first reply is still coming, and it is saved
            # when that is done; any other is gone.
            if conversation_id != self._conversation.id:
                return "That chat is not saved any more."
        self._refresh_recents()
        return ""

    def _doomed(self, chosen, *, keep_pinned: bool) -> list:
        # The chat still answering is left out: its reply would save it again.
        return [summary for summary in self._store.list(limit=100_000)
                if chosen(summary) and not (keep_pinned and summary.pinned)
                and not (self._busy and summary.id == self._conversation.id)]

    def _delete_where(self, chosen, *, keep_pinned: bool) -> int:
        doomed = self._doomed(chosen, keep_pinned=keep_pinned)
        open_one = any(summary.id == self._conversation.id for summary in doomed)
        for summary in doomed:
            self._store.delete(summary.id)
        if open_one:
            self._conversation = Conversation()
            self._previous = None
            self._model.reset(self._conversation.messages)
            self._set_sources([], "")
            self.titleChanged.emit()
        self._refresh_recents()
        return len(doomed)

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

        # "Remind me ..." is read here and set on the person's yes, never by
        # a model, which once answered "Reminder set" with nothing set.
        # "Add ... to my calendar" likewise: read here, added on the person's yes.
        said = self._reminding(payload)
        if said:
            self._event = None  # a later "yes" is to the reminder, not an event before it
        else:
            said = self._adding(payload)
        if said:
            self._say(said)
            return

        if not self._router.any_usable and not self._cloud():
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
        self._said_instead = ""
        choice = choose(payload, previous=self._previous, mode=self._mode)
        self._intent, self._why, self._route = choice.intent, choice.why, choice.route
        if self._intent is Intent.CODE and self._mode == "auto" and teaching(payload):
            # Asked to be taught, not given code, the coding model wrote the whole
            # program anyway, every time it was tried. The chat model explains.
            self._route = ROUTES[Intent.EVERYDAY]
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

    # -- reminders -------------------------------------------------------------

    def _reminding(self, text: str) -> str:
        """The reply to \a text if it is about a reminder, or "" to answer it as usual."""
        if self._remind is None:
            return ""
        pending, self._reminder = self._reminder, None
        if pending is not None:
            if pending.when is not None:
                answer = reminders.answer(text)
                if answer == "yes":
                    return self._set_reminder(pending)
                if answer == "no":
                    return "All right, no reminder."
            else:
                when, _ = reminders.when_said(text, datetime.now())
                if when is not None:
                    return self._offer(Asked(pending.what, when))
                if reminders.answer(text) == "no":
                    return "All right, no reminder."
            # Anything else is a new message; the reminder is let go.
        if not reminders.asks(text):
            return ""
        asked = reminders.read(text)
        if asked.when is None:
            self._reminder = asked
            return ("When should I remind you" + (f" to {asked.what}" if asked.what else "")
                    + "? For example: in 20 minutes, at 5pm, tomorrow at 9, or Friday at 3pm.")
        return self._offer(asked)

    def _offer(self, asked: Asked) -> str:
        self._reminder = asked
        what = asked.what or "this"
        note = ("" if self._notices is None or self._notices() else
                " Notices are not allowed yet, so it would reach you only once they are: "
                "allow Send notifications in Settings, under Permissions.")
        return (f"Set a reminder for {reminders.described(asked.when)}: {what}? "
                f"Say yes to set it, or no.{note}")

    def _set_reminder(self, asked: Asked) -> str:
        why = self._remind(asked.what or "Reminder", asked.when.timestamp())
        if why:
            return f"The reminder could not be set: {why}"
        return f"Done. I'll remind you {reminders.described(asked.when)}: {asked.what or 'this'}."

    # -- speed -----------------------------------------------------------------

    def _check_card(self) -> None:
        """Worker thread. Before a model loads onto the graphics card: say so, once a
        session, when another program already holds a gigabyte or more of it.

        Akira's own behaviour test held the card while the person opened Akira; the
        model went to ordinary memory and the window was unusable, with no word why.
        """
        if self._told_card or self._router.loaded:
            return
        model = self._config.models.get(self._router.resolve(self._route).value)
        if model is None or model.n_gpu_layers == 0:
            return
        used = _card().used_bytes()
        if used is None or used < quiet.OTHERS_BYTES:
            return
        self._told_card = True
        self.cardBusy.emit(
            f"Another program is using {used / 1024**3:.1f} GB of the graphics card, so the "
            "model will not fit beside it and answers will be very slow. Close games or other "
            "programs that use the card, then ask again.")

    def _check_speed(self, result) -> None:
        """Tell the person, once, when a model on the graphics card wrote far too slowly.

        Worker thread: emits a signal only. The 8B model writes 30 to 40 tokens a
        second on the person's card; when something else holds the card's memory,
        part of the model runs from ordinary memory and it falls to one or two.
        """
        rate = getattr(result, "writing_rate", None)
        if self._told_slow or rate is None or rate >= SLOW_TOKENS_PER_S:
            return
        if quiet.in_background():
            return  # finished with the window closed, behind every other program
        model = self._config.models.get(self._router.resolve(self._route).value)
        if model is None or model.n_gpu_layers == 0:
            return  # on the processor alone, slow is how it is
        self._told_slow = True
        words = max(0.1, rate * 0.75)
        self.slowNoticed.emit(
            f"That reply came at about {words:.1f} words a second; the model usually writes "
            "20 or more. Part of it is probably running from ordinary memory because "
            "something else is using the graphics card. Close games, browsers or other "
            "programs that use it, then restart Akira.")

    # -- the calendar ----------------------------------------------------------

    def _adding(self, text: str) -> str:
        """The reply to \a text if it is about adding to the calendar, or "" to answer it
        as usual."""
        if self._calendar is None:
            return ""
        pending, self._event = self._event, None
        if pending is not None:
            if pending.start is not None:
                answer = reminders.answer(text)
                if answer == "yes":
                    return self._add_event(pending)
                if answer == "no":
                    return "All right, nothing added."
            else:
                said = agenda.read(text)
                if said.start is not None:
                    return self._offer_event(agenda.Asked(pending.title, said.start, said.end))
                if reminders.answer(text) == "no":
                    return "All right, nothing added."
            # Anything else is a new message; the event is let go.
        if not agenda.asks_to_add(text):
            return ""
        asked = agenda.read(text)
        if asked.start is None:
            self._event = asked
            return ("When is it" + (f", {asked.title}" if asked.title else "") + "? For example: "
                    "Friday at 3pm, tomorrow from 10 to 11, or 5 October for all day.")
        return self._offer_event(asked)

    def _offer_event(self, asked: agenda.Asked) -> str:
        try:
            said = agenda.offer(asked)
        except PlannerError as exc:
            return f"That could not go in the calendar: {exc}"
        self._event = asked
        return said

    def _add_event(self, asked: agenda.Asked) -> str:
        try:
            event = self._calendar.add(asked.event())
        except (PlannerError, OSError) as exc:
            return f"The event was not added: {exc}"
        return f"Added to your calendar: {event.title}, {planner.when(event.start, event.end)}."

    def _say(self, text: str) -> None:
        """Answer at once, without a model: kept, shown and read aloud like any reply."""
        self._conversation.add("assistant", text)
        self._model.appended()
        self._persist()
        self._refresh_recents()
        self.replyGrew.emit(text)
        self.replyEnded.emit(text)

    # -- which model answers --------------------------------------------------

    def _cloud(self) -> bool:
        return self._chosen == "claude" and self._claude is not None

    @Property("QVariantList", constant=True)
    def models(self) -> list:
        """The models the chat window offers: `id`, `label`."""
        offered = [{"id": "local", "label": "Local"}]
        if self._claude is not None:
            offered.append({"id": "claude", "label": "Claude Opus 5.5"})
        return offered

    @Property(str, notify=modelChanged)
    def model(self) -> str:
        """`local` or `claude`: which answers the next message."""
        return self._chosen

    @Property(bool, notify=modelChanged)
    def claudeConnected(self) -> bool:
        return self._claude is not None and self._claude.has_key()

    @Property(bool, notify=modelChanged)
    def claudeChecking(self) -> bool:
        return self._claude_checking

    @Property(str, notify=modelChanged)
    def claudeSpend(self) -> str:
        """What Claude has cost this month at its list prices, in words."""
        if self._claude is None:
            return ""
        month = self._claude.spend.month()
        if not month["read"] and not month["written"]:
            return "Nothing used this month."
        return (f"About ${month['dollars']:.2f} this month ({month['read']:,} tokens read, "
                f"{month['written']:,} written).")

    @Slot(str, result=str)
    def setModel(self, chosen: str) -> str:
        """Answer from now on with \a chosen. "" once set; "key" when Claude needs
        its key first; or why not."""
        if chosen not in ("local", "claude") or (chosen == "claude" and self._claude is None):
            return "There is no such model here."
        if chosen == "claude":
            why = self._claude.ready()
            if why == "Add your Claude API key first.":
                return "key"
            if why:
                # Connected before, and the permission taken back since: given again
                # only by choosing Claude again here, which is the person's own act.
                given = self._allow_cloud()
                if given or self._claude.ready():
                    return given or self._claude.ready()
        self._chosen = chosen
        self._config.chat_model = chosen
        self._save_config()
        self.modelChanged.emit()
        self.routeChanged.emit()
        self.readyChanged.emit()
        self.handOffChanged.emit()
        return ""

    @Slot(str, result=str)
    def connectClaude(self, key: str) -> str:
        """Keep \a key sealed, allow sending chats to Anthropic, and check the key with
        Anthropic. "" once the check has started (`claudeFinished` follows), or why not."""
        if self._claude is None:
            return "Claude is not available here."
        if self._claude_checking:
            return "Already checking a key."
        why = self._claude.seal(key)
        if why:
            return why
        why = self._allow_cloud()
        if why:
            self._claude.forget()
            return why
        self._claude_checking = True
        self.modelChanged.emit()
        threading.Thread(target=self._check_claude, name="claude-key", daemon=True).start()
        return ""

    def _check_claude(self) -> None:
        """Worker thread. Emits a signal only."""
        try:
            why = self._claude.check()
        except Exception as exc:  # noqa: BLE001 - a crashed check must still report back
            why = f"{type(exc).__name__}: {exc}"
        self._claudeDone.emit(not why, why)

    def _on_claude_done(self, ok: bool, why: str) -> None:
        self._claude_checking = False
        if ok:
            self._chosen = "claude"
            self._config.chat_model = "claude"
            self._save_config()
            message = "Connected. Chats now go to Claude Opus 5.5 until you choose Local."
        else:
            self._claude.forget()
            message = f"The key was not kept: {why}"
        self.modelChanged.emit()
        self.routeChanged.emit()
        self.readyChanged.emit()
        self.claudeFinished.emit(ok, message)

    @Slot(result=str)
    def forgetClaude(self) -> str:
        """Forget the key and answer locally again. What the person may also do at Anthropic."""
        if self._claude is None:
            return ""
        self._claude.forget()
        self._chosen = "local"
        self._config.chat_model = "local"
        self._save_config()
        self.modelChanged.emit()
        self.routeChanged.emit()
        self.readyChanged.emit()
        return ("The key is gone from this computer. To stop it working anywhere, delete it "
                "in the Anthropic Console too.")

    def _save_config(self) -> None:
        try:
            self._config.save()
        except OSError:
            pass  # chosen for this session; asked again next time

    # -- handing the work over ------------------------------------------------

    @Property(bool, notify=handOffChanged)
    def canHandOff(self) -> bool:
        """Whether "Do it" is offered under the last answer: there is a team to
        hand to, nothing is running, and the answer reads as work to carry out."""
        if self._hand_off is None or self._busy or self._handed_from:
            return False
        messages = self._conversation.messages
        last = messages[-1] if messages else None
        return (last is not None and last.role == "assistant" and not last.error
                and (self._previous is Intent.CODE or handoff.worth_doing(last.text)))

    @Property(str, notify=handOffChanged)
    def handOffFolder(self) -> str:
        """Where the team would work: the open project's folder, or "" to ask."""
        try:
            return self._folder() or ""
        except Exception:  # noqa: BLE001 - no folder is a question, not a failure
            return ""

    @Property(bool, notify=handOffChanged)
    def handingOff(self) -> bool:
        """Whether the team is working on something handed from this chat."""
        return bool(self._handed_from)

    @Slot(str, result=str)
    def handOff(self, folder: str = "") -> str:
        """Give the last answer to the software team to carry out in \a folder (the
        open project's when ""). "" once it has started, or why it has not."""
        if not self.canHandOff:
            return "There is no answer here to carry out."
        where = (folder or self.handOffFolder).strip()
        if not where:
            return "Choose the folder the work is for first."
        task = handoff.task_from(self._conversation.messages, where)
        if not task:
            return "There is no answer here to carry out."
        why = self._hand_off(task, where)
        if why:
            return why
        self._handed_from = self._conversation.id
        self.handOffChanged.emit()
        return ""

    @Slot()
    def stopHandOff(self) -> None:
        if self._handed_from and self._stop_hand_off is not None:
            self._stop_hand_off()

    def hand_off_finished(self, ok: bool, answer: str, stopped: str) -> None:
        """For the team's end: what it did goes into the conversation it came from."""
        source, self._handed_from = self._handed_from, ""
        if not source:
            return
        said = handoff.result_said(ok, answer, stopped)
        if source == self._conversation.id:
            self._say(said)
        else:
            try:
                kept = self._store.load(source)
                kept.add("assistant", said)
                self._store.save(kept)
            except (ConversationError, OSError):
                pass
            self._refresh_recents()
        self.handOffChanged.emit()

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
        if self._cloud():
            return "Asking Claude Opus 5.5"
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
        self._said_instead = "" if findings.found else findings.said
        return findings.for_prompt(), list(findings.sources), findings.note

    def _run_turn(self, payload: str = "", opening: str = "Thinking") -> None:
        """Worker thread. Emits only signals; touches no Qt property directly."""
        try:
            extra, sources, note = (self._gather(payload, opening) if self._context is not None
                                    else ("", [], ""))
            noted = ""
            if self._researching() and not self._cancel.is_set():
                found, more, noted = self._look_up(payload)
                extra = "\n\n".join(part for part in (extra, found) if part)
                sources = sources + [s for s in more if s not in sources]
                note = "; ".join(part for part in (note, noted) if part)
            grounding = None
            if self._ground is not None and subject_of(payload) is not None:
                self._stageRequested.emit("Reading the library's own files")
                grounding = self._ground(payload, extra)
                extra = "\n\n".join(part for part in (extra, grounding.reference) if part)
                if grounding.headers:
                    sources = sources + [{"source": "files", "cite": (
                        f"{grounding.subject.name} library files "
                        f"({len(grounding.headers)} headers)")}]
            if teaching(payload):
                extra = "\n\n".join(part for part in (extra, TEACHING) if part)
            if self._context is not None or self._researching() or grounding is not None:
                self._contextReady.emit((sources, note))
            if self._cancel.is_set():
                raise Cancelled()
            if self._said_instead:
                # No page the person gave could be read, and why is known: said as
                # it is. Told why, the model said it "cannot access external websites".
                self._tokenArrived.emit(self._said_instead)
                self._turnEnded.emit("")
                return
            if grounding is not None and grounding.banner:
                # Before the answer, where it will be read: nothing here could be checked.
                self._tokenArrived.emit(grounding.banner)
            said: list[str] = []

            def shown(chunk: str) -> None:
                said.append(chunk)
                self._tokenArrived.emit(chunk)

            # An answer written from what was read opened "I cannot directly access
            # external websites": its first sentence is held until it is whole.
            from akira.core.brain.research import OpeningHeld

            opening = (OpeningHeld(shown) if self._researching() and not self._nothing_read
                       else None)
            token = opening.feed if opening is not None else shown
            cloud = self._cloud()
            if not cloud:
                self._check_card()
            responder = (Responder(self._claude.router(), self._config) if cloud
                         else self._responder)
            result = responder.respond(
                self._conversation,
                route=self._route,
                on_token=token,
                is_cancelled=self._cancel.is_set,
                extra_system=extra,
            )
            if opening is not None:
                opening.finish()
            if not cloud:
                self._check_speed(result)
            if self._researching() and self._nothing_read:
                # Told to say so, an answer with nothing read gave a prime
                # minister two out of date as "as of" today. Said here instead.
                # The reason alone: "Nothing could be read (DuckDuckGo asked …)" in
                # the note's brackets read as brackets inside brackets.
                wrapped = re.match(r"\s*nothing could be (?:read|looked up)[^(]*\((.*)\)\W*$",
                                   self._nothing_read, re.IGNORECASE | re.DOTALL)
                reason = (wrapped.group(1) if wrapped else self._nothing_read).strip().rstrip(".")
                self._tokenArrived.emit(
                    f"\n\nNote: nothing could be looked up for this ({reason}), so this answer "
                    "is from memory and may be out of date.")
            if grounding is not None:
                # Every library name in the answer, looked up in the library's
                # own files: those that are not there are named, with the closest.
                checked = grounding.check("".join(said))
                if checked:
                    self._tokenArrived.emit(checked)
            if self._researching():
                # A source the answer names and nothing was read from, checked
                # rather than trusted: told not to, answers still did.
                from akira.core.brain.research import only_searched, unread_note

                warning = unread_note("".join(said), sources, searched=only_searched(noted))
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
        """An everyday answer that did not know, where the web may be searched.

        Not for a question about the person: "what's my dentist's name?" was
        sent to a search engine when the answer did not know it, which finds
        nothing and tells a stranger what was asked.
        """
        question = next((m.text for m in reversed(self._conversation.messages)
                         if m.role == "user"), "")
        return (self._intent is Intent.EVERYDAY and self._mode == "auto"
                and not self._looked_up and self._researcher is not None
                and bool(getattr(self._researcher, "searches_web", lambda: False)())
                and DID_NOT_KNOW.search(reply) is not None
                and "in your notes" not in reply.lower()
                and not ABOUT_THEM.search(question))

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
                "pinned": summary.pinned,
                "project": summary.project,
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
