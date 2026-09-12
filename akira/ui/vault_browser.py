"""The vault browser: read, edit, retag and delete notes and projects.

Everything in the vault is a plain markdown file, so all of this is possible
in any text editor. Having it in the app matters anyway: the frontmatter
`topics:` list is what governs whether the model can see a note, and editing
that by hand in another window -- getting the id spelling exactly right, with
no feedback about whether it matched -- is the single easiest way to end up
with a note you believe is visible and is not. Here, the effect of a tag is
stated as you type it.

Deletes are real and irreversible; each one names what is about to go.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from pathlib import Path
from tkinter import messagebox, simpledialog

from ..projects import (
    ProjectError,
    delete_project,
    ensure_project,
    list_projects,
    project_contents,
    rename_project,
    validate_name,
)
from ..schemas import Manifest, SchemaError
from ..store import write_text
from ..vault import coerce_topic, read_note, render_note, scan_vault
from . import theme
from .widgets import DANGER_FG, MUTED_FG, ModalDialog, button_row


class VaultBrowser(ModalDialog):
    """Returns True if anything on disk changed, else None."""

    def __init__(self, parent: tk.Misc, vault: Path, manifest: Manifest, project: str) -> None:
        super().__init__(parent, "Vault", width=1020, height=740)
        theme.apply_window_chrome(self)
        self.vault = Path(vault)
        self.manifest = manifest
        self.project = project
        self._changed = False
        self._current: Path | None = None

        tk.Label(
            self,
            text="Every note here is a plain markdown file. The topics line decides whether the "
                 "model can see it -- a note tagged with a locked topic stays invisible until you "
                 "unlock that topic.",
            wraplength=980, justify="left", fg=MUTED_FG,
        ).pack(anchor="w", padx=12, pady=(12, 8))

        self._build_projects_row()

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=12)

        left = tk.Frame(body)
        left.pack(side="left", fill="y")
        tk.Label(left, text="Notes", anchor="w").pack(anchor="w")
        scrollbar = ttk.Scrollbar(left, orient="vertical")
        self.listbox = tk.Listbox(left, width=46, exportselection=False, yscrollcommand=scrollbar.set)
        scrollbar.configure(command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._open_selected())

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        topics_row = tk.Frame(right)
        topics_row.pack(fill="x")
        tk.Label(topics_row, text="topics", width=8, anchor="w").pack(side="left")
        self.topics_entry = tk.Entry(topics_row)
        self.topics_entry.pack(side="left", fill="x", expand=True)
        self.topics_entry.bind("<KeyRelease>", lambda _e: self._update_visibility())

        self.visibility = tk.Label(right, text="", anchor="w", justify="left", fg=MUTED_FG,
                                   wraplength=560)
        self.visibility.pack(fill="x", pady=(2, 6))

        self.editor = tk.Text(right, wrap="word", padx=6, pady=6, width=1, height=1)
        self.editor.pack(fill="both", expand=True)

        self.status = tk.Label(self, text="", anchor="w", fg=MUTED_FG, padx=12)
        self.status.pack(fill="x", pady=4)

        button_row(
            self,
            [
                ("Close", self._close),
                ("Delete note", self._delete_note),
                ("Save note", self._save_note),
            ],
        ).pack(side="bottom", fill="x")

        self._refresh_notes()

    # -- projects ------------------------------------------------------------

    def _build_projects_row(self) -> None:
        row = tk.Frame(self)
        row.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(row, text="Project", anchor="w").pack(side="left")
        names = [p.name for p in list_projects(self.vault)] or [self.project]
        self.project_var = tk.StringVar(value=self.project)
        self.project_menu = tk.OptionMenu(row, self.project_var, *names,
                                          command=lambda _v: self._refresh_notes())
        self.project_menu.pack(side="left", padx=6)
        tk.Button(row, text="New", command=self._new_project).pack(side="left", padx=2)
        tk.Button(row, text="Rename", command=self._rename_project).pack(side="left", padx=2)
        tk.Button(row, text="Delete project", command=self._delete_project).pack(side="left", padx=2)

    def _refresh_project_menu(self) -> None:
        menu = self.project_menu["menu"]
        menu.delete(0, "end")
        for project in list_projects(self.vault):
            menu.add_command(
                label=project.name,
                command=lambda n=project.name: (self.project_var.set(n), self._refresh_notes()),
            )

    def _new_project(self) -> None:
        name = simpledialog.askstring("New project", "Project name:", parent=self)
        if not name:
            return
        try:
            ensure_project(self.vault, validate_name(name))
        except (SchemaError, ProjectError) as exc:
            messagebox.showerror("Project", str(exc), parent=self)
            return
        self._changed = True
        self.project_var.set(name.strip())
        self._refresh_project_menu()
        self._refresh_notes()

    def _rename_project(self) -> None:
        old = self.project_var.get()
        new = simpledialog.askstring("Rename project", f"New name for {old!r}:", parent=self)
        if not new or new.strip() == old:
            return
        try:
            renamed = rename_project(self.vault, old, new.strip())
        except (SchemaError, ProjectError) as exc:
            messagebox.showerror("Rename failed", str(exc), parent=self)
            return
        self._changed = True
        self.project_var.set(renamed.name)
        if self.project == old:
            self.project = renamed.name
        self._refresh_project_menu()
        self._refresh_notes()
        self.status.configure(text=f"renamed to {renamed.name!r}", fg=MUTED_FG)

    def _delete_project(self) -> None:
        name = self.project_var.get()
        from ..projects import get_project

        contents = project_contents(get_project(self.vault, name))
        if not messagebox.askokcancel(
            "Delete project",
            f"Delete project {name!r} and everything in it?\n\n{contents.describe()}\n\n"
            "This cannot be undone.",
            parent=self,
        ):
            return
        try:
            delete_project(self.vault, name)
        except ProjectError as exc:
            messagebox.showerror("Cannot delete", str(exc), parent=self)
            return
        self._changed = True
        remaining = [p.name for p in list_projects(self.vault)]
        self.project_var.set(remaining[0] if remaining else "default")
        self._refresh_project_menu()
        self._refresh_notes()
        self.status.configure(text=f"deleted project {name!r}", fg=DANGER_FG)

    # -- notes ---------------------------------------------------------------

    def _refresh_notes(self) -> None:
        self.listbox.delete(0, "end")
        scan = scan_vault(self.vault)
        selected = self.project_var.get()
        self._paths: list[Path] = []
        for note in scan.notes:
            # Other projects' notes are not visible from here, mirroring the
            # isolation retrieval enforces.
            if note.project and note.project != selected:
                continue
            self._paths.append(note.path)
            if note.error:
                mark = "!"
            elif not note.topics:
                mark = "-"
            elif self.manifest.all_locked(note.topics):
                mark = "L"
            else:
                mark = "*"
            self.listbox.insert("end", f"[{mark}] {note.rel_path}")
        self.status.configure(
            text=f"{len(self._paths)} note(s)   * visible   L locked   - untagged   ! unreadable",
            fg=MUTED_FG,
        )
        self._current = None
        self.editor.delete("1.0", "end")
        self.topics_entry.delete(0, "end")
        self._update_visibility()

    def _open_selected(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        path = self._paths[selection[0]]
        note = read_note(path, self.vault)
        self._current = path
        self.topics_entry.delete(0, "end")
        self.topics_entry.insert(0, ", ".join(note.topics))
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", note.body if note.ok else f"(unreadable: {note.error})")
        self._update_visibility()

    def _parse_topics(self) -> tuple[list[str], list[str]]:
        good: list[str] = []
        bad: list[str] = []
        for raw in self.topics_entry.get().split(","):
            raw = raw.strip()
            if not raw:
                continue
            coerced = coerce_topic(raw)
            if coerced is None:
                bad.append(raw)
            elif coerced not in good:
                good.append(coerced)
        return good, bad

    def _update_visibility(self) -> None:
        topics, bad = self._parse_topics()
        if bad:
            self.visibility.configure(text=f"unusable topic(s): {', '.join(bad)}", fg=DANGER_FG)
            return
        if not topics:
            self.visibility.configure(
                text="No topics: invisible to the model until you tag it.", fg=MUTED_FG
            )
            return
        locked = self.manifest.all_locked(topics)
        if locked:
            self.visibility.configure(
                text=f"Locked: {', '.join(locked)} -- invisible to the model until unlocked.",
                fg=MUTED_FG,
            )
        else:
            self.visibility.configure(
                text="All topics unlocked: visible to retrieval.", fg=theme.PURPLE_BRIGHT
            )

    def _save_note(self) -> None:
        if self._current is None:
            messagebox.showinfo("Vault", "Select a note first.", parent=self)
            return
        topics, bad = self._parse_topics()
        if bad:
            messagebox.showerror("Topics", f"Fix the unusable topic(s): {', '.join(bad)}", parent=self)
            return
        note = read_note(self._current, self.vault)
        # Preserve frontmatter Akira wrote (kind, session, provenance) rather
        # than flattening it to just the topics list.
        extra = {k: v for k, v in note.frontmatter.items() if k not in ("topics", "topic", "tags", "tag")}
        try:
            write_text(
                self._current,
                render_note(topics, self.editor.get("1.0", "end-1c"), extra=extra or None),
            )
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return
        self._changed = True
        self.status.configure(text=f"saved {self._current.name}", fg=MUTED_FG)
        self._remember_and_refresh()

    def _delete_note(self) -> None:
        if self._current is None:
            messagebox.showinfo("Vault", "Select a note first.", parent=self)
            return
        rel = self._current.relative_to(self.vault).as_posix()
        if not messagebox.askokcancel(
            "Delete note", f"Permanently delete {rel}?\n\nThis cannot be undone.", parent=self
        ):
            return
        try:
            self._current.unlink()
        except OSError as exc:
            messagebox.showerror("Delete failed", str(exc), parent=self)
            return
        self._changed = True
        self.status.configure(text=f"deleted {rel}", fg=DANGER_FG)
        self._current = None
        self._refresh_notes()

    def _remember_and_refresh(self) -> None:
        """Refresh the list without losing the user's place in it."""
        index = self.listbox.curselection()
        self._refresh_notes()
        if index and index[0] < self.listbox.size():
            self.listbox.selection_set(index[0])
            self._open_selected()

    def _close(self) -> None:
        self.result = True if self._changed else None
        self.destroy()

    def on_cancel(self) -> None:
        self._close()
