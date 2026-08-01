"""PIN entry and PIN setup.

Shown before the main window, over a full character-rain backdrop -- the one
place the rain gets the whole screen, because there is no text here competing
with it beyond a short form floating on a solid panel.

The honest framing appears in the dialog itself rather than only in the README:
someone reading this screen should understand that they are being asked for an
access convenience, not a decryption key.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from ..security.pin import AttemptTracker, PinError, hash_pin, strength_note, validate_pin, verify_pin
from . import theme
from .rain import RainCanvas
from .widgets import MUTED_FG, ModalDialog, button_row

DISCLAIMER = (
    "The PIN keeps someone from opening Protege on an unlocked machine. It is not "
    "encryption -- your vault is plain markdown on disk and anyone with access to the "
    "drive can read it regardless. Use full-disk encryption for that."
)


class _RainDialog(ModalDialog):
    """A modal whose entire surface is rain, with content floating on a panel.

    Subclasses build into `self.panel`. The panel is solid background with a
    thin purple border, so the form reads as a window over the rain rather than
    text drowning in it. The rain stops with the dialog -- ModalDialog's
    on_cancel destroys us, and RainCanvas cancels its own tick on <Destroy>.
    """

    def __init__(self, parent: tk.Misc, title: str, *, width: int, height: int) -> None:
        # transient=False: these open over a withdrawn root at launch, and a
        # transient of a withdrawn master never maps on Windows.
        super().__init__(parent, title, width=width, height=height, transient=False)
        self.rain = RainCanvas(self, density=0.7)
        self.rain.pack(fill="both", expand=True)
        self.rain.start()

        self.panel = tk.Frame(
            self,
            bg=theme.BG,
            highlightbackground=theme.PURPLE_DIM,
            highlightcolor=theme.PURPLE_DIM,
            highlightthickness=1,
            padx=14,
            pady=10,
        )
        # A canvas window item keeps the panel centered as the dialog resizes.
        self.rain.create_window(width // 2, height // 2, window=self.panel, anchor="center")
        self.rain.bind(
            "<Configure>",
            self._recenter,
            add="+",  # RainCanvas already binds <Configure> for its columns
        )

    def _recenter(self, event: tk.Event) -> None:
        # There is exactly one window item on the canvas.
        for item in self.rain.find_withtag("all"):
            if self.rain.type(item) == "window":
                self.rain.coords(item, event.width // 2, event.height // 2)


class PinSetupDialog(_RainDialog):
    """First-run PIN creation. Returns the argon2id hash, or None if cancelled."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, "Set a PIN", width=640, height=460)

        tk.Label(
            self.panel, text="P R O T E G E", font=(theme.font_family(), 14, "bold"),
            fg=theme.PURPLE_BRIGHT,
        ).pack(anchor="w", pady=(2, 8))
        tk.Label(
            self.panel, text="Choose a PIN", font=(theme.font_family(), 11, "bold")
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(self.panel, text=DISCLAIMER, wraplength=420, justify="left", fg=MUTED_FG).pack(
            anchor="w", pady=(0, 10)
        )

        form = tk.Frame(self.panel)
        form.pack(fill="x")
        tk.Label(form, text="PIN", width=12, anchor="w").grid(row=0, column=0, sticky="w", pady=3)
        self.first = tk.Entry(form, show="*", width=28)
        self.first.grid(row=0, column=1, sticky="we", pady=3)
        tk.Label(form, text="Confirm", width=12, anchor="w").grid(row=1, column=0, sticky="w", pady=3)
        self.second = tk.Entry(form, show="*", width=28)
        self.second.grid(row=1, column=1, sticky="we", pady=3)
        form.columnconfigure(1, weight=1)

        self.hint = tk.Label(self.panel, text="", wraplength=420, justify="left", fg=MUTED_FG)
        self.hint.pack(anchor="w", pady=8)
        self.first.bind("<KeyRelease>", lambda _e: self._update_hint())
        self.second.bind("<Return>", lambda _e: self._save())

        button_row(self.panel, [("Set PIN", self._save), ("Cancel", self.on_cancel)]).pack(fill="x")
        self.initial_focus = self.first

    def _update_hint(self) -> None:
        self.hint.configure(text=strength_note(self.first.get()))

    def _save(self) -> None:
        first, second = self.first.get(), self.second.get()
        if first != second:
            messagebox.showerror("PIN mismatch", "The two entries do not match.", parent=self)
            return
        try:
            validate_pin(first)
        except PinError as exc:
            messagebox.showerror("PIN rejected", str(exc), parent=self)
            return
        self.result = hash_pin(first)
        self.destroy()


class PinPromptDialog(_RainDialog):
    """PIN entry at launch. Returns True on success, None on cancel."""

    def __init__(self, parent: tk.Misc, encoded_hash: str, *, tracker: AttemptTracker | None = None,
                 prompt: str = "Enter your PIN") -> None:
        super().__init__(parent, "Protege", width=560, height=380)
        self._hash = encoded_hash
        self._tracker = tracker or AttemptTracker()

        tk.Label(
            self.panel, text="P R O T E G E", font=(theme.font_family(), 14, "bold"),
            fg=theme.PURPLE_BRIGHT,
        ).pack(anchor="w", pady=(2, 10))
        tk.Label(self.panel, text=prompt, font=(theme.font_family(), 11)).pack(anchor="w", pady=(0, 8))
        self.entry = tk.Entry(self.panel, show="*", width=26)
        self.entry.pack(anchor="w")
        self.entry.bind("<Return>", lambda _e: self._check())

        self.status = tk.Label(self.panel, text="", fg=MUTED_FG, wraplength=380, justify="left")
        self.status.pack(anchor="w", pady=8)

        button_row(self.panel, [("Unlock", self._check), ("Quit", self.on_cancel)]).pack(fill="x")
        self.initial_focus = self.entry

    def _check(self) -> None:
        if self._tracker.locked_out:
            self.status.configure(text=f"Too many attempts. Wait {self._tracker.wait_remaining:.0f}s.")
            return
        if verify_pin(self._hash, self.entry.get()):
            self._tracker.record_success()
            self.result = True
            self.destroy()
            return
        delay = self._tracker.record_failure()
        self.entry.delete(0, "end")
        message = "Incorrect PIN."
        if delay:
            message += f" Wait {delay:.0f}s before trying again."
        self.status.configure(text=message, fg=theme.DANGER)


class PinChangeDialog(ModalDialog):
    """Change the PIN. Requires the current one. Returns the new hash.

    No rain here: this opens from inside Settings, where a full animated
    backdrop behind a three-field form would be noise, not signature.
    """

    def __init__(self, parent: tk.Misc, encoded_hash: str) -> None:
        super().__init__(parent, "Change PIN", width=460, height=280)
        self._hash = encoded_hash

        tk.Label(self, text="Change your PIN", font=(theme.font_family(), 11, "bold")).pack(
            anchor="w", padx=12, pady=(12, 8)
        )
        form = tk.Frame(self)
        form.pack(fill="x", padx=12)
        labels = ("Current", "New", "Confirm new")
        self.entries: list[tk.Entry] = []
        for row, label in enumerate(labels):
            tk.Label(form, text=label, width=14, anchor="w").grid(row=row, column=0, sticky="w", pady=3)
            entry = tk.Entry(form, show="*", width=30)
            entry.grid(row=row, column=1, sticky="we", pady=3)
            self.entries.append(entry)
        form.columnconfigure(1, weight=1)

        button_row(self, [("Change", self._save), ("Cancel", self.on_cancel)]).pack(side="bottom", fill="x")
        self.initial_focus = self.entries[0]

    def _save(self) -> None:
        current, new, confirm = (e.get() for e in self.entries)
        if not verify_pin(self._hash, current):
            messagebox.showerror("Wrong PIN", "The current PIN is incorrect.", parent=self)
            return
        if new != confirm:
            messagebox.showerror("PIN mismatch", "The two new entries do not match.", parent=self)
            return
        try:
            validate_pin(new)
        except PinError as exc:
            messagebox.showerror("PIN rejected", str(exc), parent=self)
            return
        self.result = hash_pin(new)
        self.destroy()


def confirm_pin(parent: tk.Misc, encoded_hash: str, reason: str) -> bool:
    """Re-prompt for the PIN before a consequential change.

    Used for trust-tier changes, which is the one setting that can hand the
    model filesystem access. Returns True only on a correct PIN; an unset PIN
    returns True, because there is nothing to confirm against.
    """
    if not encoded_hash:
        return True
    dialog = PinPromptDialog(parent, encoded_hash, prompt=reason)
    return dialog.show() is True
