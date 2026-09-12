"""The side panel.

A narrow navigation rail: wordmark, the handful of places you actually go, the
project list, and a status footer.

**Deliberately short.** An earlier version listed thirteen rows -- every dialog
in the application, flattened. That is a menu bar wearing a sidebar's clothes:
it optimises for "everything is reachable" when the thing that makes a tool
pleasant is "the four things I do constantly are obvious". Creation actions
(new skill, attach, import, unlock) moved to the floating + button, which is
where a person looks to make something. What is left here is *navigation* --
places with state you go to inspect.

Rows are flat labels with hover highlights rather than tk.Buttons: a column of
raised button borders reads as a dialog from 2003.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from . import theme

WIDTH = 208

# (key, label, glyph). Order is frequency of use, not alphabet.
NAV_ITEMS = (
    ("new_session", "New session", "+"),
    ("knowledge_web", "Knowledge", "*"),
    ("vault", "Vault", "#"),
    ("memory", "Memory", "~"),
    ("history", "History", "^"),
    ("skills", "Skills", ">"),
)


class _Row(tk.Frame):
    """One flat, hoverable navigation row."""

    def __init__(self, parent: tk.Misc, glyph: str, text: str,
                 command: Callable[[], None], *, accent: bool = False) -> None:
        super().__init__(parent, bg=theme.BG_PANEL, cursor="hand2")
        fg = theme.PURPLE_BRIGHT if accent else theme.FG

        self.mark = tk.Label(self, text=glyph, bg=theme.BG_PANEL, fg=theme.PURPLE,
                             font=theme.font(size=theme.UI_SIZE), width=2)
        self.mark.pack(side="left", padx=(theme.px(14), theme.px(4)))
        self.text = tk.Label(self, text=text, anchor="w", bg=theme.BG_PANEL, fg=fg,
                             font=theme.ui_font())
        self.text.pack(side="left", fill="x", expand=True, pady=theme.px(7))

        for widget in (self, self.mark, self.text):
            widget.bind("<Button-1>", lambda _e: command())
            widget.bind("<Enter>", lambda _e: self._hover(True))
            widget.bind("<Leave>", lambda _e: self._hover(False))

    def _hover(self, on: bool) -> None:
        colour = theme.PURPLE_DEEP if on else theme.BG_PANEL
        for widget in (self, self.mark, self.text):
            widget.configure(bg=colour)


class Sidebar(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        actions: dict[str, Callable[[], None]],
        projects: list[str],
        current_project: str,
        on_switch_project: Callable[[str], None],
        on_new_project: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=theme.BG_PANEL, width=theme.px(WIDTH))
        self.pack_propagate(False)
        self._on_switch_project = on_switch_project
        self._project_rows: dict[str, tk.Label] = {}

        header = tk.Frame(self, bg=theme.BG_PANEL)
        header.pack(fill="x", pady=(theme.px(16), theme.px(6)))
        tk.Label(
            header, text="AKIRA", bg=theme.BG_PANEL, fg=theme.PURPLE_BRIGHT,
            font=theme.font(size=theme.MONO_SIZE + 3, bold=True), anchor="w",
            padx=theme.px(16),
        ).pack(fill="x")
        tk.Label(
            header, text="local · gated · offline", bg=theme.BG_PANEL, fg=theme.FG_DIM,
            font=theme.ui_font(size=theme.UI_SIZE - 2), anchor="w", padx=theme.px(16),
        ).pack(fill="x")

        self._rule()

        for key, label, glyph in NAV_ITEMS:
            if key in actions:
                _Row(self, glyph, label, actions[key],
                     accent=(key == "new_session")).pack(fill="x")

        self._rule()

        tk.Label(
            self, text="PROJECTS", bg=theme.BG_PANEL, fg=theme.FG_DIM,
            font=theme.ui_font(size=theme.UI_SIZE - 2, bold=True), anchor="w",
            padx=theme.px(16),
        ).pack(fill="x", pady=(theme.px(4), theme.px(2)))

        self._projects_box = tk.Frame(self, bg=theme.BG_PANEL)
        self._projects_box.pack(fill="x")
        _Row(self, "+", "New project", on_new_project).pack(fill="x")

        # Plugin contributions land here, above the footer.
        self._plugin_box = tk.Frame(self, bg=theme.BG_PANEL)
        self._plugin_box.pack(fill="x")

        footer = tk.Frame(self, bg=theme.BG_PANEL)
        footer.pack(side="bottom", fill="x", pady=(0, theme.px(10)))
        self.status = tk.Label(
            footer, text="", bg=theme.BG_PANEL, fg=theme.FG_DIM,
            font=theme.ui_font(size=theme.UI_SIZE - 2), anchor="w", justify="left",
            padx=theme.px(16),
        )
        self.status.pack(fill="x", pady=(theme.px(8), 0))

        # A mode switch belongs where you can reach it, not three clicks into
        # Settings. Its label carries the current state rather than a checkbox,
        # so the sidebar answers "which mode am I in" without being asked.
        self.mode_row = None
        if "toggle_everyday" in actions:
            self.mode_row = _Row(footer, "@", "Everyday mode",
                                 actions["toggle_everyday"])
            self.mode_row.pack(fill="x")

        for key, label, glyph in (("settings", "Settings", "="), ("about", "About", "?")):
            if key in actions:
                _Row(footer, glyph, label, actions[key]).pack(fill="x")

        self.set_projects(projects, current_project)

    def _rule(self) -> None:
        tk.Frame(self, bg=theme.PURPLE_GHOST, height=1).pack(
            fill="x", padx=theme.px(12), pady=theme.px(8)
        )

    # -- projects ------------------------------------------------------------

    def set_projects(self, projects: list[str], current: str) -> None:
        for child in list(self._projects_box.children.values()):
            child.destroy()
        self._project_rows.clear()
        for name in projects:
            active = name == current
            row = tk.Label(
                self._projects_box,
                text=("▸ " if active else "  ") + name,
                anchor="w", padx=theme.px(16), pady=theme.px(4),
                bg=theme.PURPLE_DEEP if active else theme.BG_PANEL,
                fg=theme.FG if active else theme.FG_DIM,
                font=theme.ui_font(size=theme.UI_SIZE - 1),
                cursor="hand2",
            )
            row.pack(fill="x")
            row.bind("<Button-1>", lambda _e, n=name: self._on_switch_project(n))
            if not active:
                row.bind("<Enter>", lambda _e, r=row: r.configure(bg=theme.PURPLE_DEEP))
                row.bind("<Leave>", lambda _e, r=row: r.configure(bg=theme.BG_PANEL))
            self._project_rows[name] = row

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def set_everyday(self, on: bool) -> None:
        """Label the mode row with the state, and colour it when the lock is off."""
        if self.mode_row is None:
            return
        self.mode_row.text.configure(
            text="Everyday mode: ON" if on else "Everyday mode",
            fg=theme.WARNING_FG if on else theme.FG,
        )
        self.mode_row.mark.configure(fg=theme.WARNING_FG if on else theme.PURPLE)

    def add_plugin_items(self, items: list[tuple[str, Callable[[], None]]]) -> None:
        """Show plugin-contributed actions. Replaces whatever was there."""
        for child in list(self._plugin_box.children.values()):
            child.destroy()
        if not items:
            return
        tk.Frame(self._plugin_box, bg=theme.PURPLE_GHOST, height=1).pack(
            fill="x", padx=theme.px(12), pady=theme.px(8)
        )
        for label, command in items:
            _Row(self._plugin_box, "·", label, command).pack(fill="x")
