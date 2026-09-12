"""Turn a PDF or Word document into a set of unlockable topics.

The difference from `ImportDialog` is the unit of work. That one imports a file
as *one* note whose topics you type. This one reads the document's outline and
proposes *one note per section*, each with a topic id derived from its own
heading, so a lecture handout arrives as eight locked topics instead of one
undifferentiated blob you would have to split by hand.

Everything is a proposal until Import is pressed. Topic ids are editable,
sections can be dropped, and the prefix -- the part that decides where these
land in the knowledge web -- is one field at the top that renames all of them
at once.

Importing does not unlock anything, and the dialog says so where it cannot be
missed. These notes are tagged with locked topics and stay invisible to the
model until each is unlocked by demonstration, exactly like a note typed by
hand. Stocking the shelves is not the same as reading the books; a shortcut
that blurred the two would be a shortcut around the whole point of the program.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from ..documents import (
    DOCUMENT_SUFFIXES,
    DocumentError,
    Document,
    ProposedNote,
    extract,
    propose_notes,
    suggest_domain,
    write_notes,
)
from ..projects import get_project
from ..schemas import Manifest, SchemaError, utcnow_iso
from ..vault import coerce_topic
from . import theme
from .widgets import (
    MUTED_FG,
    ModalDialog,
    ScrollableFrame,
    button_row,
    read_only_text,
    set_text,
)


class DocumentImportDialog(ModalDialog):
    """Returns the list of written Paths, or None if cancelled."""

    def __init__(self, parent: tk.Misc, vault: Path, project: str,
                 manifest: Manifest) -> None:
        super().__init__(parent, "Import a document as knowledge", width=1020, height=740)
        self.vault = Path(vault)
        self.project = project
        self.manifest = manifest
        self.document: Document | None = None
        self.notes: list[ProposedNote] = []
        self._rows: list[dict] = []

        head = tk.Frame(self)
        head.pack(fill="x", padx=14, pady=(14, 4))
        tk.Button(head, text="Choose document...", command=self._choose).pack(side="left")
        self.file_label = tk.Label(
            head, text="PDF, Word (.docx), Markdown or plain text",
            fg=MUTED_FG, font=theme.ui_font(),
        )
        self.file_label.pack(side="left", padx=10)

        form = tk.Frame(self)
        form.pack(fill="x", padx=14, pady=4)
        tk.Label(form, text="Topic prefix", width=13, anchor="w",
                 font=theme.ui_font()).grid(row=0, column=0, sticky="w")
        self.domain_var = tk.StringVar()
        entry = tk.Entry(form, textvariable=self.domain_var, width=26)
        entry.grid(row=0, column=1, sticky="w")
        entry.bind("<KeyRelease>", lambda _e: self._repropose())
        tk.Label(form, text="groups these into one branch of the knowledge web",
                 fg=MUTED_FG, font=theme.ui_font(size=theme.UI_SIZE - 1)).grid(
                     row=0, column=2, sticky="w", padx=10)

        tk.Label(form, text="Save to", width=13, anchor="w",
                 font=theme.ui_font()).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.dest_var = tk.StringVar(value="global")
        dest = tk.Frame(form)
        dest.grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))
        tk.Radiobutton(dest, text="global notes", variable=self.dest_var,
                       value="global").pack(side="left")
        tk.Radiobutton(dest, text=f"this project ({project})", variable=self.dest_var,
                       value="project").pack(side="left")

        self.summary = tk.Label(self, text="", anchor="w", justify="left",
                                fg=MUTED_FG, font=theme.ui_font(), wraplength=960)
        self.summary.pack(fill="x", padx=14, pady=(10, 2))

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=14, pady=4)
        self.rows = ScrollableFrame(body)
        self.rows.pack(side="left", fill="both", expand=True)
        self.preview = read_only_text(body, "", height=16)
        self.preview.pack(side="left", fill="both", expand=True, padx=(12, 0))

        button_row(self, [("Import", self._import), ("Cancel", self.on_cancel)]).pack(
            side="bottom", fill="x"
        )
        self._placeholder("Choose a document to see what it would become.")

    # -- proposal -----------------------------------------------------------

    def _placeholder(self, message: str) -> None:
        for child in self.rows.inner.winfo_children():
            child.destroy()
        self._rows.clear()
        tk.Label(self.rows.inner, text=message, fg=MUTED_FG, wraplength=440,
                 justify="left", font=theme.ui_font()).pack(anchor="w", padx=6, pady=6)

    def _choose(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Choose a document", filetypes=DOCUMENT_SUFFIXES, parent=self
        )
        if not chosen:
            return
        try:
            document = extract(chosen)
        except DocumentError as exc:
            messagebox.showerror("Cannot read this document", str(exc), parent=self)
            return
        self.document = document
        self.file_label.configure(
            text=f"{document.source}   {document.word_count:,} words, "
                 f"{len(document.headings)} headings",
            fg=theme.FG,
        )
        self.domain_var.set(suggest_domain(document))
        self._repropose()

    def _repropose(self) -> None:
        """Re-derive every topic from the document.

        Rebuilt rather than string-substituted over the ids already on screen.
        Editing the prefix has to rename everything, and quietly rewriting an
        id the user had hand-corrected would be worse than restarting -- so it
        restarts, and the summary line says so before it happens.
        """
        if self.document is None:
            return
        self.notes = propose_notes(self.document, self.domain_var.get().strip())
        self._render_rows()

    def _render_rows(self) -> None:
        for child in self.rows.inner.winfo_children():
            child.destroy()
        self._rows.clear()

        if not self.notes:
            self._placeholder("No sections found to import from this document.")
            return

        for note in self.notes:
            row = tk.Frame(self.rows.inner)
            row.pack(fill="x", pady=1)

            included = tk.BooleanVar(value=note.include)
            tk.Checkbutton(row, variable=included,
                           command=self._update_summary).pack(side="left")

            topic_var = tk.StringVar(value=note.topic)
            topic_entry = tk.Entry(row, textvariable=topic_var, width=32,
                                   font=theme.font(size=theme.UI_SIZE - 1))
            topic_entry.pack(side="left")

            label = tk.Label(
                row, text=f"{note.heading[:32]}   {note.word_count:,}w",
                anchor="w", fg=MUTED_FG, font=theme.ui_font(size=theme.UI_SIZE - 1),
            )
            label.pack(side="left", padx=6)

            self._rows.append({"note": note, "include": included, "topic": topic_var})
            for widget in (row, label):
                widget.bind("<Button-1>", lambda _e, n=note: self._show(n), add="+")
            topic_entry.bind("<FocusIn>", lambda _e, n=note: self._show(n), add="+")

            if note.warnings:
                tk.Label(
                    self.rows.inner, text="      " + "; ".join(note.warnings),
                    anchor="w", fg=theme.WARNING_FG, wraplength=440, justify="left",
                    font=theme.ui_font(size=theme.UI_SIZE - 1),
                ).pack(fill="x")

        self.rows.scroll_to_top()
        self._show(self.notes[0])
        self._update_summary()

    def _show(self, note: ProposedNote) -> None:
        set_text(self.preview, f"{note.heading}\n\n{note.body[:20_000]}")

    def _update_summary(self) -> None:
        chosen = [r for r in self._rows if r["include"].get()]
        locked = self.manifest.all_locked(
            [t for t in (coerce_topic(r["topic"].get()) for r in chosen) if t]
        )
        self.summary.configure(
            text=f"{len(chosen)} of {len(self._rows)} sections selected -- "
                 f"{len(locked)} would arrive locked. Locked means stored now and "
                 "invisible to the model until you unlock each one by explaining it; "
                 "importing teaches it nothing by itself. Changing the prefix "
                 "re-derives every id below and discards edits to them."
        )

    # -- writing ------------------------------------------------------------

    def _import(self) -> None:
        if self.document is None:
            messagebox.showerror("Import", "Choose a document first.", parent=self)
            return
        for record in self._rows:
            record["note"].include = record["include"].get()
            record["note"].topic = record["topic"].get().strip()
        chosen = [r["note"] for r in self._rows if r["note"].include]
        if not chosen:
            messagebox.showerror("Import", "Select at least one section.", parent=self)
            return

        seen: set[str] = set()
        for note in chosen:
            key = coerce_topic(note.topic)
            if key is None:
                messagebox.showerror(
                    "Import",
                    f"'{note.topic}' is not a usable topic id. Letters, digits and "
                    "underscores, starting with a letter.",
                    parent=self,
                )
                return
            if key in seen:
                # Two notes on one topic is not a naming annoyance: unlocking
                # that topic would reveal both at once, which is not what
                # anyone reading the list would expect.
                messagebox.showerror(
                    "Import",
                    f"Two sections both want the topic '{key}'. Give one a different "
                    "id -- otherwise unlocking one would reveal both.",
                    parent=self,
                )
                return
            seen.add(key)

        if self.dest_var.get() == "project":
            directory = get_project(self.vault, self.project).notes_dir
        else:
            directory = self.vault / "global" / "notes"

        try:
            written = write_notes(directory, chosen, self.document, utcnow_iso())
        except (OSError, SchemaError, DocumentError) as exc:
            messagebox.showerror("Import failed", str(exc), parent=self)
            return

        self.result = written
        messagebox.showinfo(
            "Imported",
            f"{len(written)} note(s) written to {directory.name}.\n\n"
            "They are in the knowledge web now, locked. Open Knowledge to see them, "
            "then unlock one by explaining it in your own words.",
            parent=self,
        )
        self.destroy()
