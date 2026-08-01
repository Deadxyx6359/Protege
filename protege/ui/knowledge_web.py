"""The knowledge web -- the skill-tree view of what the model may know.

A canvas of glowing and dark nodes: domains as hubs, topics branching off them,
co-tagged topics linked by faint threads. Unlocked topics glow purple; locked
ones sit dark with a dim outline -- territory that exists but has not been
taught. Clicking a node shows its details and offers the unlock or re-lock
flow, so the map is a control surface, not just a picture.

Reuses UnlockDialog and RelockDialog rather than reimplementing either: the
demonstration-and-approval ritual is the lock system's front door, and a
second, simpler door would inevitably become the weaker one.
"""

from __future__ import annotations

import tkinter as tk
from ..knowledge_graph import KnowledgeGraph, TopicNode, build_graph, layout, summarize
from ..lock.tripwires import TripwireSet
from ..retention import age_of, review_queue
from ..unlock import UnlockFlow
from ..vault import scan_vault
from . import sprites, theme
from .unlock_dialog import RelockDialog, UnlockDialog
from .widgets import MUTED_FG, ModalDialog, button_row


class KnowledgeWebDialog(ModalDialog):
    """Returns the updated Manifest when unlock/relock changed it, else None."""

    def __init__(self, parent: tk.Misc, flow: UnlockFlow) -> None:
        super().__init__(parent, "Knowledge web", width=980, height=720)
        self.flow = flow
        self._changed = False
        self._selected: str | None = None
        self._hit: dict[int, str] = {}  # canvas item id -> topic
        self._images: list = []         # live PhotoImage references
        retention = flow.settings.retention
        self._review_after = retention.review_after_days if retention.enabled else 0
        self._due: set[str] = set()

        self.canvas = tk.Canvas(self, bg=theme.BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)

        bottom = tk.Frame(self)
        bottom.pack(fill="x")
        self.detail = tk.Label(
            bottom, text="", anchor="w", justify="left", padx=12, pady=4,
            fg=MUTED_FG, font=theme.ui_font(),
        )
        self.detail.pack(side="left", fill="x", expand=True)
        self.buttons = button_row(
            bottom,
            [("Close", self._close), ("Re-lock", self._relock),
             ("Review...", self._review), ("Unlock...", self._unlock)],
        )
        self.buttons.pack(side="right")
        self._unlock_button = self.buttons.winfo_children()[3]
        self._review_button = self.buttons.winfo_children()[2]
        self._relock_button = self.buttons.winfo_children()[1]
        self._set_action_state(None)

        self.graph: KnowledgeGraph = KnowledgeGraph()
        self._rebuild()
        # The first draw happens before the bottom button row has claimed its
        # space, so the canvas still reports the taller pre-layout height and
        # nodes get placed below what ends up visible. One deferred redraw once
        # geometry has settled fixes it; <Configure> keeps it right afterwards.
        self.after_idle(self._redraw)

    # -- data ---------------------------------------------------------------

    def _rebuild(self) -> None:
        scan = scan_vault(self.flow.vault)
        self.graph = build_graph(scan, self.flow.manifest, TripwireSet.load(self.flow.vault))
        self._due = {
            age.topic
            for age in review_queue(self.flow.manifest, review_after_days=self._review_after)
        }
        self._redraw()

    # -- drawing ------------------------------------------------------------

    def _redraw(self) -> None:
        canvas = self.canvas
        if not canvas.winfo_exists():
            return
        canvas.delete("all")
        self._hit.clear()
        # Dropped every redraw: Tk frees a PhotoImage the moment its last
        # Python reference goes, and the canvas item then renders empty.
        self._images = []
        width = max(canvas.winfo_width(), 200)
        height = max(canvas.winfo_height(), 200)
        self._drawn_size = (width, height)
        layout(self.graph, width, height)

        if not self.graph.nodes:
            canvas.create_text(
                width / 2, height / 2,
                text=summarize(self.graph),
                fill=theme.FG_DIM, font=theme.ui_font(), width=int(width * 0.6),
            )
            return

        # Edges under nodes. Co-tag threads faint; branches purple.
        for edge in self.graph.edges:
            a, b = self.graph.nodes.get(edge.a), self.graph.nodes.get(edge.b)
            if a is None or b is None:
                continue
            if edge.kind == "branch":
                sprites.draw_line(canvas, a.x, a.y, b.x, b.y,
                                  colour=theme.PURPLE_DIM, width=2)
            else:
                sprites.draw_line(canvas, a.x, a.y, b.x, b.y,
                                  colour=theme.PURPLE_GHOST, dash=(2, 5))

        for node in self.graph.nodes.values():
            self._draw_node(node)

        canvas.create_text(
            12, height - 10, anchor="sw",
            text=summarize(self.graph),
            fill=theme.FG_DIM, font=theme.ui_font(size=9),
        )
        self._draw_legend(width)

    def _draw_node(self, node: TopicNode) -> None:
        """Blit an antialiased sprite for the node.

        Tk's canvas primitives are not antialiased, and a field of staircased
        circles is the single roughest thing in this window. Sprites are
        rasterised with coverage sampling and cached by shape, so a redraw is
        a handful of dictionary lookups regardless of how many nodes there are.
        """
        canvas = self.canvas
        x, y, r = node.x, node.y, node.radius
        selected = node.topic == self._selected
        radius = int(r)

        if node.is_real and node.unlocked:
            image = sprites.node_sprite(canvas, radius, fill=theme.PURPLE,
                                        outline=theme.PURPLE_BRIGHT, glow=True,
                                        selected=selected)
            label_fill = theme.FG
        elif node.is_real:
            # Locked: dark core, dim outline -- visible territory, not open.
            image = sprites.node_sprite(canvas, radius, fill=theme.BG_PANEL,
                                        outline=theme.PURPLE_GHOST, selected=selected)
            label_fill = theme.FG_DIM
        else:
            # Synthetic hub: a junction, not a topic.
            image = sprites.diamond_sprite(canvas, radius, outline=theme.PURPLE_DIM,
                                           fill=theme.BG, selected=selected)
            label_fill = theme.PURPLE

        # Keep a Python reference or Tk frees the image and draws nothing.
        self._images.append(image)
        core = canvas.create_image(x, y, image=image)

        label_font = theme.font(size=10, bold=node.is_hub) if node.is_hub else theme.ui_font(size=9)
        # Below the node, cleared of the glow (which reaches r + 9 when
        # unlocked). Hubs in the lower half of the canvas put their label above
        # instead: their branches fan *outward*, so a label below one is a
        # label written across its own edges.
        _, canvas_height = getattr(self, "_drawn_size", (0, 0))
        above = node.is_hub and canvas_height and y >= canvas_height / 2
        label = canvas.create_text(
            x, y - r - 14 if above else y + r + 17,
            text=node.label, fill=label_fill, font=label_font,
        )
        if node.has_tripwires and node.is_real and not node.unlocked:
            canvas.create_text(x, y - r - 9, text="#", fill=theme.WARNING_FG,
                               font=theme.font(size=8))
        if node.is_real and node.topic in self._due:
            # Still unlocked, so still a glowing circle -- a due topic has not
            # lost anything. The amber tick is the same colour the warning strip
            # uses, and means the same thing: worth your attention, not broken.
            canvas.create_text(x + r + 6, y - r - 4, text="!", fill=theme.WARNING_FG,
                               font=theme.font(size=9, bold=True))

        if node.is_real:
            self._hit[core] = node.topic
            self._hit[label] = node.topic
            canvas.tag_bind(core, "<Enter>", lambda _e: canvas.configure(cursor="hand2"))
            canvas.tag_bind(core, "<Leave>", lambda _e: canvas.configure(cursor=""))

    def _draw_legend(self, width: int) -> None:
        canvas = self.canvas
        items = (
            (theme.PURPLE, theme.PURPLE_BRIGHT, "unlocked"),
            (theme.BG_PANEL, theme.PURPLE_GHOST, "locked"),
        )
        x = width - 12
        for fill, outline, label in reversed(items):
            canvas.create_text(x, 18, anchor="e", text=label, fill=theme.FG_DIM,
                               font=theme.ui_font(size=9))
            x -= 8 + 7 * len(label)
            swatch = sprites.node_sprite(canvas, 6, fill=fill, outline=outline)
            self._images.append(swatch)
            canvas.create_image(x - 6, 18, image=swatch)
            x -= 22

    # -- interaction --------------------------------------------------------

    def _topic_at(self, event: tk.Event) -> str | None:
        for item in self.canvas.find_overlapping(event.x - 2, event.y - 2, event.x + 2, event.y + 2):
            if item in self._hit:
                return self._hit[item]
        return None

    def _on_motion(self, event: tk.Event) -> None:
        self.canvas.configure(cursor="hand2" if self._topic_at(event) else "")

    def _on_click(self, event: tk.Event) -> None:
        topic = self._topic_at(event)
        self._selected = topic
        self._set_action_state(topic)
        if topic is None:
            self.detail.configure(text="")
            self._redraw()
            return
        node = self.graph.nodes[topic]
        bits = [topic]
        bits.append("UNLOCKED" if node.unlocked else "locked")
        bits.append(f"{node.note_count} note(s)")
        bits.append("tripwires set" if node.has_tripwires else "no tripwires")
        if node.unlocked and self._review_after:
            age = age_of(self.flow.manifest, topic, review_after_days=self._review_after)
            bits.append(age.describe().split(": ", 1)[-1])
        for event_record in self.flow.manifest.history:
            if event_record.topic == topic:
                bits.append(f"last {event_record.action}: {event_record.at[:10]}")
        self.detail.configure(text="   |   ".join(bits))
        self._redraw()

    def _set_action_state(self, topic: str | None) -> None:
        if topic is None:
            for button in (self._unlock_button, self._relock_button, self._review_button):
                button.configure(state="disabled")
            return
        unlocked = self.flow.manifest.is_unlocked(topic)
        self._unlock_button.configure(state="disabled" if unlocked else "normal")
        self._relock_button.configure(state="normal" if unlocked else "disabled")
        self._review_button.configure(state="normal" if unlocked else "disabled")

    def _review(self) -> None:
        if self._selected is None or not self.flow.manifest.is_unlocked(self._selected):
            return
        manifest = UnlockDialog(self, self.flow, review_topic=self._selected).show()
        if manifest is not None:
            self.flow.manifest = manifest
            self._changed = True
        self._rebuild()
        self._set_action_state(self._selected)

    def _unlock(self) -> None:
        if self._selected is None:
            return
        dialog = UnlockDialog(self, self.flow)
        dialog.topic_var.set(self._selected)
        manifest = dialog.show()
        if manifest is not None:
            self.flow.manifest = manifest
            self._changed = True
        self._rebuild()
        self._set_action_state(self._selected)

    def _relock(self) -> None:
        if self._selected is None:
            return
        manifest = RelockDialog(self, self.flow, self._selected).show()
        if manifest is not None:
            self.flow.manifest = manifest
            self._changed = True
        self._rebuild()
        self._set_action_state(self._selected)

    def _close(self) -> None:
        self.result = self.flow.manifest if self._changed else None
        self.destroy()

    def on_cancel(self) -> None:
        self._close()
