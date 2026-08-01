"""The working indicator.

A pulsing dot, the current stage in words, and an elapsed clock, shown inline
where the reply will appear. Modelled on Claude's: the point is that a long
wait should never look like a hang, and the user should be able to tell
*which* slow thing is happening.

That last part matters more here than in most chat UIs, because a turn is not
one operation. Retrieval, prompt assembly, generation and the auditor pass are
four distinct phases with very different durations, and on a 24B at ~2 tok/s a
turn runs 40 seconds or more. "Working..." for 40 seconds is indistinguishable
from a crash; "checking the response (Layer 5) - 0:18" is a system visibly
doing its job.

Stage names are user-facing prose, not internal identifiers -- the pipeline
emits `retrieving`, `assembling`, `generating`, `checking`, and STAGE_TEXT
turns those into something worth reading.
"""

from __future__ import annotations

import time
import tkinter as tk

from . import theme

STAGE_TEXT = {
    "retrieving": "searching your notes",
    "assembling": "assembling context",
    "generating": "thinking",
    "checking": "checking the response",
    "summarizing": "reading your notes",
    "generating questions": "writing its own questions",
    "checking for other locked topics": "checking for other locked topics",
}

# Stages that deserve a note about *why* they can be slow. Shown once the
# phase has run long enough that the user starts to wonder.
STAGE_HINT = {
    "generating": "the model writes about two words a second",
    "checking": "Layer 5 -- the auditor reads the whole draft",
}

HINT_AFTER_S = 8.0
TICK_MS = 60
PULSE_PERIOD = 1.4  # seconds for one full brightness cycle

# Brightness ramp for the pulse, dim -> bright -> dim. Lives in theme.py:
# every colour in the application has exactly one definition site.
_PULSE_COLORS = theme.PULSE_RAMP


class ActivityIndicator(tk.Frame):
    """Pulsing dot + stage text + elapsed clock. Hidden until `start()`."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=theme.BG)
        self._after: str | None = None
        self._started = 0.0
        self._stage = ""
        self._stage_started = 0.0

        size = theme.px(14)
        self.dot = tk.Canvas(self, width=size, height=size, bg=theme.BG,
                             highlightthickness=0, bd=0)
        self.dot.pack(side="left", padx=(0, theme.px(9)))
        pad = theme.px(3)
        self._dot_id = self.dot.create_oval(
            pad, pad, size - pad, size - pad, fill=theme.PURPLE, outline=""
        )

        self.label = tk.Label(
            self, text="", anchor="w", bg=theme.BG, fg=theme.PURPLE_BRIGHT,
            font=theme.ui_font(size=theme.UI_SIZE),
        )
        self.label.pack(side="left")

        self.clock = tk.Label(
            self, text="", anchor="w", bg=theme.BG, fg=theme.FG_DIM,
            font=theme.ui_font(size=theme.UI_SIZE - 1),
        )
        self.clock.pack(side="left", padx=(theme.px(10), 0))

        self.hint = tk.Label(
            self, text="", anchor="w", bg=theme.BG, fg=theme.FG_DIM,
            font=theme.ui_font(size=theme.UI_SIZE - 1),
        )
        self.hint.pack(side="left", padx=(theme.px(10), 0))

        self.bind("<Destroy>", lambda _e: self.stop())

    # -- lifecycle ----------------------------------------------------------

    def start(self, stage: str = "generating") -> None:
        self._started = time.monotonic()
        self.set_stage(stage)
        if self._after is None:
            self._tick()

    def set_stage(self, stage: str) -> None:
        if stage == self._stage:
            return
        self._stage = stage
        self._stage_started = time.monotonic()
        self.label.configure(text=STAGE_TEXT.get(stage, stage))
        self.hint.configure(text="")

    def stop(self) -> None:
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    # -- animation ----------------------------------------------------------

    def _tick(self) -> None:
        self._after = None
        if not self.winfo_exists():
            return

        elapsed = time.monotonic() - self._started
        # Triangle wave over the ramp: smooth brighten then dim, no snap back.
        phase = (elapsed % PULSE_PERIOD) / PULSE_PERIOD
        position = phase * 2 if phase < 0.5 else (1 - phase) * 2
        index = min(len(_PULSE_COLORS) - 1, int(position * len(_PULSE_COLORS)))
        try:
            self.dot.itemconfigure(self._dot_id, fill=_PULSE_COLORS[index])
            self.clock.configure(text=f"{int(elapsed) // 60}:{int(elapsed) % 60:02d}")
            if time.monotonic() - self._stage_started > HINT_AFTER_S:
                hint = STAGE_HINT.get(self._stage, "")
                if hint and self.hint.cget("text") != hint:
                    self.hint.configure(text=hint)
        except tk.TclError:
            return

        self._after = self.after(TICK_MS, self._tick)
