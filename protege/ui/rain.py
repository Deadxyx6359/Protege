"""The character rain.

Vertical columns of glyphs falling down a black canvas, purple head fading to a
deep-violet tail. Used two ways: as a gutter beside the chat scrollback, and as
the full backdrop of the PIN screen.

**Smoothness model.** The first version moved glyphs a whole 16px cell every
85ms, which reads as a stutter -- the eye tracks the jump, not the fall. This
version moves continuously: each column has a float velocity in pixels per
tick at ~30fps, and every tick issues one `canvas.move` per column (all of a
column's glyphs share a tag, so a column moves as a unit in a single Tcl call).
Glyph *identity* still changes on cell boundaries -- re-inking every frame at
30fps turns the rain into static noise, while re-inking on crossings keeps the
"data falling" read. Cost: ~40 move calls plus a handful of itemconfigures per
33ms tick, well under what Tk redraws comfortably.

The glyph set is ASCII letters, digits, and structural symbols. Deliberately no
katakana: Tk's font fallback for missing glyphs is inconsistent across Windows
installs, and one tofu box ruins the effect.

Lifecycle matters more than it looks: an `after` callback that fires on a
destroyed canvas raises TclError in the Tk mainloop. `stop()` cancels the
pending tick, `<Destroy>` calls it automatically, and the tick itself re-checks
`winfo_exists` because a destroy can land between scheduling and firing.
"""

from __future__ import annotations

import random
import tkinter as tk

from . import theme

GLYPHS = "01ABCDEFGHIJKLMNOPQRSTUVWXYZ23456789#$%&+=*<>/\\|[]{}"

CELL_H = 18
CELL_W = 13
TICK_MS = 33  # ~30fps; continuous motion needs frame rate more than step size

SPEED_MIN = 1.6   # px per tick -- a slow drizzle column
SPEED_MAX = 4.2   # px per tick -- a fast streak

# Chance that a non-head glyph re-inks when its column crosses a cell
# boundary. The head always re-inks on crossing.
TRAIL_FLICKER = 0.25


class _Column:
    __slots__ = ("tag", "x", "y", "speed", "delay", "items", "last_cell", "height")

    def __init__(self, canvas: tk.Canvas, tag: str, x: int, trail: int,
                 canvas_height: int) -> None:
        self.tag = tag
        self.x = x
        # Spread the initial heads across the whole canvas, not just above it.
        # At 2-4 px/tick a column needs 12-23 seconds to fall past a 1400px
        # window, so starting them all overhead means the field is still
        # descending -- empty below, clustered at the top -- for the first
        # twenty seconds of every launch. Seeded across the height, it reads as
        # already-running from the first frame.
        self.y = random.uniform(-trail * CELL_H, canvas_height)
        self.speed = random.uniform(SPEED_MIN, SPEED_MAX)
        self.delay = random.randint(0, 12)
        self.last_cell = int(self.y // CELL_H)
        self.height = trail * CELL_H
        self.items: list[int] = [
            canvas.create_text(
                x,
                self.y - i * CELL_H,
                text=random.choice(GLYPHS),
                fill=theme.RAIN_COLORS[min(i, len(theme.RAIN_COLORS) - 1)],
                font=(theme.font_family(), 11),
                anchor="n",
                # Both tags: "rain" for bulk delete on rebuild, the column tag
                # for one-call movement of the whole trail.
                tags=("rain", tag),
            )
            for i in range(trail)
        ]

    def reset(self, canvas: tk.Canvas, canvas_height: int) -> None:
        """Teleport back above the top with fresh speed and stagger."""
        target = float(-random.randint(0, 260))
        canvas.move(self.tag, 0, target - self.y)
        self.y = target
        self.speed = random.uniform(SPEED_MIN, SPEED_MAX)
        self.delay = random.randint(0, 20)
        self.last_cell = int(target // CELL_H)


class RainCanvas(tk.Canvas):
    """A self-animating rain surface.

    `density` scales how many columns of the available width are used --
    gutters run dense (1.0), the PIN backdrop slightly sparser (0.7) so the
    centered entry panel stays the focal point.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        width: int = 84,
        density: float = 1.0,
        trail: int = 7,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            width=width,
            bg=theme.BG,
            highlightthickness=0,
            bd=0,
            **kwargs,
        )
        self._density = max(0.1, min(1.0, density))
        self._trail = trail
        self._columns: list[_Column] = []
        self._after_id: str | None = None
        self._running = False
        self._built_for: tuple[int, int] = (0, 0)
        self._tag_serial = 0

        self.bind("<Configure>", self._on_resize)
        self.bind("<Destroy>", lambda _e: self.stop())

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._schedule()

    def stop(self) -> None:
        self._running = False
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _schedule(self) -> None:
        if self._running:
            self._after_id = self.after(TICK_MS, self._tick)

    # -- geometry -----------------------------------------------------------

    def _on_resize(self, _event: tk.Event) -> None:
        size = (self.winfo_width(), self.winfo_height())
        if size == self._built_for or size[0] <= 1:
            return
        self._built_for = size
        self.delete("rain")
        self._columns.clear()
        width, height = size
        slots = max(1, width // CELL_W)
        used = max(1, int(slots * self._density))
        xs = random.sample(range(slots), used) if used < slots else range(slots)
        for slot in xs:
            self._tag_serial += 1
            self._columns.append(
                _Column(self, f"raincol{self._tag_serial}",
                        slot * CELL_W + CELL_W // 2, self._trail, height)
            )
        # Canvas z-order is creation order, and columns are rebuilt on every
        # resize -- without this the fresh glyphs would draw over an embedded
        # window item (the PIN screen's form panel).
        self.tag_lower("rain")

    # -- animation ----------------------------------------------------------

    def _tick(self) -> None:
        self._after_id = None
        if not self._running or not self.winfo_exists():
            return
        height = self.winfo_height()

        for column in self._columns:
            if column.delay > 0:
                column.delay -= 1
                continue

            self.move(column.tag, 0, column.speed)
            column.y += column.speed

            if column.y - column.height > height:
                column.reset(self, height)
                continue

            # Re-ink glyphs only when the column crosses into a new cell, so
            # the characters change at a readable rhythm regardless of speed.
            cell = int(column.y // CELL_H)
            if cell != column.last_cell:
                column.last_cell = cell
                self.itemconfigure(column.items[0], text=random.choice(GLYPHS))
                for item in column.items[1:]:
                    if random.random() < TRAIL_FLICKER:
                        self.itemconfigure(item, text=random.choice(GLYPHS))

        self._schedule()
