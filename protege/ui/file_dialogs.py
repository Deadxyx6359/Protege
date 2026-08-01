"""File attach and import.

Two distinct operations with two distinct lifetimes, kept visually separate so
neither masquerades as the other:

* **Attach** puts a file's text into the current conversation's context. It
  lives for this session only, is injected at its own budget priority, and is
  never written to the vault.
* **Import** copies a file into the vault as a topic-tagged markdown note. It
  is permanent, and from that moment it behaves exactly like a note the user
  wrote by hand -- including the visibility rules: tagged with a locked topic,
  it stays invisible to the model until that topic is unlocked.

Neither operation passes the lock gate, deliberately. The gate exists for
*model* output; these files are user-supplied content, and running the user's
own documents through tripwires would mean the pattern list censoring what the
user may tell their own assistant. The directive's "notes provided in context"
clause covers attachments; import visibility is governed by topic tags like any
other note. MAIN's *responses about* either still pass Layers 4-5 unchanged.

Text files only. A binary file pasted into a prompt is garbage tokens at best,
and at worst a parser surprise -- so anything with NUL bytes or that will not
decode as UTF-8 (BOM tolerated) is refused with a plain explanation.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from ..projects import get_project, slugify
from ..schemas import Manifest, SchemaError, utcnow_iso
from ..store import write_text
from ..vault import coerce_topic, render_note
from . import theme
from .widgets import MUTED_FG, ModalDialog, button_row, read_only_text, set_text

MAX_ATTACH_BYTES = 2_000_000
TEXT_SUFFIXES = (
    ("Text and code", "*.txt *.md *.markdown *.py *.json *.yaml *.yml *.csv *.log *.toml *.ini *.html *.css *.js *.xml"),
    ("All files", "*.*"),
)


class FileReadError(ValueError):
    """The file cannot be used as text, with a reason the user can act on."""


def read_text_file(path: str | Path) -> tuple[str, str]:
    """Read a file as UTF-8 text. Returns (name, content) or raises FileReadError."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise FileReadError(f"cannot read {path.name}: {exc}") from exc
    if size > MAX_ATTACH_BYTES:
        raise FileReadError(
            f"{path.name} is {size / 1_000_000:.1f} MB, over the {MAX_ATTACH_BYTES // 1_000_000} MB "
            "limit. A file that size would not fit any context budget anyway -- consider importing "
            "an excerpt instead."
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FileReadError(f"cannot read {path.name}: {exc}") from exc
    if b"\x00" in raw[:8192]:
        raise FileReadError(
            f"{path.name} looks like a binary file. Only text files can be attached or imported."
        )
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            # Windows-authored text is often cp1252. Better to accept it than
            # to make the user re-save their own notes in a different editor.
            content = raw.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise FileReadError(
                f"{path.name} is not UTF-8 or Windows-1252 text: {exc}"
            ) from exc
    if not content.strip():
        raise FileReadError(f"{path.name} is empty.")
    return path.name, content


def pick_text_file(parent: tk.Misc) -> tuple[str, str] | None:
    """File chooser + validation. Returns (name, content) or None on cancel."""
    chosen = filedialog.askopenfilename(title="Choose a text file", filetypes=TEXT_SUFFIXES, parent=parent)
    if not chosen:
        return None
    try:
        return read_text_file(chosen)
    except FileReadError as exc:
        messagebox.showerror("Cannot use this file", str(exc), parent=parent)
        return None


class AttachmentsDialog(ModalDialog):
    """View and remove this session's attachments. Returns the updated list."""

    def __init__(self, parent: tk.Misc, attachments: list[tuple[str, str]]) -> None:
        super().__init__(parent, "Attached files", width=640, height=460)
        self.attachments = list(attachments)

        tk.Label(
            self,
            text="Attached to this conversation only -- cleared when the session ends, never "
                 "written to the vault.",
            wraplength=600, justify="left", fg=MUTED_FG,
        ).pack(anchor="w", padx=12, pady=(12, 8))

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=12)
        self.listbox = tk.Listbox(body, width=34, exportselection=False)
        self.listbox.pack(side="left", fill="y")
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._preview())
        self.viewer = read_only_text(body, "", height=16)
        self.viewer.pack(side="left", fill="both", expand=True, padx=(10, 0))

        button_row(self, [("Close", self._close), ("Remove selected", self._remove)]).pack(
            side="bottom", fill="x"
        )
        self._refresh()

    def _refresh(self) -> None:
        self.listbox.delete(0, "end")
        for name, content in self.attachments:
            self.listbox.insert("end", f"{name}  ({len(content):,} chars)")
        if not self.attachments:
            set_text(self.viewer, "Nothing attached. Use the Attach button next to Send.")

    def _preview(self) -> None:
        selection = self.listbox.curselection()
        if selection:
            set_text(self.viewer, self.attachments[selection[0]][1][:20_000])

    def _remove(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        del self.attachments[selection[0]]
        self._refresh()

    def _close(self) -> None:
        self.result = self.attachments
        self.destroy()

    def on_cancel(self) -> None:
        self._close()


class ImportDialog(ModalDialog):
    """Import a text file into the vault as a topic-tagged note.

    Returns the written Path, or None. The topic entry is validated with the
    same coercion notes use, and the visibility consequence is stated in the
    dialog rather than discovered later: tags with locked topics mean the note
    is invisible to the model until those topics are unlocked. That is not an
    error -- importing reference material ahead of teaching it is exactly how
    the unlock flow expects source notes to arrive.
    """

    def __init__(self, parent: tk.Misc, vault: Path, project: str, manifest: Manifest) -> None:
        super().__init__(parent, "Import into vault", width=680, height=560)
        self.vault = Path(vault)
        self.project = project
        self.manifest = manifest
        self._file: tuple[str, str] | None = None

        picker = tk.Frame(self)
        picker.pack(fill="x", padx=12, pady=(12, 4))
        tk.Button(picker, text="Choose file...", command=self._choose).pack(side="left")
        self.file_label = tk.Label(picker, text="no file chosen", fg=MUTED_FG)
        self.file_label.pack(side="left", padx=8)

        form = tk.Frame(self)
        form.pack(fill="x", padx=12, pady=4)
        tk.Label(form, text="Topics (comma-separated)", width=24, anchor="w").grid(row=0, column=0, sticky="w")
        self.topics_entry = tk.Entry(form)
        self.topics_entry.grid(row=0, column=1, sticky="we", pady=2)
        tk.Label(form, text="Destination", width=24, anchor="w").grid(row=1, column=0, sticky="w")
        self.dest_var = tk.StringVar(value="project")
        dest_row = tk.Frame(form)
        dest_row.grid(row=1, column=1, sticky="w")
        tk.Radiobutton(dest_row, text=f"this project ({project})", variable=self.dest_var, value="project").pack(side="left")
        tk.Radiobutton(dest_row, text="global notes", variable=self.dest_var, value="global").pack(side="left")
        form.columnconfigure(1, weight=1)

        self.visibility = tk.Label(self, text="", wraplength=640, justify="left", fg=MUTED_FG)
        self.visibility.pack(anchor="w", padx=12, pady=4)
        self.topics_entry.bind("<KeyRelease>", lambda _e: self._update_visibility())

        tk.Label(self, text="Preview", anchor="w").pack(anchor="w", padx=12)
        self.preview = read_only_text(self, "", height=12)
        self.preview.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        button_row(self, [("Import", self._import), ("Cancel", self.on_cancel)]).pack(side="bottom", fill="x")

    def _choose(self) -> None:
        picked = pick_text_file(self)
        if picked is None:
            return
        self._file = picked
        self.file_label.configure(text=f"{picked[0]}  ({len(picked[1]):,} chars)", fg=theme.FG)
        set_text(self.preview, picked[1][:20_000])

    def _topics(self) -> tuple[list[str], list[str]]:
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
        topics, bad = self._topics()
        if bad:
            self.visibility.configure(text=f"unusable topic(s): {', '.join(bad)}", fg=theme.DANGER)
            return
        if not topics:
            self.visibility.configure(
                text="No topics: the note will exist in the vault but stay invisible to the model "
                     "until you tag it.",
                fg=MUTED_FG,
            )
            return
        locked = self.manifest.all_locked(topics)
        if locked:
            self.visibility.configure(
                text=f"Locked topic(s): {', '.join(locked)}. The note is stored now and becomes "
                     "visible to the model when you unlock them -- importing ahead of teaching is "
                     "how unlock source notes usually arrive.",
                fg=MUTED_FG,
            )
        else:
            self.visibility.configure(
                text="All topics unlocked: the note is immediately visible to retrieval.",
                fg=MUTED_FG,
            )

    def _import(self) -> None:
        if self._file is None:
            messagebox.showerror("Import", "Choose a file first.", parent=self)
            return
        topics, bad = self._topics()
        if bad:
            messagebox.showerror("Import", f"Fix the unusable topic(s): {', '.join(bad)}", parent=self)
            return

        name, content = self._file
        stem = slugify(Path(name).stem, fallback="imported")
        if self.dest_var.get() == "project":
            directory = get_project(self.vault, self.project).notes_dir
        else:
            directory = self.vault / "global" / "notes"
        directory.mkdir(parents=True, exist_ok=True)

        target = directory / f"{stem}.md"
        counter = 2
        while target.exists():
            target = directory / f"{stem}-{counter}.md"
            counter += 1

        try:
            write_text(
                target,
                render_note(
                    topics,
                    content,
                    extra={"kind": "imported", "source_file": name, "imported_at": utcnow_iso()},
                ),
            )
        except (OSError, SchemaError) as exc:
            messagebox.showerror("Import failed", str(exc), parent=self)
            return
        self.result = target
        self.destroy()
