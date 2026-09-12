"""The floating action button.

A circular purple "+" pinned to the bottom-right of the chat area. Clicking it
raises a small card of the things you actually start from scratch: a skill, an
attachment, an import, a topic.

Why this exists rather than four more sidebar rows: those four are *creation*
actions, and creation is the one thing a person does deliberately and
infrequently enough that hunting for it in a list is annoying, but often enough
that burying it two menus deep is worse. Collecting them under one always-present
control keeps the sidebar for navigation -- places you go -- and gives creation
a single, memorable home.

Drawn on a canvas rather than assembled from widgets: Tk has no rounded or
circular buttons, and a square grey button with a "+" glyph in the corner of a
cyberpunk UI looks like a mistake.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Sequence

from . import sprites, theme


class FloatingActionButton(tk.Canvas):
    """A circular + button that opens an action card.

    Positioned by the caller with `place()`, so it floats above the chat rather
    than taking layout space.
    """

    def __init__(
        self,
        parent: tk.Misc,
        actions: Sequence[tuple[str, str, Callable[[], None]]],
        *,
        diameter: int = 56,
    ) -> None:
        self._d = theme.px(diameter)
        super().__init__(parent, width=self._d, height=self._d, bg=theme.BG,
                         highlightthickness=0, bd=0)
        # (label, one-line description, callback)
        self._actions = list(actions)
        self._card: tk.Toplevel | None = None
        self._hover = False

        self._draw()
        self.bind("<Button-1>", lambda _e: self.toggle())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.configure(cursor="hand2")

    # -- painting -----------------------------------------------------------

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._draw()

    def _draw(self) -> None:
        """Blit a pre-rendered, antialiased sprite.

        Tk's `create_oval` and `create_line` have no antialiasing, so the
        circle staircased and the diagonal strokes of the x were the roughest
        edges in the window. The sprite is rasterised with coverage sampling
        and cached, so hover repaints are a dictionary lookup.
        """
        self.delete("all")
        # Held on the instance: Tk frees a PhotoImage as soon as its last
        # Python reference goes, and the canvas item then draws nothing.
        self._image = sprites.fab_sprite(
            self, self._d, hover=self._hover, rotated=self._card is not None
        )
        self.create_image(0, 0, image=self._image, anchor="nw")

    # -- the action card ----------------------------------------------------

    def toggle(self) -> None:
        if self._card is not None:
            self.close()
        else:
            self.open()

    def open(self) -> None:
        if self._card is not None or not self._actions:
            return
        self.update_idletasks()

        # An in-window Frame, not a Toplevel. An `overrideredirect` popup on
        # Windows quietly ignores `geometry()` -- it renders, but parks itself
        # at the top-left of the display no matter what coordinates it is
        # given. Placing a frame inside the main window sidesteps that whole
        # class of problem, and a menu that belongs to this window has no
        # business being a separate OS window in the first place.
        parent = self.master
        card = tk.Frame(parent, bg=theme.PURPLE_DIM)
        self._card = card

        inner = tk.Frame(card, bg=theme.BG_RAISED)
        inner.pack(padx=1, pady=1)

        for label, description, command in self._actions:
            row = tk.Frame(inner, bg=theme.BG_RAISED, cursor="hand2")
            row.pack(fill="x")
            # Asymmetric spacing goes on pack(), not the widget: a widget's
            # own -pady takes a single distance and rejects a 2-tuple with
            # "bad screen distance".
            title = tk.Label(
                row, text=label, anchor="w", bg=theme.BG_RAISED, fg=theme.FG,
                font=theme.ui_font(bold=True), padx=theme.px(14),
            )
            title.pack(fill="x", pady=(theme.px(7), 0))
            subtitle = tk.Label(
                row, text=description, anchor="w", bg=theme.BG_RAISED, fg=theme.FG_DIM,
                font=theme.ui_font(size=theme.UI_SIZE - 1), padx=theme.px(14),
            )
            subtitle.pack(fill="x", pady=(0, theme.px(7)))

            def enter(_e, r=row, t=title, s=subtitle):
                for w in (r, t, s):
                    w.configure(bg=theme.PURPLE_DEEP)

            def leave(_e, r=row, t=title, s=subtitle):
                for w in (r, t, s):
                    w.configure(bg=theme.BG_RAISED)

            def click(_e, fn=command):
                self.close()
                fn()

            for widget in (row, title, subtitle):
                widget.bind("<Enter>", enter)
                widget.bind("<Leave>", leave)
                widget.bind("<Button-1>", click)

        card.update_idletasks()

        # Sits directly above the button, right edges aligned. Coordinates are
        # relative to the shared parent, so no screen-space arithmetic and
        # nothing that depends on a mapped window.
        card.place(
            in_=parent,
            relx=1.0, rely=1.0, anchor="se",
            x=theme.px(-26),
            y=-(self._d + theme.px(36)),
        )
        card.lift()

        # Any click elsewhere, or Escape, dismisses it.
        self.winfo_toplevel().bind("<Button-1>", self._maybe_close, add="+")
        self.winfo_toplevel().bind("<Escape>", self._escape, add="+")
        self._draw()

    def _escape(self, _event: tk.Event) -> None:
        self.close()

    def _maybe_close(self, event: tk.Event) -> None:
        if self._card is None:
            return
        # Clicks on the button itself (toggle) or anywhere inside the card
        # (an action) are handled by their own bindings.
        if event.widget is self:
            return
        widget = event.widget
        while widget is not None:
            if widget is self._card:
                return
            widget = getattr(widget, "master", None)
        self.close()

    def close(self) -> None:
        if self._card is None:
            return
        try:
            self._card.destroy()
        except tk.TclError:
            pass
        self._card = None
        self._draw()
