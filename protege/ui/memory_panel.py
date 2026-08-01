"""The memory panel.

Shows what has been written this session, lets the user edit or discard entries
before consolidation, and pins new ones by hand. Also lists writes the lock
system refused, because a silently-dropped memory write looks identical to a
model that simply did not notice anything worth keeping.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from ..memory.live import SOURCE_PINNED, LiveMemory
from . import theme
from .widgets import DANGER_FG, MUTED_FG, ModalDialog, button_row, read_only_text, set_text


class MemoryPanel(ModalDialog):
    def __init__(self, parent: tk.Misc, memory: LiveMemory, unlocked_topics: tuple[str, ...]) -> None:
        super().__init__(parent, "Session memory", width=800, height=600)
        self.memory = memory
        self.unlocked_topics = unlocked_topics

        tk.Label(
            self,
            text=(
                "Written this session. Nothing here is permanent until the session ends and you "
                "confirm the consolidation."
            ),
            wraplength=760, justify="left", fg=MUTED_FG,
        ).pack(anchor="w", padx=12, pady=(12, 8))

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=12)

        left = tk.Frame(body)
        left.pack(side="left", fill="y")
        self.listbox = tk.Listbox(left, width=44, height=18, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._show_selected())

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.editor = tk.Text(right, wrap="word", height=12, padx=6, pady=6)
        self.editor.pack(fill="both", expand=True)
        tk.Label(
            right,
            text="Edits here are your own text and are saved as-is -- the lock system checks model "
                 "output, not your notes.",
            wraplength=380, justify="left", fg=MUTED_FG,
        ).pack(anchor="w", pady=4)

        self._build_pin_row()

        self.status = tk.Label(self, text="", anchor="w", fg=MUTED_FG)
        self.status.pack(fill="x", padx=12, pady=(4, 0))

        self.blocked_view = read_only_text(self, "", height=5)
        self.blocked_view.pack(fill="x", padx=12, pady=4)

        button_row(
            self,
            [("Close", self._close), ("Discard entry", self._discard), ("Save edit", self._save_edit)],
        ).pack(side="bottom", fill="x")

        self._refresh()

    def _build_pin_row(self) -> None:
        row = tk.Frame(self)
        row.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(row, text="Pin a note", width=10, anchor="w").pack(side="left")
        self.pin_entry = tk.Entry(row)
        self.pin_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.pin_topic = tk.StringVar(value=self.unlocked_topics[0] if self.unlocked_topics else "")
        if self.unlocked_topics:
            tk.OptionMenu(row, self.pin_topic, *self.unlocked_topics).pack(side="left")
        tk.Button(row, text="Pin", width=8, command=self._pin).pack(side="left", padx=4)

    # -- data ---------------------------------------------------------------

    def _refresh(self) -> None:
        self.listbox.delete(0, "end")
        for entry in self.memory.entries:
            topics = ",".join(entry.topics) or "untagged"
            preview = entry.content.replace("\n", " ")[:38]
            self.listbox.insert("end", f"[{entry.source[:3]}·{entry.importance}] {topics}: {preview}")
        self.status.configure(text=self.memory.summary())

        if self.memory.rejected:
            lines = ["Writes the lock system refused this session:"]
            for rejection in self.memory.rejected:
                lines.append(f"  - {rejection.reason}")
            set_text(self.blocked_view, "\n".join(lines))
            self.blocked_view.configure(height=min(8, len(lines) + 1))
        else:
            set_text(self.blocked_view, "No memory writes were blocked this session.")

    def _selected_index(self) -> int:
        selection = self.listbox.curselection()
        return selection[0] if selection else -1

    def _show_selected(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.memory.entries[index].content)

    # -- actions ------------------------------------------------------------

    def _pin(self) -> None:
        content = self.pin_entry.get().strip()
        if not content:
            return
        topic = self.pin_topic.get().strip()
        result = self.memory.write(
            content, topics=[topic] if topic else [], source=SOURCE_PINNED, importance=4
        )
        if not result.accepted:
            messagebox.showerror("Not written", result.reason, parent=self)
        else:
            self.pin_entry.delete(0, "end")
        self._refresh()

    def _save_edit(self) -> None:
        index = self._selected_index()
        if index < 0:
            messagebox.showinfo("Memory", "Select an entry first.", parent=self)
            return
        self.memory.replace(index, self.editor.get("1.0", "end-1c"))
        self._refresh()

    def _discard(self) -> None:
        index = self._selected_index()
        if index < 0:
            messagebox.showinfo("Memory", "Select an entry first.", parent=self)
            return
        if not messagebox.askokcancel("Discard", "Discard this memory entry?", parent=self):
            return
        self.memory.remove(index)
        self.editor.delete("1.0", "end")
        self._refresh()

    def _close(self) -> None:
        self.result = True
        self.destroy()

    def on_cancel(self) -> None:
        self._close()


class ConsolidationReviewDialog(ModalDialog):
    """Diff-style review of the session's consolidation.

    Confirming commits the notes and deletes the transcript, which is
    irreversible -- so the dialog says so in those words, next to the button
    that does it, rather than in a tooltip.
    """

    def __init__(self, parent: tk.Misc, consolidator, result) -> None:
        super().__init__(parent, "Review session notes", width=880, height=660)
        self.consolidator = consolidator
        self.consolidation = result
        self._accepted: dict[str, tk.BooleanVar] = {}

        tk.Label(
            self,
            text=result.summary(),
            font=(theme.font_family(), 10, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 4))

        tk.Label(
            self,
            text=(
                "These notes were written by the model from this session's memory. Consolidation is "
                "done by an 8B model and is sometimes lossy or wrong, which is why the transcript is "
                "kept until you confirm."
            ),
            wraplength=840, justify="left", fg=MUTED_FG,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=12)

        left = tk.Frame(body)
        left.pack(side="left", fill="y")
        self.listbox = tk.Listbox(left, width=36, height=18, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._show_selected())

        self.diff_view = read_only_text(body, "", height=18)
        self.diff_view.pack(side="left", fill="both", expand=True, padx=(12, 0))

        toggles = tk.Frame(self)
        toggles.pack(fill="x", padx=12, pady=6)
        self.keep_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            toggles,
            text="Keep the selected note when confirming",
            variable=self.keep_var,
            command=self._toggle_keep,
        ).pack(side="left")

        warning = tk.Label(
            self,
            text="Confirming deletes this session's transcript. That cannot be undone.",
            fg=DANGER_FG, anchor="w",
        )
        warning.pack(fill="x", padx=12)

        button_row(
            self,
            [("Confirm", self._confirm), ("Discard notes", self._discard), ("Decide later", self.on_cancel)],
        ).pack(side="bottom", fill="x")

        for note in result.usable:
            self._accepted[note.filename] = tk.BooleanVar(value=True)
        self._refresh()

    def _refresh(self) -> None:
        self.listbox.delete(0, "end")
        for note in self.consolidation.usable:
            mark = "x" if self._accepted[note.filename].get() else " "
            self.listbox.insert("end", f"[{mark}] {note.topic}: {note.title[:26]}")
        for note in self.consolidation.blocked:
            self.listbox.insert("end", f"[BLOCKED] {note.topic}")

    def _selected_note(self):
        selection = self.listbox.curselection()
        if not selection:
            return None
        index = selection[0]
        usable = self.consolidation.usable
        if index < len(usable):
            return usable[index]
        return self.consolidation.blocked[index - len(usable)]

    def _show_selected(self) -> None:
        note = self._selected_note()
        if note is None:
            return
        if note.blocked:
            set_text(self.diff_view, f"BLOCKED\n\n{note.block_reason}\n\nThis note will not be saved.")
            return
        existing = ""
        if note.merges_into:
            path = self.consolidator.vault / note.merges_into
            if path.is_file():
                existing = path.read_text(encoding="utf-8")
        set_text(self.diff_view, note.diff_against(existing))
        self.keep_var.set(self._accepted[note.filename].get())

    def _toggle_keep(self) -> None:
        note = self._selected_note()
        if note is None or note.blocked:
            return
        self._accepted[note.filename].set(self.keep_var.get())
        self._refresh()

    def _confirm(self) -> None:
        accept = [name for name, var in self._accepted.items() if var.get()]
        if not messagebox.askokcancel(
            "Confirm",
            f"Commit {len(accept)} note(s) and permanently delete this session's transcript?",
            parent=self,
        ):
            return
        self.result = self.consolidator.confirm(self.consolidation, accept=accept)
        self.destroy()

    def _discard(self) -> None:
        if not messagebox.askokcancel(
            "Discard",
            "Throw away these notes? The transcript is kept so you can try again.",
            parent=self,
        ):
            return
        self.consolidator.discard(self.consolidation, keep_transcript=True)
        self.result = []
        self.destroy()
