"""Browse and install skills from the shipped library.

Installing copies the source into the project's `skills/` directory and stops
there. It does not approve anything: the digest-bound approval in the Skills
window is still required before the tool can run.

That separation is deliberate rather than bureaucratic. "It shipped with the
application" is precisely the reasoning that makes supply-chain trust invisible,
and the whole point of digest-bound approval is that trust attaches to content
somebody looked at -- not to provenance.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from ..skills.library import LIBRARY, LibrarySkill
from ..store import write_text
from . import theme
from .widgets import MUTED_FG, ModalDialog, button_row, read_only_text, set_text


class SkillLibraryDialog(ModalDialog):
    """Returns the list of installed filenames, or None."""

    def __init__(self, parent: tk.Misc, skills_dir: Path) -> None:
        super().__init__(parent, "Skill library", width=940, height=660)
        self.skills_dir = Path(skills_dir)
        self._installed: list[str] = []

        tk.Label(
            self,
            text="Ready-made tools, reviewed and shipped with Akira. Installing copies the "
                 "source into this project -- it does not approve it to run. Read it, then "
                 "approve it in the Skills window.",
            wraplength=theme.px(880), justify="left", fg=MUTED_FG,
        ).pack(anchor="w", padx=theme.px(14), pady=(theme.px(14), theme.px(10)))

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=theme.px(14))

        left = tk.Frame(body)
        left.pack(side="left", fill="y")
        self.listbox = tk.Listbox(left, width=34, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._preview())

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(theme.px(12), 0))
        self.summary = tk.Label(
            right, text="", anchor="w", justify="left", fg=theme.FG,
            font=theme.ui_font(bold=True), wraplength=theme.px(520),
        )
        self.summary.pack(fill="x")
        self.usage = tk.Label(
            right, text="", anchor="w", justify="left", fg=theme.PURPLE_BRIGHT,
            font=theme.font(size=theme.UI_SIZE - 1),
        )
        self.usage.pack(fill="x", pady=(theme.px(2), theme.px(6)))
        self.source = read_only_text(right, "", height=20)
        self.source.pack(fill="both", expand=True)

        self.status = tk.Label(self, text="", anchor="w", fg=MUTED_FG, padx=theme.px(14))
        self.status.pack(fill="x", pady=theme.px(4))

        button_row(self, [("Close", self._close), ("Install all", self._install_all),
                          ("Install", self._install)]).pack(side="bottom", fill="x")

        self._refresh()

    def _refresh(self) -> None:
        self.listbox.delete(0, "end")
        for skill in LIBRARY:
            present = (self.skills_dir / skill.filename).exists()
            self.listbox.insert("end", f"{'[installed] ' if present else ''}{skill.name}")
        if LIBRARY:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self._preview()

    def _selected(self) -> LibrarySkill | None:
        selection = self.listbox.curselection()
        return LIBRARY[selection[0]] if selection else None

    def _preview(self) -> None:
        skill = self._selected()
        if skill is None:
            return
        self.summary.configure(text=skill.summary)
        self.usage.configure(text=f"python {skill.usage}    ·    topic: {skill.topic}")
        set_text(self.source, skill.source)

    def _write(self, skill: LibrarySkill) -> bool:
        target = self.skills_dir / skill.filename
        if target.exists() and not messagebox.askokcancel(
            "Overwrite", f"{skill.filename} already exists. Replace it?", parent=self
        ):
            return False
        header = (
            f'"""{skill.summary}.\n\n'
            f"usage: python {skill.usage}\n\n"
            "Installed from the Akira skill library. NOT approved for execution --\n"
            "approval is granted per skill and is bound to this file's exact contents.\n"
            '"""\n\n'
        )
        try:
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            write_text(target, header + skill.source)
        except OSError as exc:
            messagebox.showerror("Install failed", str(exc), parent=self)
            return False
        self._installed.append(skill.filename)
        return True

    def _install(self) -> None:
        skill = self._selected()
        if skill is None:
            return
        if self._write(skill):
            self.status.configure(text=f"installed {skill.filename} (unapproved)")
            self._refresh()

    def _install_all(self) -> None:
        count = sum(1 for skill in LIBRARY if self._write(skill))
        self.status.configure(text=f"installed {count} skill(s) (all unapproved)")
        self._refresh()

    def _close(self) -> None:
        self.result = self._installed or None
        self.destroy()

    def on_cancel(self) -> None:
        self._close()
