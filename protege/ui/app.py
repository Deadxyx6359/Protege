"""The main window.

One window: a sidebar down the left, scrollback, an input box, a send button, a
status line, and a warning strip that appears only when a lock layer has been
switched off. Every other destination lives in the sidebar -- there is no menu
bar, for the reason documented above `_build_widgets`.

Threading: llama.cpp generation blocks for seconds at a time and Tk is not
thread-safe, so a turn runs on a worker thread and communicates back through a
queue the main thread drains on a timer. Nothing touches a widget from the
worker.

Streaming and blocking interact awkwardly and the resolution matters. Tokens are
shown as they arrive, which means MAIN's draft is briefly on screen before
Layers 4 and 5 have seen it. If the gate then blocks, the streamed text is
erased and replaced with the marker. A user watching closely can see a blocked
draft appear and vanish -- so `_erase_streamed_response` runs before anything
else on a block, and the draft is never left in the scrollback. The alternative,
withholding all output until the gate clears, makes every response feel like a
hang on an 8B model. This is a deliberate trade, not an oversight.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox
from typing import Any

from .. import __version__, plugins, store
from ..audit import AuditLog
from ..chat import BlockDetail, Conversation, Turn, TurnCancelled
from ..lock.pipeline import PipelineResponder
from ..lock.tripwires import TripwireSet
from ..memory.consolidate import Consolidator
from ..memory.live import LiveMemory, new_session_id, parse_remember_calls
from ..models import ModelManager
from ..models.base import ModelError
from ..personality.prompt import build_personality_prompt
from ..projects import DEFAULT_PROJECT, ensure_project, list_projects
from ..retention import overdue_for_relock, review_queue, summarize
from ..schemas import Manifest, Personality, PersonalityProfile, Settings
from ..security import netguard
from ..security.paths import capabilities
from ..unlock import UnlockFlow
from .activity import ActivityIndicator
from .fab import FloatingActionButton
from .document_import import DocumentImportDialog
from .file_dialogs import AttachmentsDialog, ImportDialog
from .history_window import HistoryWindow
from .memory_panel import ConsolidationReviewDialog, MemoryPanel
from .pin_dialog import PinPromptDialog, PinSetupDialog
from .knowledge_web import KnowledgeWebDialog
from .rain import RainCanvas
from .settings_window import SettingsWindow
from .sidebar import Sidebar
from .skills_window import SkillsWindow
from .unlock_dialog import TopicManagerDialog, UnlockDialog
from .vault_browser import VaultBrowser
from . import theme
from .widgets import DANGER_FG, MUTED_FG, WARNING_BG, ThemedScrolledText

POLL_MS = 40
INPUT_LINES = 4
HISTORY_LIMIT = 40
# Readable measure. Wider screens get more rain, not longer lines.
CHAT_COLUMN_WIDTH = 860


class ProtegeWindow(tk.Tk):
    def __init__(self, vault: Path, manifest: Manifest, settings: Settings, personality: Personality) -> None:
        super().__init__()
        # Theme first: the option database only affects widgets created after
        # its entries exist, and everything below is a widget.
        theme.install(self)
        theme.apply_window_chrome(self)
        self.vault = Path(vault)
        self.manifest = manifest
        self.settings = settings
        self.personality = personality
        self.project = settings.current_project or DEFAULT_PROJECT
        ensure_project(self.vault, self.project)

        self.manager = ModelManager(settings)
        self.conversation = Conversation()
        self.session_id = new_session_id()
        self._transcript: list[str] = []
        self._turns: list[Turn] = []
        self._block_details: dict[str, BlockDetail] = {}
        self._events: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._busy = False
        self._stream_marker: str | None = None
        # Whether any non-whitespace token has arrived for the current turn.
        self._stream_started = False
        # (filename, text) pairs attached this session; injected into context
        # at their own budget priority and cleared on new session.
        self._attachments: list[tuple[str, str]] = []
        # Cancellation. `_turn_id` tags every queued event so a stopped
        # turn's late output can be identified and dropped; `_cancelled`
        # is what the streaming callbacks read to unwind the generation.
        self._cancelled = threading.Event()
        self._turn_id = 0
        self._last_user_text = ""

        self.audit = AuditLog(self.vault, enabled=settings.logging_enabled)
        self.responder = self._build_responder()
        self.memory = self._build_memory()
        self._plugins: list = []
        self._plugin_errors: list[str] = []

        self.title("Protege")
        self.geometry(f"{theme.px(1180)}x{theme.px(780)}")
        self.minsize(theme.px(820), theme.px(560))
        # Maximised on boot: the layout is built around a fixed-width reading
        # column with rain filling the rest, so more screen means more rain
        # rather than longer lines -- it is strictly better full-size.
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._bind_shortcuts()

        self._build_widgets()
        self._refresh_status()
        self._refresh_layer_warning()
        self._sweep_holding()
        self._load_plugins()
        self._check_retention()
        self._poll_id = self.after(POLL_MS, self._drain_events)

    def _bind_shortcuts(self) -> None:
        """Window-wide keys.

        Until now the entire main window had exactly one binding -- Return in
        the input box. Everything else was a trip to the sidebar with the
        mouse, which is fine once and tiring every day.

        Escape is deliberately Stop and nothing else. It is the key people
        already press when they want something to stop happening, and binding
        it to "close the window" instead would be actively hostile mid-answer.
        """
        for sequence, handler in (
            ("<Escape>", lambda: self._stop()),
            ("<Control-n>", lambda: self._new_session()),
            ("<Control-r>", lambda: self._regenerate()),
            ("<Control-k>", lambda: self._knowledge_web()),
            ("<Control-comma>", lambda: self._show_settings()),
        ):
            self.bind_all(sequence, self._only_when_unobstructed(handler))

    def _only_when_unobstructed(self, action):
        """Wrap a shortcut so it is inert while a modal dialog is up.

        `bind_all` binds application-wide, dialogs included. Without this,
        Ctrl+N pressed while the Settings window was open would start a new
        session behind the modal -- invisibly, since the dialog still has the
        grab and the focus.
        """
        def handler(_event: tk.Event) -> None:
            grab = self.grab_current()
            if grab is not None and grab is not self:
                return
            action()

        return handler

    # -- wiring -------------------------------------------------------------

    def _build_responder(self) -> PipelineResponder:
        return PipelineResponder(
            self.vault,
            self._effective_manifest(),
            self._effective_settings(),
            self.personality,
            self.manager,
            project=self.project,
            live_memory=lambda: self.memory.render_for_context() if self.memory else "",
            audit=self.audit,
            attachments=lambda: list(self._attachments),
        )

    def _build_memory(self) -> LiveMemory:
        return LiveMemory(
            self.vault,
            self.project,
            self._effective_manifest(),
            self.responder.gate(),
            session_id=self.session_id,
            enabled=self.settings.memory.enabled,
        )

    def _rewire(self) -> None:
        """Rebuild everything that captured a now-stale manifest or settings."""
        self.manager.update_settings(self.settings)
        self.audit.enabled = self.settings.logging_enabled
        self.responder = self._build_responder()
        self.memory.manifest = self._effective_manifest()
        self.memory.gate = self.responder.gate()
        self.memory.enabled = self.settings.memory.enabled
        self._refresh_status()
        self._refresh_layer_warning()

    def _load_plugins(self) -> None:
        """Load approved plugins and surface whatever they contribute.

        Errors are shown in the scrollback rather than a dialog: a broken plugin
        should be visible without being a modal obstacle to using Protege.
        """
        self._plugins, self._plugin_errors = plugins.load(
            self.vault,
            self.manifest,
            self.settings,
            self.responder.gate(),
            self.manager,
            enabled=self.settings.enabled_plugins,
        )
        for error in self._plugin_errors:
            self._append_system(f"plugin: {error}")

        items: list[tuple[str, Any]] = []
        for _plugin, context in self._plugins:
            items.extend(context.menu_items)
        if not items:
            return

        # Into the sidebar, not a menu bar -- there isn't one.
        self.sidebar.add_plugin_items(items)
        self._append_system(
            f"{len(self._plugins)} plugin(s) loaded, contributing {len(items)} action(s)."
        )
        self.audit.event("plugins_loaded", count=len(self._plugins), errors=len(self._plugin_errors))

    def _show_skills(self) -> None:
        manifest = SkillsWindow(
            self,
            self.vault,
            self.project,
            self.manifest,
            self.settings,
            self.manager,
            self.responder.gate(),
        ).show()
        if manifest is not None and manifest != self.manifest:
            self.manifest = manifest
            store.save_manifest(self.vault, manifest)
            self.audit.event("skill_approvals_changed", count=len(manifest.approved_skills))
            self._rewire()

    def _sweep_holding(self) -> None:
        try:
            removed = Consolidator(
                self.vault, self.project, self.manifest, self.settings, self.manager, self.responder.gate()
            ).sweep_holding()
        except Exception:  # noqa: BLE001 - housekeeping must never block startup
            return
        if removed:
            self._append_system(f"{len(removed)} held transcript(s) passed their retention period and were deleted.")

    # -- construction -------------------------------------------------------

    # There is deliberately no menu bar. Windows draws it natively and ignores
    # Tk's color options, so it renders as a bright white strip across the top
    # of an otherwise black window -- and every destination it offered now
    # lives in the sidebar, which is the navigation surface this UI actually
    # wants. Quit is the window's close button; About sits in the sidebar
    # footer.

    def _build_widgets(self) -> None:
        self.warning_var = tk.StringVar(value="")
        self.warning_label = tk.Label(
            self, textvariable=self.warning_var, anchor="w", justify="left",
            padx=6, pady=4, bg=WARNING_BG, fg=theme.WARNING_FG,
        )

        self._body = tk.Frame(self)
        self._body.pack(side="top", fill="both", expand=True)

        # Sidebar owns the left edge; the rain keeps the right gutter. The chat
        # area stays solid black so the ivory text has nothing to fight.
        self.sidebar = Sidebar(
            self._body,
            actions={
                "new_session": self._new_session,
                "end_session": self._end_session,
                "knowledge_web": self._knowledge_web,
                "unlock": self._unlock_topic,
                "topics": self._topic_manager,
                "skills": self._show_skills,
                "memory": self._show_memory,
                "attachments": self._show_attachments,
                "attach": self._attach_file,
                "import": self._import_file,
                "toggle_everyday": self._toggle_everyday,
                "history": self._show_history,
                "document": self._import_document,
                "prompt": self._show_prompt,
                "vault": self._show_vault,
                "settings": self._show_settings,
                "about": self._show_about,
            },
            projects=[p.name for p in list_projects(self.vault)] or [DEFAULT_PROJECT],
            current_project=self.project,
            on_switch_project=self._switch_project,
            on_new_project=self._new_project,
        )
        self.sidebar.pack(side="left", fill="y")

        # Rain fills whatever the centre column does not take. The chat is a
        # fixed-width column rather than "everything that is left" for two
        # reasons: prose past roughly 100 characters is measurably harder to
        # read, and on a wide screen the leftover space is exactly where the
        # rain wants to be. So widening the window adds rain, not line length.
        stage = tk.Frame(self._body, bg=theme.BG)
        stage.pack(side="top", fill="both", expand=True)

        self.rain_left = RainCanvas(stage, width=theme.px(10))
        self.rain_left.pack(side="left", fill="both", expand=True)
        self.rain_right = RainCanvas(stage, width=theme.px(10))
        self.rain_right.pack(side="right", fill="both", expand=True)
        self.rain_left.start()
        self.rain_right.start()

        column = tk.Frame(stage, bg=theme.BG, width=theme.px(CHAT_COLUMN_WIDTH))
        column.pack(side="left", fill="y")
        column.pack_propagate(False)
        self._column = column

        # width/height of 1: a Text widget otherwise *requests* 80x24
        # characters, and at 11pt mono that demand exceeds the column, so pack
        # clips it. A minimal request hands geometry control to fill/expand.
        self.scrollback = ThemedScrolledText(
            column, wrap="word", state="disabled",
            padx=theme.px(14), pady=theme.px(12), width=1, height=1,
            # No border on the transcript: the theme's default 1px entry
            # outline makes sense on an input you can type into, and turns the
            # reading area into a boxed-in panel.
            highlightthickness=0, relief="flat", bg=theme.BG,
        )
        self.scrollback.pack(side="top", fill="both", expand=True)
        self._configure_tags()

        # Working indicator: directly under the transcript, above the
        # composer, so it appears where the answer will.
        self.activity = ActivityIndicator(column)
        self._composer = self._build_composer(column)

        status = tk.Frame(self, bg=theme.BG_PANEL)
        status.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value="")
        tk.Label(
            status, textvariable=self.status_var, anchor="w", bg=theme.BG_PANEL,
            fg=theme.FG_DIM, font=theme.ui_font(size=theme.UI_SIZE - 1),
            padx=theme.px(14), pady=theme.px(4),
        ).pack(side="left")

        # The + button floats over the chat area, anchored bottom-right.
        self.fab = FloatingActionButton(
            self._body,
            [
                ("New skill", "have the model write a tool", self._show_skills),
                ("Attach file", "add a file to this conversation", self._attach_file),
                ("Import a document", "split a PDF or Word file into topics",
                 self._import_document),
                ("Import file", "save one file into the vault", self._import_file),
                ("Unlock a topic", "teach the model something new", self._unlock_topic),
            ],
        )
        self.fab.place(relx=1.0, rely=1.0, x=theme.px(-26), y=theme.px(-26), anchor="se")

    def _build_composer(self, parent: tk.Misc) -> tk.Frame:
        """The input box, styled as a single card rather than a widget row."""
        shell = tk.Frame(parent, bg=theme.PURPLE_GHOST)
        shell.pack(side="top", fill="x", padx=theme.px(14), pady=(0, theme.px(14)))

        card = tk.Frame(shell, bg=theme.BG_RAISED)
        card.pack(fill="x", padx=1, pady=1)

        self.input = tk.Text(
            card, height=INPUT_LINES, wrap="word", width=1,
            bg=theme.BG_RAISED, fg=theme.FG, insertbackground=theme.PURPLE_BRIGHT,
            relief="flat", highlightthickness=0,
            padx=theme.px(12), pady=theme.px(10), font=theme.font(),
        )
        self.input.pack(side="top", fill="both", expand=True)
        self.input.bind("<Return>", self._on_return)
        self.input.bind("<Up>", self._recall_last)
        self.input.focus_set()

        bar = tk.Frame(card, bg=theme.BG_RAISED)
        bar.pack(side="top", fill="x", padx=theme.px(10), pady=(0, theme.px(8)))
        tk.Label(
            bar, text="Enter to send · Shift+Enter for a new line · Esc to stop · Up to recall",
            bg=theme.BG_RAISED, fg=theme.FG_DIM,
            font=theme.ui_font(size=theme.UI_SIZE - 2),
        ).pack(side="left")
        self.send_button = tk.Button(
            bar, text="Send", command=self._on_send,
            bg=theme.PURPLE, fg=theme.BG, activebackground=theme.PURPLE_BRIGHT,
            activeforeground=theme.BG, relief="flat", borderwidth=0,
            font=theme.ui_font(bold=True), padx=theme.px(18), pady=theme.px(3),
            cursor="hand2",
        )
        self.send_button.pack(side="right")
        return shell

    def _configure_tags(self) -> None:
        # Speaker prefixes carry the purple; body text is plain white. That
        # split is most of what makes the theme read as deliberate.
        mono = theme.font_family()
        self.scrollback.tag_configure(
            "user_prefix", font=(mono, theme.UI_SIZE - 1, "bold"), foreground=theme.PURPLE,
            spacing1=theme.px(14), spacing3=theme.px(2),
        )
        self.scrollback.tag_configure(
            "assistant_prefix", font=(mono, theme.UI_SIZE - 1, "bold"),
            foreground=theme.PURPLE_BRIGHT, spacing1=theme.px(14), spacing3=theme.px(2),
        )
        self.scrollback.tag_configure("user", foreground=theme.FG, spacing3=theme.px(4))
        self.scrollback.tag_configure("assistant", foreground=theme.FG, spacing3=theme.px(8))
        self.scrollback.tag_configure("blocked", foreground=DANGER_FG)
        self.scrollback.tag_configure(
            "system", foreground=MUTED_FG, spacing1=theme.px(8), spacing3=theme.px(8),
            font=theme.ui_font(size=theme.UI_SIZE - 1),
        )
        self.scrollback.tag_configure(
            "detail", foreground=theme.FG_SOFT, lmargin1=theme.px(18), lmargin2=theme.px(18),
            font=theme.ui_font(size=theme.UI_SIZE - 1),
        )
        self.scrollback.tag_configure("link", foreground=theme.PURPLE_BRIGHT, underline=True)

    # -- rendering ----------------------------------------------------------

    def _append(self, text: str, *tags: str) -> None:
        self.scrollback.configure(state="normal")
        self.scrollback.insert("end", text, tags)
        self.scrollback.configure(state="disabled")
        self.scrollback.see("end")

    def _append_system(self, text: str) -> None:
        self._append(f"{text}\n", "system")

    def _render_block(self, turn: Turn) -> None:
        self._append(f"{turn.text}\n", "blocked")
        self._offer_teaching(turn)
        detail = turn.detail
        if detail is None:
            return
        key = f"detail-{len(self._block_details)}"
        self._block_details[key] = detail
        self.scrollback.configure(state="normal")
        self.scrollback.insert("end", "why was this blocked?\n", ("link", key))
        self.scrollback.configure(state="disabled")
        self.scrollback.tag_bind(key, "<Button-1>", lambda _e, k=key: self._show_block_detail(k))
        self.scrollback.tag_bind(key, "<Enter>", lambda _e: self.scrollback.configure(cursor="hand2"))
        self.scrollback.tag_bind(key, "<Leave>", lambda _e: self.scrollback.configure(cursor=""))

    def _offer_teaching(self, turn: Turn) -> None:
        """After a decline, say how to actually teach the topic.

        Explaining it in the chat does nothing -- the directive refuses to be
        widened by conversation, which is the whole security property. Without
        this hint a user reasonably tries to teach by talking, gets stonewalled
        with no next step, and concludes the app is broken rather than that
        they are using the wrong door.
        """
        import re as _re

        from ..lock.directive import DECLINE_PATTERN
        from ..vault import scan_vault

        match = _re.search(DECLINE_PATTERN, turn.text)
        if not match:
            return
        declined = match.group(1)
        if self.manifest.is_unlocked(declined):
            return

        # The label in `[LOCKED: x]` is the model's own guess at what the
        # subject is called -- it is not looked up against the vault. Ask about
        # voltage with a note tagged `electronics` and the model may well say
        # `physics`, because that is what *it* considers the subject. Offering
        # to teach the declined name alone would point at a topic with no notes
        # behind it, which is worse than no advice. So the real teachable
        # candidates -- locked topics that actually have notes -- are offered
        # alongside it.
        try:
            scan = scan_vault(self.vault)
        except Exception:  # noqa: BLE001 - guidance must never break a turn
            scan = None

        candidates: list[str] = []
        if scan is not None:
            with_notes = {t for note in scan.notes if note.ok for t in note.topics}
            candidates = sorted(t for t in with_notes if not self.manifest.is_unlocked(t))

        self._append(
            f"'{declined}' is locked. Explaining it in this conversation will not unlock it -- "
            "nothing said in a chat can widen what the model may use.\n",
            "detail",
        )
        if candidates:
            self._append(
                f"That name is the model's own guess at the subject and need not match your tags. "
                f"You have notes on these locked topics: {', '.join(candidates)}.\n",
                "detail",
            )
        else:
            self._append(
                f"No notes are tagged with a locked topic yet. Write one tagged "
                f"topics: [{declined}], then run the unlock.\n",
                "detail",
            )

        offers = candidates or [declined]
        self.scrollback.configure(state="normal")
        for topic in offers:
            key = f"teach-{len(self._block_details)}-{topic}-{self.scrollback.index('end')}"
            self.scrollback.insert("end", f"teach {topic} now\n", ("link", key))
            self.scrollback.tag_bind(key, "<Button-1>", lambda _e, t=topic: self._teach_topic(t))
            self.scrollback.tag_bind(
                key, "<Enter>", lambda _e: self.scrollback.configure(cursor="hand2")
            )
            self.scrollback.tag_bind(key, "<Leave>", lambda _e: self.scrollback.configure(cursor=""))
        self.scrollback.configure(state="disabled")

    def _teach_topic(self, topic: str) -> None:
        """Open the unlock flow with this topic pre-filled."""
        flow = UnlockFlow(self.vault, self.manifest, self.settings, self.manager,
                          tripwires=TripwireSet.load(self.vault))
        dialog = UnlockDialog(self, flow)
        dialog.topic_var.set(topic)
        manifest = dialog.show()
        if manifest is not None:
            self.manifest = manifest
            store.save_manifest(self.vault, manifest)
            self._rewire()
            self._append_system(f"unlocked: {topic}")

    def _show_block_detail(self, key: str) -> None:
        detail = self._block_details.get(key)
        if detail is None:
            return
        window = tk.Toplevel(self)
        window.title("Blocked response")
        window.geometry("600x380")
        theme.apply_window_chrome(window)
        text = ThemedScrolledText(window, wrap="word", padx=8, pady=8)
        text.pack(fill="both", expand=True)
        text.insert("1.0", detail.summary())
        if detail.layer == "tripwires":
            text.insert(
                "end",
                "\n\nTripwires are deterministic pattern matches. They are fast, dumb, and produce "
                "false positives by design. If this block looks wrong, edit the pattern list for "
                "this topic in Settings -> Tripwires.",
            )
        elif detail.layer == "auditor":
            text.insert(
                "end",
                "\n\nThe auditor is a small model with both false positives and false negatives. "
                "It is a meaningful filter, not a guarantee.",
            )
        elif detail.layer == "error":
            text.insert(
                "end",
                "\n\nA lock layer failed. Protege blocks rather than passing a response it could "
                "not fully check.",
            )
        text.configure(state="disabled")
        tk.Button(window, text="Close", command=window.destroy).pack(side="bottom", pady=4)

    # -- status -------------------------------------------------------------

    def _refresh_status(self) -> None:
        tier = capabilities(self.manifest.trust_tier)
        model_status = self.manager.status()
        bits = [
            "EVERYDAY MODE" if self.settings.everyday_mode else f"Tier {tier.tier}",
            f"{len(self.manifest.unlocked_topics)} unlocked",
            f"profile: {self.personality.active_profile}",
        ]
        if self._turns and self._turns[-1].budget_note:
            bits.append(self._turns[-1].budget_note)
        if self.memory and self.memory.entries:
            bits.append(f"memory: {len(self.memory.entries)}")
        if self._attachments:
            bits.append(f"attached: {len(self._attachments)}")
        if model_status.detail:
            bits.append(model_status.detail)
        self.status_var.set("   |   ".join(bits))

        if hasattr(self, "sidebar"):
            self.sidebar.set_projects(
                [p.name for p in list_projects(self.vault)] or [DEFAULT_PROJECT], self.project
            )
            self.sidebar.set_status(
                f"{tier.label}\n{len(self.manifest.unlocked_topics)} topic(s) unlocked"
            )
            self.sidebar.set_everyday(self.settings.everyday_mode)

    def _refresh_layer_warning(self) -> None:
        """The strip across the top. Everyday mode outranks a disabled layer.

        Everyday mode is not a warning -- it is a mode the user chose -- but it
        has to be as unmissable as one, because the entire difference between
        the two modes is invisible in the answers themselves. A reply that
        arrives without a `[LOCKED: ...]` marker looks the same whether the
        topic was taught or the constraint was off.
        """
        layers = self.settings.lock_layers
        if self.settings.everyday_mode:
            self.warning_var.set(
                "EVERYDAY MODE -- the knowledge lock is off. Answers come from the "
                "model's full training, not from what you have taught it. "
                "Nothing has been unlocked; switch back and the lock is exactly as "
                "you left it."
            )
            self.warning_label.pack(side="top", fill="x", before=self._body)
        elif layers.any_disabled:
            self.warning_var.set(
                f"WARNING: lock layer(s) disabled -- {', '.join(layers.disabled_names)}. "
                "Locked knowledge may reach you unfiltered."
            )
            self.warning_label.pack(side="top", fill="x", before=self._body)
        else:
            self.warning_label.pack_forget()

    def _show_history(self) -> None:
        HistoryWindow(self, self.vault, self.settings).show()

    # -- retention -------------------------------------------------------------

    def _check_retention(self) -> None:
        """Say what has gone stale, and relock it only if asked to.

        Runs once at launch rather than on a timer: a nag that can interrupt
        you mid-thought is a nag that gets disabled. Nothing here blocks, and
        nothing here is modal -- it is two lines in the scrollback next to
        everything else the session has to say for itself.
        """
        retention = self.settings.retention
        if not retention.enabled or not retention.review_after_days:
            return

        if retention.auto_relock:
            overdue = overdue_for_relock(
                self.manifest,
                review_after_days=retention.review_after_days,
                grace_days=retention.grace_days,
            )
            for age in overdue:
                self.manifest = self.manifest.with_relocked(
                    age.topic,
                    note=f"auto-relocked: not demonstrated in {age.days} days",
                )
                self.audit.event("auto_relock", topic=age.topic, days=age.days)
            if overdue:
                store.save_manifest(self.vault, self.manifest)
                self._rewire()
                self._append_system(
                    f"auto-relocked {len(overdue)} topic(s) not demonstrated in over "
                    f"{retention.review_after_days + retention.grace_days} days: "
                    f"{', '.join(a.topic for a in overdue)}. Teach them again to "
                    "bring them back."
                )

        queue = review_queue(self.manifest, review_after_days=retention.review_after_days)
        if queue:
            self._append_system(
                summarize(queue, review_after_days=retention.review_after_days)
                + " Open Knowledge, pick one, and press Review."
            )

    # -- everyday mode --------------------------------------------------------

    def _effective_manifest(self) -> Manifest:
        """What the responder is given -- never what is stored.

        `self.manifest` stays the true record in every mode, so the knowledge
        web, the topic manager and the unlock flow keep showing what has
        actually been taught even while the lock is standing down.
        """
        if self.settings.everyday_mode:
            return self.manifest.unrestricted_view()
        return self.manifest

    def _effective_settings(self) -> Settings:
        """Settings as the responder sees them.

        Retrieval stays *on* in everyday mode. It is the user's own vault, and
        the point of the mode is a normal assistant that can still see their
        notes -- switching retrieval off would make everyday mode dumber about
        the user's own material than Protege mode is.
        """
        if not self.settings.everyday_mode:
            return self.settings
        return replace(
            self.settings,
            lock_layers=replace(
                self.settings.lock_layers,
                directive=False, tripwires=False, auditor=False,
            ),
        )

    def _toggle_everyday(self) -> None:
        turning_on = not self.settings.everyday_mode
        if turning_on and not messagebox.askokcancel(
            "Everyday mode",
            "Turn the knowledge lock off for this assistant?\n\n"
            "It will answer from its full training instead of only what you have "
            "taught it. Your unlocked topics are not changed -- switching back "
            "restores the lock exactly as it is now.\n\n"
            "The banner across the top of the window shows while it is on.",
            parent=self,
        ):
            return

        self.settings = replace(self.settings, everyday_mode=turning_on)
        store.save_settings(self.vault, self.settings)
        self.audit.event("everyday_mode", enabled=turning_on)
        self._rewire()
        self._append_system(
            "everyday mode ON -- answering from full training; nothing was unlocked"
            if turning_on else
            "everyday mode OFF -- back to teaching-gated answers"
        )

    # -- sending ------------------------------------------------------------

    def _on_return(self, event: tk.Event) -> str:
        if event.state & 0x0001:  # Shift+Enter inserts a newline
            return ""
        self._on_send()
        return "break"

    def _on_send(self, text: str | None = None) -> None:
        if self._busy:
            return
        if text is None:
            text = self.input.get("1.0", "end-1c").strip()
        if not text:
            return

        status = self.manager.status()
        if not status.library_available:
            messagebox.showerror(
                "No inference library",
                "llama-cpp-python is not installed, so Protege cannot run a model.\n\n"
                "    pip install -r requirements.txt\n\n"
                "See the README for the CUDA build needed to use the GPU.",
            )
            return
        if not status.main_configured:
            messagebox.showerror(
                "No model configured",
                "No MAIN model is configured. Set the path to a .gguf file in Settings.\n\n"
                "Protege will not substitute a placeholder model.",
            )
            return
        if not status.auditor_configured:
            messagebox.showerror(
                "No auditor configured",
                "No AUDITOR model is configured, so Layer 5 cannot run and every response would "
                "block.\n\nSet an auditor path in Settings. Pointing it at the same file as MAIN is "
                "supported and loads the model only once.",
            )
            return

        self.input.delete("1.0", "end")
        self._last_user_text = text
        self._append("You\n", "user_prefix")
        self._append(f"{text}\n", "user")
        self._transcript.append(f"USER: {text}")

        self._set_busy(True)
        self._append("Protege\n", "assistant_prefix")
        self._stream_marker = self.scrollback.index("end-1c")
        self._stream_started = False
        self._cancelled.clear()
        self._turn_id += 1
        threading.Thread(target=self._run_turn, args=(text, self._turn_id),
                         daemon=True).start()

    def _run_turn(self, text: str, turn_id: int) -> None:
        def check() -> None:
            if self._cancelled.is_set():
                raise TurnCancelled()

        def on_token(piece: str) -> None:
            check()
            self._events.put(("token", (turn_id, piece)))

        def on_stage(stage: str) -> None:
            # Checked at every layer boundary as well as every token, so Stop
            # pressed while MAIN is streaming aborts before the auditor -- the
            # slowest phase -- is ever started.
            check()
            self._events.put(("stage", (turn_id, stage)))

        try:
            turn = self.responder.respond(
                text, self.conversation, on_token=on_token, on_stage=on_stage,
            )
            self._events.put(("done", (turn_id, turn)))
        except TurnCancelled:
            # The UI has already reset itself; nothing to report.
            pass
        except ModelError as exc:
            self._events.put(("error", (turn_id, str(exc))))
        except Exception as exc:  # noqa: BLE001
            # Fail closed. An unexpected exception during a turn surfaces as a
            # blocked response, never as partial text that skipped the layers
            # which had not run yet.
            self._events.put(("error", (turn_id, f"{type(exc).__name__}: {exc}")))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, tagged = self._events.get_nowait()
                turn_id, payload = tagged
                if turn_id != self._turn_id:
                    # A cancelled turn whose worker had already queued this, or
                    # one still inside the auditor when Stop was pressed. There
                    # is no way to kill the thread, so its output is discarded
                    # here instead -- silently, because the user has already
                    # been told the turn was stopped.
                    continue
                if kind == "token":
                    # Qwen3's template emits a newline pair around its (now
                    # suppressed) reasoning block, so the first tokens of every
                    # reply are blank lines. The finished Turn is stripped, but
                    # the *stream* is not -- without this the user watches two
                    # empty lines print under every "Protege" label.
                    if not self._stream_started:
                        payload = payload.lstrip()
                        if not payload:
                            continue
                        self._stream_started = True
                    self._append(payload, "assistant")
                elif kind == "stage":
                    self.activity.set_stage(payload)
                elif kind == "done":
                    self._finish_turn(payload)
                elif kind == "error":
                    self._fail_turn(payload)
        except queue.Empty:
            pass
        # Reschedule only while the window is still real. Without this the
        # timer outlives `destroy()` and Tk reports "invalid command name"
        # against a torn-down interpreter, once every POLL_MS, forever.
        if self.winfo_exists():
            self._poll_id = self.after(POLL_MS, self._drain_events)

    def _finish_turn(self, turn: Turn) -> None:
        if turn.blocked:
            self._erase_streamed_response()
            self._render_block(turn)
            self._transcript.append(f"PROTEGE (blocked): {turn.text}")
        else:
            calls, cleaned = parse_remember_calls(turn.text)
            if cleaned != turn.text:
                # Redraw without the tool-call lines rather than leaving them
                # in the scrollback where the user would read them as output.
                self._erase_streamed_response()
                if cleaned:
                    self._append(f"{cleaned}\n", "assistant")
                else:
                    # Observed with the real model: despite instructions, a
                    # reply can be nothing but the tool call. An empty
                    # response block reads as a hang, so say what happened.
                    self._append(
                        "(the model wrote a memory note instead of a reply -- "
                        "see Session -> Session memory)\n",
                        "detail",
                    )
            self._append("\n")
            # A compliant decline reaches this branch, not the blocked one: a
            # reply that is only `[LOCKED: x]` conveys no knowledge, so the gate
            # short-circuits and allows it. That is the *usual* way a user meets
            # the marker, so the teaching guidance has to hang off the text
            # rather than off turn.blocked.
            self._offer_teaching(turn)
            self._record_remembered(calls)
            self._transcript.append(f"PROTEGE: {cleaned or turn.text}")

        self.conversation.add_user(turn.user_text)
        self.conversation.add_assistant(turn.text)
        if len(self.conversation.messages) > HISTORY_LIMIT:
            del self.conversation.messages[:-HISTORY_LIMIT]

        for notice in turn.notices:
            self._append_system(notice)

        self._turns.append(turn)
        self._set_busy(False)
        self._refresh_status()

    def _record_remembered(self, calls) -> None:
        for call in calls:
            result = self.memory.write(
                call.content,
                topics=[call.topic],
                source="proposed",
                importance=call.importance,
            )
            if result.accepted:
                self._append_system(f"remembered: {call.content}")
            else:
                self._append_system(f"memory write refused: {result.reason}")

    def _fail_turn(self, message: str) -> None:
        self._erase_streamed_response()
        self._append(f"[error] {message}\n", "blocked")
        self._append(
            "No response was produced. Protege blocks rather than passing output it could not "
            "fully check.\n",
            "detail",
        )
        self._set_busy(False)
        self._refresh_status()

    def _stop(self) -> None:
        """Abandon the turn in progress.

        Bumping the turn id first is what makes this safe: any event the worker
        has already queued, or queues later from inside an uninterruptible
        auditor call, no longer matches and is dropped. The conversation is not
        updated -- `_finish_turn` never runs -- so a stopped turn leaves no
        trace in the history the model will see next time.
        """
        if not self._busy:
            return
        self._cancelled.set()
        self._turn_id += 1
        self._erase_streamed_response()
        self._append("[stopped]\n", "detail")
        self._append(
            "Nothing was added to the conversation. Press Up in the input box to "
            "bring back what you asked.\n",
            "detail",
        )
        self._set_busy(False)
        self._refresh_status()

    def _regenerate(self) -> None:
        """Ask the last question again."""
        if self._busy or not self._last_user_text:
            return
        self._on_send(self._last_user_text)

    def _recall_last(self, _event: tk.Event) -> str | None:
        """Up-arrow in an empty box brings back the last thing you sent.

        Only when empty: Up is still cursor movement in a draft you are editing,
        and stealing it there would be worse than not having the shortcut.
        """
        if self.input.get("1.0", "end-1c").strip() or not self._last_user_text:
            return None
        self.input.insert("1.0", self._last_user_text)
        return "break"

    def _erase_streamed_response(self) -> None:
        if self._stream_marker is None:
            return
        self.scrollback.configure(state="normal")
        self.scrollback.delete(self._stream_marker, "end-1c")
        self.scrollback.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        # The Send button becomes Stop rather than greying out. A disabled
        # button during a two-minute generation says "wait"; there was nothing
        # anywhere that said "you may stop this", and there was no way to.
        self.send_button.configure(
            text="Stop" if busy else "Send",
            command=self._stop if busy else self._on_send,
            bg=theme.PURPLE_DIM if busy else theme.PURPLE,
            activebackground=theme.DANGER if busy else theme.PURPLE_BRIGHT,
        )
        if busy:
            # Packed only while working, so it occupies no space at rest.
            # `before` the composer: pack order is creation order otherwise,
            # and a late pack() lands the indicator *below* the input box
            # rather than where the answer is about to appear.
            self.activity.pack(side="top", fill="x", before=self._composer,
                               padx=theme.px(20), pady=(0, theme.px(8)))
            self.activity.start("retrieving")
        else:
            self.activity.stop()
            self.activity.pack_forget()
            self._stream_marker = None

    # -- menu actions -------------------------------------------------------

    def _attach_file(self) -> None:
        from .file_dialogs import pick_text_file

        picked = pick_text_file(self)
        if picked is None:
            return
        self._attachments.append(picked)
        self._append_system(f"attached {picked[0]} ({len(picked[1]):,} chars) to this conversation")
        self._refresh_status()

    def _show_attachments(self) -> None:
        result = AttachmentsDialog(self, self._attachments).show()
        if result is not None:
            self._attachments = result
            self._refresh_status()

    def _import_file(self) -> None:
        target = ImportDialog(self, self.vault, self.project, self.manifest).show()
        if target is not None:
            rel = target.relative_to(self.vault).as_posix()
            self._append_system(f"imported into the vault: {rel}")
            self.audit.event("file_imported", path=rel)

    def _import_document(self) -> None:
        written = DocumentImportDialog(self, self.vault, self.project, self.manifest).show()
        if not written:
            return
        for path in written:
            self.audit.event("document_section_imported",
                             path=path.relative_to(self.vault).as_posix())
        self._append_system(
            f"imported {len(written)} section(s) as locked topics. Open Knowledge to "
            "see them; each still has to be unlocked by explaining it."
        )
        self._refresh_status()

    def _pin_last(self) -> None:
        if not self._turns:
            messagebox.showinfo("Pin", "Nothing to pin yet.")
            return
        last = self._turns[-1]
        if last.blocked:
            messagebox.showinfo("Pin", "That response was blocked and cannot be pinned.")
            return
        topics = self.manifest.unlocked_topics
        result = self.memory.write(
            last.text, topics=[topics[0]] if topics else [], source="pinned", importance=4
        )
        if result.accepted:
            self._append_system("pinned to session memory")
        else:
            messagebox.showerror("Not pinned", result.reason)
        self._refresh_status()

    def _show_memory(self) -> None:
        MemoryPanel(self, self.memory, self.manifest.unlocked_topics).show()
        self._refresh_status()

    def _show_prompt(self) -> None:
        view = self._turns[-1].prompt_view if self._turns else ""
        window = tk.Toplevel(self)
        window.title("Assembled prompt")
        window.geometry("820x640")
        theme.apply_window_chrome(window)
        text = ThemedScrolledText(window, wrap="word", padx=8, pady=8)
        text.pack(fill="both", expand=True)
        text.insert("1.0", view or "Send a message to see exactly what MAIN received.")
        text.configure(state="disabled")

    def _unlock_topic(self) -> None:
        flow = UnlockFlow(self.vault, self.manifest, self.settings, self.manager,
                          tripwires=TripwireSet.load(self.vault))
        manifest = UnlockDialog(self, flow).show()
        if manifest is not None:
            self.manifest = manifest
            store.save_manifest(self.vault, manifest)
            self._rewire()
            self._append_system(f"unlocked: {manifest.unlocked_topics[-1] if manifest.unlocked_topics else ''}")

    def _topic_manager(self) -> None:
        flow = UnlockFlow(self.vault, self.manifest, self.settings, self.manager,
                          tripwires=TripwireSet.load(self.vault))
        manifest = TopicManagerDialog(self, flow).show()
        if manifest is not None and manifest != self.manifest:
            self.manifest = manifest
            store.save_manifest(self.vault, manifest)
            self._rewire()

    def _knowledge_web(self) -> None:
        flow = UnlockFlow(self.vault, self.manifest, self.settings, self.manager,
                          tripwires=TripwireSet.load(self.vault))
        manifest = KnowledgeWebDialog(self, flow).show()
        if manifest is not None and manifest != self.manifest:
            self.manifest = manifest
            store.save_manifest(self.vault, manifest)
            self._rewire()

    def _new_project(self) -> None:
        from tkinter import simpledialog

        from ..projects import validate_name
        from ..schemas import SchemaError

        name = simpledialog.askstring("New project", "Project name:", parent=self)
        if not name:
            return
        try:
            name = validate_name(name)
        except SchemaError as exc:
            messagebox.showerror("Project", str(exc), parent=self)
            return
        ensure_project(self.vault, name)
        self._switch_project(name)

    def _show_vault(self) -> None:
        changed = VaultBrowser(self, self.vault, self.manifest, self.project).show()
        if not changed:
            return
        # A note may have been retagged or deleted, and the current project may
        # have been renamed out from under us. Fall back to a project that
        # still exists before anything tries to write to it.
        existing = [p.name for p in list_projects(self.vault)]
        if existing and self.project not in existing:
            self._switch_project(existing[0])
        else:
            self._rewire()
        self._append_system("vault updated")

    def _show_settings(self) -> None:
        SettingsWindow(
            self,
            self.vault,
            self.manifest,
            self.settings,
            self.personality,
            on_apply=self._apply_settings,
            prompt_view=self._turns[-1].prompt_view if self._turns else "",
            on_preview=self._live_preview,
        )

    def _apply_settings(self, manifest: Manifest, settings: Settings, personality: Personality) -> None:
        tier_changed = manifest.trust_tier != self.manifest.trust_tier
        plugins_changed = settings.enabled_plugins != self.settings.enabled_plugins
        self.manifest = manifest
        self.settings = settings
        self.personality = personality
        self._rewire()
        if tier_changed:
            self.audit.event("trust_tier_changed", tier=manifest.trust_tier)
        if plugins_changed:
            self._load_plugins()
        self._append_system("settings applied")

    def _live_preview(self, profile: PersonalityProfile) -> str:
        """Regenerate the last response under candidate slider positions.

        Nothing is committed: the profile is passed to a throwaway responder and
        the result is shown in the settings panel only. This is how the sliders
        actually get calibrated, so it works on the real last turn rather than
        on a canned example.
        """
        if not self._turns:
            return "Send a message first -- preview regenerates the most recent response."
        last = self._turns[-1]
        preview_responder = PipelineResponder(
            self.vault, self.manifest, self.settings, self.personality, self.manager,
            project=self.project, profile=profile,
        )
        history = Conversation(messages=list(self.conversation.messages[:-2]))
        turn = preview_responder.respond(last.user_text, history)

        header = build_personality_prompt(self.personality, profile).text or "(all neutral)"
        return f"{header}\n\n{'-' * 60}\n\n{turn.text}"

    def _switch_project(self, name: str) -> None:
        if name == self.project or self._busy:
            return
        self.project = name
        ensure_project(self.vault, name)
        self.settings = replace_settings(self.settings, current_project=name)
        store.save_settings(self.vault, self.settings)
        self._new_session()
        self._rewire()
        self._append_system(f"switched to project {name!r}")

    def _new_session(self) -> None:
        if self._busy:
            return
        self.conversation = Conversation()
        self._turns.clear()
        self._transcript.clear()
        self._block_details.clear()
        self._attachments.clear()
        self.session_id = new_session_id()
        self.memory = self._build_memory()
        self.scrollback.configure(state="normal")
        self.scrollback.delete("1.0", "end")
        self.scrollback.configure(state="disabled")
        self._append_system(f"New session in project {self.project!r}.")
        self._refresh_status()

    def _end_session(self) -> None:
        if self._busy:
            return
        if not self.memory.entries:
            self._append_system("Nothing was written to memory this session; nothing to consolidate.")
            self._new_session()
            return
        if not self.settings.memory.consolidate_on_session_end:
            self._new_session()
            return

        consolidator = Consolidator(
            self.vault, self.project, self.manifest, self.settings, self.manager, self.responder.gate()
        )
        self._append_system("Consolidating session memory...")
        self.update_idletasks()
        try:
            result = consolidator.consolidate(self.memory, "\n\n".join(self._transcript))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Consolidation failed", f"{type(exc).__name__}: {exc}")
            return

        ConsolidationReviewDialog(self, consolidator, result).show()
        self._new_session()

    def _show_about(self) -> None:
        status = self.manager.status()
        messagebox.showinfo(
            "About Protege",
            f"Protege {__version__}\n\n"
            f"Vault: {self.vault}\n"
            f"Project: {self.project}\n"
            f"Unlocked topics: {len(self.manifest.unlocked_topics)}\n"
            f"Trust tier: {capabilities(self.manifest.trust_tier).label}\n"
            f"Network guard: {'installed' if netguard.is_installed() else 'NOT INSTALLED'}\n"
            f"Inference: {'llama.cpp, in-process' if status.library_available else 'unavailable'}\n\n"
            "All inference is local. This application opens no network connections.\n"
            "The PIN is an access convenience, not encryption.",
        )

    def destroy(self) -> None:
        """Cancel the poll timer before tearing the interpreter down.

        `after` callbacks survive the widget that scheduled them. A pending
        `_drain_events` firing into a destroyed window is harmless in a running
        application -- nobody sees the stderr line -- but under a test run it
        lands in whichever test happens to be pumping the event loop next, and
        turns an unrelated test red depending on the order they ran in.
        """
        poll_id = getattr(self, "_poll_id", None)
        if poll_id is not None:
            try:
                self.after_cancel(poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        super().destroy()

    def _on_close(self) -> None:
        if self._busy and not messagebox.askokcancel(
            "Quit", "A response is still being generated. Quit anyway?"
        ):
            return
        if self.memory.entries and messagebox.askyesno(
            "Session memory",
            f"{len(self.memory.entries)} memory entr(y/ies) were written this session. "
            "Consolidate before quitting?",
        ):
            self._end_session()
        self.rain_right.stop()
        try:
            self.manager.close()
        finally:
            self.destroy()


def replace_settings(settings: Settings, **changes) -> Settings:
    from dataclasses import replace

    return replace(settings, **changes)


def run_app(vault: Path, manifest: Manifest, settings: Settings, personality: Personality) -> int:
    # Before any window exists: the taskbar resolves its icon from the
    # AppUserModelID, not from iconbitmap, and would otherwise show Python's.
    theme.set_app_id()
    try:
        window = ProtegeWindow(vault, manifest, settings, personality)
    except tk.TclError as exc:
        print(f"Cannot start the user interface: {exc}")
        print("Protege needs a graphical display and a Tk-enabled Python build.")
        return 3

    # PIN before anything is shown. The window exists first because Tk dialogs
    # need a root, so it is created withdrawn and revealed only on success.
    window.withdraw()
    if not manifest.pin.is_set:
        encoded = PinSetupDialog(window).show()
        if not encoded:
            window.destroy()
            return 1
        window.manifest = manifest.with_pin(encoded)
        store.save_manifest(vault, window.manifest)
        window._rewire()
    else:
        if PinPromptDialog(window, manifest.pin.hash).show() is not True:
            window.destroy()
            return 1

    window.deiconify()
    # Focus set during construction happened while the root was withdrawn and
    # did not stick; now the window is mapped, put the caret in the input box
    # so the user can type immediately.
    window.input.focus_force()
    window._append_system(
        f"Protege {__version__} -- {len(window.manifest.unlocked_topics)} topic(s) unlocked, "
        f"{capabilities(window.manifest.trust_tier).label}."
    )
    window.mainloop()
    return 0
