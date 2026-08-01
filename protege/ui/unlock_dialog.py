"""The unlock dialog.

Pick a topic and its source notes, watch MAIN demonstrate understanding, then
approve or reject. The demonstration runs on a worker thread -- three
generations on an 8B model is tens of seconds -- and the approve button stays
disabled until it finishes and passes the gate.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from typing import Any

from ..schemas import SchemaError
from ..unlock import UnlockError, UnlockFlow, UnlockProposal, available_topics, validate_new_topic
from ..vault import scan_vault
from . import theme
from .widgets import DANGER_FG, MUTED_FG, ModalDialog, button_row, read_only_text, set_text

POLL_MS = 60


class UnlockDialog(ModalDialog):
    """Returns the updated Manifest on approval, or None.

    Doubles as the review dialog. A retention check is the same ritual run
    again on an already-unlocked topic -- same notes, same demonstration, same
    judgement by the user -- and giving it a second, simpler dialog would
    inevitably make it the weaker one. `review_topic` switches the wording and
    what gets written to the manifest; everything between is identical.
    """

    def __init__(self, parent: tk.Misc, flow: UnlockFlow, *,
                 review_topic: str | None = None) -> None:
        self._review_topic = review_topic
        super().__init__(
            parent,
            f"Review {review_topic}" if review_topic else "Unlock a topic",
            width=820, height=680,
        )
        self.flow = flow
        self._events: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._proposal: UnlockProposal | None = None
        self._running = False

        self.scan = scan_vault(flow.vault)

        tk.Label(
            self,
            text=(
                f"{review_topic!r} was unlocked a while ago. Run the demonstration "
                "again against your notes as they stand now. Nothing is lost if it "
                "goes badly -- the topic stays unlocked and stays due, and the fix "
                "is to rewrite the notes."
                if review_topic else
                "A topic is unlocked by teaching it. Choose the notes you have written, and "
                "Protege will ask the model to show it understood them."
            ),
            wraplength=780, justify="left", fg=MUTED_FG,
        ).pack(anchor="w", padx=12, pady=(12, 8))

        self._build_topic_row()
        self._build_note_list()
        self._build_review()

        self.buttons = button_row(
            self,
            [
                ("Approve", self._approve),
                ("Reject", self.on_cancel),
                ("Demonstrate", self._demonstrate),
            ],
        )
        self.buttons.pack(side="bottom", fill="x", padx=8)
        self._approve_button = self.buttons.winfo_children()[0]
        self._demo_button = self.buttons.winfo_children()[2]
        self._approve_button.configure(state="disabled")

        self.after(POLL_MS, self._drain)

    # -- construction -------------------------------------------------------

    def _build_topic_row(self) -> None:
        row = tk.Frame(self)
        row.pack(fill="x", padx=12, pady=4)
        tk.Label(row, text="Topic", width=10, anchor="w").pack(side="left")
        self.topic_var = tk.StringVar(value=self._review_topic or "")
        self.topic_entry = tk.Entry(row, textvariable=self.topic_var, width=32)
        self.topic_entry.pack(side="left")
        if self._review_topic:
            # The topic is not a choice in a review; it is the subject.
            self.topic_entry.configure(state="readonly")

        suggestions = available_topics(self.scan, self.flow.manifest)
        if suggestions:
            tk.Label(row, text="  from your notes:", fg=MUTED_FG).pack(side="left")
            self.suggestion_var = tk.StringVar(value=suggestions[0])
            menu = tk.OptionMenu(row, self.suggestion_var, *suggestions,
                                 command=lambda value: self.topic_var.set(value))
            menu.pack(side="left")
            # Apply the value the menu is already displaying. An OptionMenu
            # fires its command only on an active selection, so without this
            # the dropdown shows a topic that was never written to the Topic
            # field -- it looks chosen, Demonstrate then rejects an empty id,
            # and the error blames the user for a value the UI appeared to have
            # filled in for them.
            self.topic_var.set(suggestions[0])
        else:
            tk.Label(
                row,
                text="  (no locked topics found in your notes -- type one below)",
                fg=MUTED_FG,
            ).pack(side="left")

    def _build_note_list(self) -> None:
        tk.Label(self, text="Source notes (ctrl-click to select several)", anchor="w").pack(
            anchor="w", padx=12, pady=(8, 2)
        )
        frame = tk.Frame(self)
        frame.pack(fill="both", expand=False, padx=12)
        scrollbar = ttk.Scrollbar(frame, orient="vertical")
        self.note_list = tk.Listbox(
            frame, selectmode="extended", height=8, yscrollcommand=scrollbar.set, exportselection=False
        )
        scrollbar.configure(command=self.note_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.note_list.pack(side="left", fill="both", expand=True)

        # Every note in the vault, including ones currently invisible to
        # retrieval -- that is the point of this dialog.
        self._note_paths = [n.rel_path for n in self.scan.notes if n.ok]
        for rel in self._note_paths:
            self.note_list.insert("end", rel)

    def _build_review(self) -> None:
        tk.Label(self, text="Demonstration", anchor="w").pack(anchor="w", padx=12, pady=(10, 2))
        self.review = read_only_text(self, "Choose a topic and its notes, then press Demonstrate.", height=16)
        self.review.pack(fill="both", expand=True, padx=12)
        self.status = tk.Label(self, text="", anchor="w", fg=MUTED_FG)
        self.status.pack(fill="x", padx=12, pady=4)

    # -- running ------------------------------------------------------------

    def _selected_notes(self) -> list[str]:
        return [self._note_paths[i] for i in self.note_list.curselection()]

    def _demonstrate(self) -> None:
        if self._running:
            return
        raw = self.topic_var.get().strip()
        if not raw:
            # The schema's "invalid topic id ''" is accurate and useless here:
            # an empty field is not a malformed id, it is a missing answer.
            messagebox.showerror(
                "Topic",
                "Choose a topic first -- pick one from your notes, or type a name using "
                "lowercase letters, digits and underscores (e.g. dc_basics).",
                parent=self,
            )
            return
        if self._review_topic:
            topic = self._review_topic
        else:
            try:
                topic = validate_new_topic(raw, self.flow.manifest)
            except SchemaError as exc:
                messagebox.showerror("Topic", str(exc), parent=self)
                return
        notes = self._selected_notes()
        if not notes:
            messagebox.showerror("Source notes", "Select at least one note.", parent=self)
            return

        self._running = True
        self._demo_button.configure(state="disabled")
        self._approve_button.configure(state="disabled")
        set_text(self.review, "Working...")
        threading.Thread(target=self._worker, args=(topic, notes), daemon=True).start()

    def _worker(self, topic: str, notes: list[str]) -> None:
        try:
            proposal = self.flow.demonstrate(
                topic, notes,
                on_stage=lambda s: self._events.put(("stage", s)),
                review=bool(self._review_topic),
            )
            self._events.put(("done", proposal))
        except UnlockError as exc:
            self._events.put(("error", str(exc)))
        except Exception as exc:  # noqa: BLE001
            self._events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "stage":
                    self.status.configure(text=f"working: {payload} ...")
                elif kind == "done":
                    self._show_proposal(payload)
                elif kind == "error":
                    self._running = False
                    self._demo_button.configure(state="normal")
                    self.status.configure(text="")
                    set_text(self.review, f"Demonstration failed.\n\n{payload}")
        except queue.Empty:
            pass
        self.after(POLL_MS, self._drain)

    def _show_proposal(self, proposal: UnlockProposal) -> None:
        self._running = False
        self._proposal = proposal
        self._demo_button.configure(state="normal")
        set_text(self.review, proposal.render())
        if proposal.blocked:
            self.status.configure(
                text="Blocked: the demonstration drew on another locked topic. Approval is not offered.",
                fg=DANGER_FG,
            )
            self._approve_button.configure(state="disabled")
        else:
            self.status.configure(
                text="Review the demonstration. Approving unlocks this topic permanently until you re-lock it.",
                fg=MUTED_FG,
            )
            self._approve_button.configure(state="normal")

    def _approve(self) -> None:
        if self._proposal is None or self._proposal.blocked:
            return
        try:
            manifest = (
                self.flow.confirm_review(self._proposal) if self._review_topic
                else self.flow.approve(self._proposal)
            )
        except UnlockError as exc:
            messagebox.showerror("Cannot approve", str(exc), parent=self)
            return
        self.result = manifest
        self.destroy()


class RelockDialog(ModalDialog):
    """Confirm re-locking, showing what will become invisible.

    The memory-note count is the one people do not anticipate: users remember
    writing their own notes but not what the model recorded three sessions ago.
    """

    def __init__(self, parent: tk.Misc, flow: UnlockFlow, topic: str) -> None:
        super().__init__(parent, f"Re-lock {topic}", width=560, height=340)
        self.flow = flow
        self.topic = topic

        impact = flow.relock_impact(topic)
        tk.Label(self, text=f"Re-lock {topic!r}?", font=(theme.font_family(), 11, "bold")).pack(
            anchor="w", padx=12, pady=(12, 6)
        )
        tk.Label(self, text=impact.describe(), justify="left", anchor="w").pack(
            anchor="w", padx=12, pady=4
        )
        tk.Label(
            self,
            text=(
                "The model will stop being able to draw on this topic, and every note carrying it "
                "becomes invisible to retrieval -- including memory notes written in past sessions. "
                "Nothing is deleted, and you can unlock it again later. The unlock stays in the "
                "manifest history either way."
            ),
            wraplength=520, justify="left", fg=MUTED_FG,
        ).pack(anchor="w", padx=12, pady=8)

        if impact.memory_notes:
            listbox = tk.Listbox(self, height=6)
            for rel in impact.memory_notes:
                listbox.insert("end", rel)
            listbox.pack(fill="both", expand=True, padx=12, pady=4)

        button_row(self, [("Re-lock", self._confirm), ("Cancel", self.on_cancel)]).pack(
            side="bottom", fill="x"
        )

    def _confirm(self) -> None:
        self.result = self.flow.relock(self.topic)
        self.destroy()


class TopicManagerDialog(ModalDialog):
    """View unlocked topics, inspect provenance, and re-lock."""

    def __init__(self, parent: tk.Misc, flow: UnlockFlow) -> None:
        super().__init__(parent, "Topic manager", width=760, height=560)
        self.flow = flow
        self.result = flow.manifest

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        left = tk.Frame(body)
        left.pack(side="left", fill="y")
        tk.Label(left, text="Unlocked topics", anchor="w").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=32, height=20, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._show_provenance())

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(right, text="Provenance", anchor="w").pack(anchor="w")
        self.detail = read_only_text(right, "", height=20)
        self.detail.pack(fill="both", expand=True)

        button_row(
            self,
            [("Close", self._close), ("Re-lock selected", self._relock), ("Unlock a topic...", self._unlock)],
        ).pack(side="bottom", fill="x")

        self._refresh()

    def _refresh(self) -> None:
        self.listbox.delete(0, "end")
        for topic in self.flow.manifest.unlocked_topics:
            self.listbox.insert("end", topic)
        set_text(self.detail, "" if self.flow.manifest.unlocked_topics else
                 "Nothing is unlocked yet.\n\nEverything starts locked -- ethics, literature and "
                 "mathematics exactly like geography. Write notes on a topic, then use "
                 "'Unlock a topic...' to teach it.")

    def _selected(self) -> str:
        selection = self.listbox.curselection()
        if not selection:
            return ""
        return self.listbox.get(selection[0])

    def _show_provenance(self) -> None:
        topic = self._selected()
        if not topic:
            return
        lines = [f"TOPIC: {topic}", ""]
        for event in self.flow.manifest.history:
            if event.topic != topic:
                continue
            lines.append(f"{event.at}  {event.action.upper()}")
            for source in event.source_notes:
                lines.append(f"    source: {source}")
            if event.note:
                lines.append(f"    note: {event.note}")
            lines.append("")
        impact = self.flow.relock_impact(topic)
        lines.append(impact.describe())
        set_text(self.detail, "\n".join(lines))

    def _unlock(self) -> None:
        manifest = UnlockDialog(self, self.flow).show()
        if manifest is not None:
            self.flow.manifest = manifest
            self._refresh()

    def _relock(self) -> None:
        topic = self._selected()
        if not topic:
            messagebox.showinfo("Re-lock", "Select a topic first.", parent=self)
            return
        manifest = RelockDialog(self, self.flow, topic).show()
        if manifest is not None:
            self.flow.manifest = manifest
            self._refresh()

    def _close(self) -> None:
        self.result = self.flow.manifest
        self.destroy()

    def on_cancel(self) -> None:
        self._close()
