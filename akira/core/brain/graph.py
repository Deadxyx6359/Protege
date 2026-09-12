"""The shape of what the vault knows: a map of its tags, and the links between notes.

B6, folding the legacy `knowledge_graph.py` onto the vault. Two views, both plain
data with no drawing in them, so they can be tested and the interface only has
to draw.

**The tag map** is the legacy skill tree, rebuilt on tags as Obsidian writes
them. A nested tag names its own hierarchy — `#garden/tomatoes` sits under
`garden` — so each first segment is a hub and the tags beneath it branch off it.
A hub nobody tagged directly is still drawn, marked as not a tag itself. Two
tags on one note are linked, because the person put them together. Nothing else
is inferred.

**The link graph** is the notes and the links between them, resolved the way
Obsidian resolves them. Links to notes that do not exist yet are counted, not
drawn: an unwritten note is a wish, not knowledge.

**Deterministic layout.** The tag map is placed radially, hubs on an ellipse and
their tags fanned outward, with the legacy map's geometry and the reasons for
it. The same vault always draws the same way, because a map that will not hold
still cannot be learned. The link graph is left for the interface to place.

Only notes the vault may read contribute, and past `MAX_NODES` the busiest are
kept and the rest counted. Everything here reads; nothing writes.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Iterator

from .vault import Note, Vault, VaultError

#: Past this a map is a smear. The busiest nodes are kept and the rest counted.
MAX_NODES = 400

# Room a label needs before it runs into its neighbour, and below its own node.
# Measured from rendered labels in the legacy map rather than guessed: a tag is
# short but not narrow.
LABEL_CLEARANCE = 88.0
MARGIN_X = 74.0
MARGIN_Y = 58.0

#: A branch shorter than this reads as a blob, however few children it has.
MIN_BRANCH = 96.0


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    hub: bool = False
    real: bool = True
    """False only for a hub nobody tagged directly."""

    weight: int = 0
    """How many notes carry the tag, or how many links touch the note."""

    x: float = 0.0
    y: float = 0.0
    radius: float = 0.0


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    kind: str
    """`branch` (a hub to a tag under it), `cotag` (tagged on one note), or `link`."""


@dataclass
class Graph:
    kind: str
    """`tags` or `links`."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    unresolved: int = 0
    """Links to notes that do not exist yet."""

    hidden: int = 0
    """Nodes left out past `MAX_NODES`."""

    @property
    def hubs(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.hub]

    def summary(self) -> str:
        if not self.nodes:
            if self.kind == "tags":
                return ("No tags yet. Tag notes with #subject, or #subject/detail, and the map "
                        "grows from there.")
            return "No notes yet."
        if self.kind == "tags":
            real = sum(1 for n in self.nodes.values() if n.real)
            text = f"{real} tag{'s' if real != 1 else ''} in {len(self.hubs)} group" + \
                   ("s" if len(self.hubs) != 1 else "")
        else:
            links = len(self.edges)
            text = f"{len(self.nodes)} notes, {links} link{'s' if links != 1 else ''}"
            if self.unresolved:
                text += f", {self.unresolved} to notes not written yet"
        if self.hidden:
            text += f"; {self.hidden} more left out to keep it readable"
        return text + "."

    def to_json(self) -> dict:
        return {"kind": self.kind, "nodes": [asdict(n) for n in self.nodes.values()],
                "edges": [asdict(e) for e in self.edges], "unresolved": self.unresolved,
                "hidden": self.hidden, "summary": self.summary()}


def _notes(vault: Vault, folder: Path | None) -> Iterator[Note]:
    for path in vault.note_paths():
        if folder is not None and not path.is_relative_to(folder):
            continue
        try:
            yield vault.read(path)
        except VaultError:
            continue


# -- the tag map ------------------------------------------------------------------------------


def tag_map(vault: Vault, folder: Path | None = None) -> Graph:
    """Tags as hubs and branches, with links between tags used together."""
    counts: dict[str, int] = {}
    spelling: dict[str, str] = {}
    together: list[list[str]] = []
    for note in _notes(vault, folder):
        keys: list[str] = []
        for tag in note.tags:
            key = tag.strip("/").lower()
            if key and key not in keys:
                spelling.setdefault(key, tag.strip("/"))
                keys.append(key)
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
        together.append(keys)

    graph = Graph("tags")
    kept = sorted(counts, key=lambda k: (-counts[k], k))[:MAX_NODES]
    graph.hidden = len(counts) - len(kept)

    clusters: dict[str, list[str]] = {}
    for key in sorted(kept):
        clusters.setdefault(key.split("/", 1)[0], []).append(key)
    for hub, members in clusters.items():
        label = spelling.get(hub) or spelling[members[0]].split("/", 1)[0]
        graph.nodes[hub] = Node(hub, label, hub=True, real=hub in members,
                                weight=counts.get(hub, 0))
        for key in members:
            if key != hub:
                graph.nodes[key] = Node(key, spelling[key].split("/", 1)[1], weight=counts[key])
                graph.edges.append(Edge(hub, key, "branch"))

    # Tags used together on a note, once each, never repeating a branch.
    linked = {frozenset((e.a, e.b)) for e in graph.edges}
    for keys in together:
        present = [k for k in keys if k in graph.nodes]
        for index, a in enumerate(present):
            for b in present[index + 1:]:
                pair = frozenset((a, b))
                if pair not in linked:
                    linked.add(pair)
                    graph.edges.append(Edge(*sorted(pair), "cotag"))
    return graph


def layout(graph: Graph, width: float, height: float) -> Graph:
    """Place a tag map radially, in place. Returns the same graph.

    Hubs sit on an ellipse — not a circle, so a wide window is used
    horizontally — and each hub's tags fan outward on an arc facing away from
    the centre. Each arm is as long as its own labels need to clear each other,
    and the ring is sized after the arms, so the outermost branch is not pushed
    off the edge and clamped on top of its neighbour.
    """
    hubs = sorted(graph.hubs, key=lambda n: n.id)
    if not hubs:
        return graph
    cx, cy = width / 2, height / 2
    usable_x = max(80.0, width / 2 - MARGIN_X)
    usable_y = max(70.0, height / 2 - MARGIN_Y)
    single = len(hubs) == 1

    branches = {hub.id: sorted(e.b for e in graph.edges if e.kind == "branch" and e.a == hub.id)
                for hub in hubs}
    arms = {hub_id: _branch_length(len(children), _fan(len(children), single),
                                   usable_x, usable_y, single)
            for hub_id, children in branches.items()}
    reach = max(arms.values(), default=MIN_BRANCH)
    ring_x = 0.0 if single else max(0.0, min(usable_x - reach, usable_x * 0.75))
    ring_y = 0.0 if single else max(0.0, min(usable_y - reach * 0.8, usable_y * 0.72))

    placed: dict[str, Node] = {}
    for index, hub in enumerate(hubs):
        angle = -math.pi / 2 + 2 * math.pi * index / len(hubs)
        hx = _clamp(cx + ring_x * math.cos(angle), MARGIN_X, width - MARGIN_X)
        hy = _clamp(cy + ring_y * math.sin(angle), MARGIN_Y, height - MARGIN_Y)
        placed[hub.id] = replace(hub, x=hx, y=hy, radius=16 if hub.real else 12)

        children = branches[hub.id]
        spread, arm = _fan(len(children), single), arms[hub.id]
        for index_in_fan, child in enumerate(children):
            turn = (angle if len(children) == 1
                    else angle - spread / 2 + spread * index_in_fan / (len(children) - 1))
            placed[child] = replace(
                graph.nodes[child],
                x=_clamp(hx + arm * math.cos(turn), MARGIN_X, width - MARGIN_X),
                y=_clamp(hy + arm * math.sin(turn), MARGIN_Y, height - MARGIN_Y),
                radius=11)
    graph.nodes.update(placed)
    return graph


def _fan(count: int, single_hub: bool) -> float:
    """How wide an arc a hub's tags spread across.

    A lone hub owns the canvas, so its tags ring it. A hub on the ring has
    neighbours, and past about 150 degrees a fan curls back into theirs.
    """
    if count <= 1:
        return 0.0
    if single_hub:
        return 2 * math.pi * (count - 1) / count
    return math.radians(min(150.0, 64.0 + 26.0 * (count - 1)))


def _branch_length(count: int, spread: float, usable_x: float, usable_y: float,
                   single_hub: bool) -> float:
    """How far out a hub's tags go so their labels clear each other.

    Neighbours sit `2 * arm * sin(step / 2)` apart, so the arm follows from the
    clearance. It is capped so the fan still lands on the canvas.
    """
    if count <= 1:
        return MIN_BRANCH
    step = spread / (count - 1)
    needed = LABEL_CLEARANCE / (2 * math.sin(step / 2))
    ceiling = min(usable_x, usable_y) * (0.82 if single_hub else 0.44)
    return max(MIN_BRANCH, min(needed, max(MIN_BRANCH, ceiling)))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value)) if high > low else (low + high) / 2


# -- the link graph ---------------------------------------------------------------------------


def link_graph(vault: Vault, folder: Path | None = None) -> Graph:
    """Notes, and the links between them. Unwritten targets are counted, not drawn."""
    notes = list(_notes(vault, folder))
    known = {note.rel for note in notes}
    graph = Graph("links")
    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()
    degree = dict.fromkeys(known, 0)
    for note in notes:
        for link in note.links:
            target = vault.resolve(link.target, note.path)
            if target is None:
                graph.unresolved += 1
                continue
            rel = vault.rel(target)
            if rel == note.rel or rel not in known or (note.rel, rel) in seen:
                continue
            seen.add((note.rel, rel))
            edges.append(Edge(note.rel, rel, "link"))
            degree[note.rel] += 1
            degree[rel] += 1

    kept = set(sorted(known, key=lambda rel: (-degree[rel], rel))[:MAX_NODES])
    graph.hidden = len(known) - len(kept)
    for note in sorted(notes, key=lambda n: n.rel):
        if note.rel in kept:
            graph.nodes[note.rel] = Node(note.rel, note.title, weight=degree[note.rel])
    graph.edges = [e for e in edges if e.a in kept and e.b in kept]
    return graph
