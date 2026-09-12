"""Shared Tkinter helpers.

Plain `tk` widgets throughout, themed through `theme.py`'s option database and
palette -- no third-party styling packages, no images, no icons. (The original
brief said "no theming"; the user later specified the purple/black/ivory look,
and `theme.py` documents that departure.)

The loud colors stay reserved: the amber warning strip when a lock layer is
off, and pink-red for blocked responses and destructive confirmations. Purple
is structure and interaction; ivory is prose.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Callable, Sequence

from . import theme


class ThemedScrolledText(scrolledtext.ScrolledText):
    """ScrolledText with a ttk scrollbar that hides itself when unneeded.

    On Windows the classic tk.Scrollbar is drawn by the OS and ignores every
    color option, which puts a bright white bar down the edge of an otherwise
    black window. The ttk scrollbar honors the 'clam' style configured in
    `theme._style_ttk`.

    It also disappears when everything fits. A scrollbar pinned full-height
    down an empty chat is pure noise -- it says "there is more here" when there
    is nothing here -- and reclaiming that strip lets the rain run right up to
    the edge of the column.
    """

    def __init__(self, master=None, **kw) -> None:
        super().__init__(master, **kw)
        self.vbar.destroy()
        vbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.yview)
        self.vbar = vbar
        self._vbar_shown = False
        self.configure(yscrollcommand=self._on_yscroll)

    def _on_yscroll(self, first: str, last: str) -> None:
        needed = not (float(first) <= 0.0 and float(last) >= 1.0)
        if needed != self._vbar_shown:
            if needed:
                self.vbar.pack(side="right", fill="y")
            else:
                self.vbar.pack_forget()
            self._vbar_shown = needed
        self.vbar.set(first, last)

# Re-exported so every module that imports these names keeps working. The
# values live in theme.py -- the single source of truth for the palette.
WARNING_BG = theme.WARNING_BG
DANGER_FG = theme.DANGER
MUTED_FG = theme.FG_DIM


class ModalDialog(tk.Toplevel):
    """A Toplevel that grabs focus and blocks until dismissed.

    Every destructive or consequential action in Akira goes through one of
    these rather than an inline control, so that "I clicked it by accident" is
    not a way to unlock a topic or delete a transcript.
    """

    def __init__(
        self, parent: tk.Misc, title: str, *, width: int = 640, height: int = 480,
        transient: bool = True,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        # Sizes are authored against an unscaled display; on a 125% screen a
        # literal 640x480 is physically three-quarters the intended size, which
        # is enough on its own to push a button row off the bottom.
        self._requested_size = (theme.px(width), theme.px(height))
        self.geometry(f"{self._requested_size[0]}x{self._requested_size[1]}")
        # Grow to fit whatever the content actually needs, and never shrink
        # below it. `_fit_to_content` runs once the children are laid out.
        self.after_idle(self._fit_to_content)
        # On Windows a transient toplevel is never mapped while its master is
        # withdrawn -- the launch PIN dialogs open over a withdrawn root and
        # must pass transient=False or the app waits forever on an invisible
        # modal. Dialogs opened from a visible window keep the default.
        if transient:
            self.transient(parent)
        theme.apply_window_chrome(self)
        self.result = None
        # The widget that should hold keyboard focus once the dialog is
        # actually visible. A focus_set() during construction happens before
        # the window is mapped and does not stick, which leaves the user
        # typing at a dialog frame that swallows every keystroke.
        self.initial_focus: tk.Widget | None = None
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def show(self):
        # Non-transient dialogs have no master to stack above; force them up
        # front so they cannot open behind another application's window.
        self.lift()
        try:
            self.wait_visibility()
            self.grab_set()
            (self.initial_focus or self).focus_force()
        except tk.TclError:
            # A dialog destroyed before it became visible (e.g. programmatic
            # close in tests) must not crash the caller.
            pass
        self.wait_window()
        return self.result

    def _fit_to_content(self) -> None:
        """Ensure the window is at least as large as the controls inside it.

        A dialog whose Save button sits below the fold is a feature the user
        cannot reach, and "just drag it bigger" is not always available on a
        laptop screen. Tk knows the required size once children are laid out,
        so ask it rather than guessing -- and set a matching minsize so the
        window cannot later be dragged smaller than its own contents.

        Capped to the screen: a dialog larger than the display is a different
        and worse failure than one that scrolls.
        """
        try:
            self.update_idletasks()
            need_w, need_h = self.winfo_reqwidth(), self.winfo_reqheight()
            # Floor is the size the dialog *asked* for, never `winfo_width()`.
            # An unmapped window reports 1x1, so `max(needed, actual)` collapses
            # to the bare requirement -- and for a dialog whose content sits on
            # a canvas (the PIN screens draw their form as a canvas window
            # item, which contributes nothing to reqwidth) that requirement is
            # a sliver. This method may only ever grow a window.
            floor_w, floor_h = self._requested_size
            max_w = self.winfo_screenwidth() - theme.px(80)
            max_h = self.winfo_screenheight() - theme.px(120)
            want_w = min(max(need_w, floor_w), max_w)
            want_h = min(max(need_h, floor_h), max_h)
            if (want_w, want_h) != (floor_w, floor_h):
                self.geometry(f"{want_w}x{want_h}")
                self._requested_size = (want_w, want_h)
            self.minsize(min(min(need_w, floor_w), max_w),
                         min(min(need_h, floor_h), max_h))
        except tk.TclError:
            pass

    def on_cancel(self) -> None:
        self.result = None
        self.destroy()


def read_only_text(parent: tk.Misc, content: str = "", *, height: int = 12) -> scrolledtext.ScrolledText:
    widget = ThemedScrolledText(parent, wrap="word", height=height, padx=6, pady=6)
    widget.insert("1.0", content)
    widget.configure(state="disabled")
    return widget


def set_text(widget: scrolledtext.ScrolledText, content: str) -> None:
    """Replace a read-only text widget's contents."""
    was_disabled = str(widget.cget("state")) == "disabled"
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", content)
    if was_disabled:
        widget.configure(state="disabled")


def button_row(parent: tk.Misc, buttons: Sequence[tuple[str, Callable[[], None]]]) -> tk.Frame:
    """A right-aligned row of buttons, first in the list rightmost."""
    row = tk.Frame(parent)
    for label, command in buttons:
        tk.Button(row, text=label, width=12, command=command).pack(side="right", padx=4, pady=6)
    return row


class LabeledSlider(tk.Frame):
    """A 0-100 slider that shows the *band prose*, never the number.

    The number is deliberately absent from the display as well as from the
    prompt. Showing "72" invites the user to tune a value the model cannot
    distinguish from 68; showing the band text makes the five real settings
    visible, which is what they are actually choosing between.
    """

    def __init__(
        self,
        parent: tk.Misc,
        label: str,
        bands: Sequence[str],
        value: int = 50,
        *,
        on_change: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.bands = list(bands)
        self._on_change = on_change

        header = tk.Frame(self)
        header.pack(fill="x")
        tk.Label(header, text=label, anchor="w", font=(theme.font_family(), 9, "bold")).pack(side="left")
        self.band_number = tk.Label(header, text="", anchor="e", fg=MUTED_FG)
        self.band_number.pack(side="right")

        self.scale = tk.Scale(
            self,
            from_=0,
            to=100,
            orient="horizontal",
            showvalue=False,   # the number is not the setting
            command=self._changed,
        )
        self.scale.set(value)
        self.scale.pack(fill="x")

        self.band_label = tk.Label(self, text="", anchor="w", justify="left", wraplength=520, fg=MUTED_FG)
        self.band_label.pack(fill="x", pady=(0, 8))
        self._changed(str(value))

    def _changed(self, raw: str) -> None:
        from ..schemas import NEUTRAL_BAND, band_for_value

        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            return
        band = band_for_value(value)
        self.band_label.configure(text=self.bands[band] if band < len(self.bands) else "")
        suffix = " (neutral - not sent to the model)" if band == NEUTRAL_BAND else ""
        self.band_number.configure(text=f"band {band + 1} of 5{suffix}")
        if self._on_change:
            self._on_change(value)

    def get(self) -> int:
        return int(self.scale.get())

    def set(self, value: int) -> None:
        self.scale.set(value)


class ScrollableFrame(tk.Frame):
    """A frame with a vertical scrollbar, for the long trait list."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = tk.Frame(canvas)

        self.inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        window = canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._canvas = canvas

    def scroll_to_top(self) -> None:
        self._canvas.yview_moveto(0.0)
