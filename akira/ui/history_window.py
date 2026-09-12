"""Browsing and searching kept transcripts.

Read-only, and deliberately so. This window answers "what did I ask about
Thevenin last week", which was unanswerable before because transcripts were
always deleted after consolidation. Nothing here feeds the model: an archived
transcript contains drafts the gate blocked, and putting it back into context
would hand back exactly what was stopped.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from ..history import load_all, search, summarize
from ..schemas import Settings
from . import theme
from .widgets import MUTED_FG, ModalDialog, button_row, read_only_text, set_text


class HistoryWindow(ModalDialog):
    """Returns nothing. Reading, not editing."""

    def __init__(self, parent: tk.Misc, vault: Path, settings: Settings) -> None:
        super().__init__(parent, "Session history", width=940, height=680)
        self.vault = Path(vault)
        self.settings = settings
        self._all = load_all(self.vault)
        self._shown = list(self._all)

        top = tk.Frame(self)
        top.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(top, text="Search", anchor="w", width=8,
                 font=theme.ui_font()).pack(side="left")
        self.query = tk.Entry(top)
        self.query.pack(side="left", fill="x", expand=True)
        self.query.bind("<KeyRelease>", lambda _e: self._filter())
        self.query.focus_set()

        self.summary = tk.Label(self, text="", anchor="w", justify="left",
                                fg=MUTED_FG, wraplength=900, font=theme.ui_font())
        self.summary.pack(fill="x", padx=12, pady=(6, 4))

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=4)
        self.listbox = tk.Listbox(body, width=46, exportselection=False)
        self.listbox.pack(side="left", fill="y")
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._show())
        self.viewer = read_only_text(body, "", height=24)
        self.viewer.pack(side="left", fill="both", expand=True, padx=(12, 0))

        button_row(self, [("Close", self.on_cancel)]).pack(side="bottom", fill="x")
        self._filter()

    def _filter(self) -> None:
        self._shown = search(self._all, self.query.get())
        self.listbox.delete(0, "end")
        for transcript in self._shown:
            self.listbox.insert("end", transcript.label())
        self.summary.configure(
            text=summarize(len(self._all), len(self._shown),
                           enabled=self.settings.memory.keep_transcripts)
        )
        if self._shown:
            self.listbox.selection_set(0)
            self._show()
        else:
            set_text(self.viewer, "")

    def _show(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        transcript = self._shown[selection[0]]
        header = (
            f"{transcript.project}   ·   session {transcript.session}\n"
            f"{transcript.path.name}\n" + "-" * 70 + "\n\n"
        )
        set_text(self.viewer, header + transcript.body[:200_000])
