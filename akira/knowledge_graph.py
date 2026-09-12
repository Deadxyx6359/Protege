"""The knowledge graph: topics arranged as a skill tree.

Pure data and geometry -- no Tk in this module, so the clustering and layout
are unit-testable. `ui/knowledge_web.py` draws the result.

**Where the hierarchy comes from.** Topic ids are flat strings, but the naming
convention users actually fall into (`python_basics`, `python_loops`,
`chemistry_organic`) carries structure: the first underscore-segment names the
domain. So the graph groups topics by first segment -- each distinct segment
becomes a *major* hub, and topics sharing it branch off that hub. A topic with
no underscore is its own hub. A hub may be purely synthetic ("python" as a hub
even if no topic is literally named `python`); if a topic with the bare hub
name exists, it fuses with the hub rather than orbiting itself.

This is a heuristic and it is honest about being one: it invents no relations
beyond the naming, and cross-links come only from co-tagging -- two topics that
appear together in one note's frontmatter are related because the user said so
by tagging them together.

**Layout.** Deterministic radial: hubs on a ring around the center, each hub's
subtopics fanned on a short arc facing away from the center. Deterministic
matters -- a force-directed layout gives a different picture every open, and a
map that will not hold still is useless for building a mental model of what the
model knows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .lock.tripwires import TripwireSet
from .schemas import Manifest
from .vault import VaultScan


@dataclass(frozen=True)
class TopicNode:
    topic: str            # full topic id, or the hub name for synthetic hubs
    label: str            # short display form (subtopics drop the hub prefix)
    is_hub: bool
    is_real: bool         # False only for synthetic hubs -- not a taggable topic
    unlocked: bool = False
    note_count: int = 0
    has_tripwires: bool = False
    x: float = 0.0
    y: float = 0.0
    radius: float = 0.0


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    kind: str  # "branch" (hub->subtopic) | "cotag" (tagged together on a note)


@dataclass
class KnowledgeGraph:
    nodes: dict[str, TopicNode] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    @property
    def hubs(self) -> list[TopicNode]:
        return [n for n in self.nodes.values() if n.is_hub]

    @property
    def unlocked_count(self) -> int:
        return sum(1 for n in self.nodes.values() if n.is_real and n.unlocked)

    @property
    def real_count(self) -> int:
        return sum(1 for n in self.nodes.values() if n.is_real)


def hub_of(topic: str) -> str:
    return topic.split("_", 1)[0]


def build_graph(
    scan: VaultScan,
    manifest: Manifest,
    tripwires: TripwireSet | None = None,
) -> KnowledgeGraph:
    """Collect every topic the vault or manifest knows about and cluster it.

    Sources, union of all three: note frontmatter (including notes currently
    invisible -- the whole point of the map is seeing locked ground), the
    unlocked list itself (a topic can be unlocked with its notes since
    deleted), and tripwire files (a topic being guarded is worth showing even
    before any note exists).
    """
    tripwires = tripwires or TripwireSet()

    note_counts: dict[str, int] = {}
    for note in scan.notes:
        for topic in note.topics:
            note_counts[topic] = note_counts.get(topic, 0) + 1

    topics: set[str] = set(note_counts)
    topics.update(manifest.unlocked_topics)
    topics.update(tripwires.by_topic)

    graph = KnowledgeGraph()
    if not topics:
        return graph

    clusters: dict[str, list[str]] = {}
    for topic in sorted(topics):
        clusters.setdefault(hub_of(topic), []).append(topic)

    for hub, members in sorted(clusters.items()):
        # A topic literally named like its hub fuses with the hub node instead
        # of orbiting itself.
        hub_is_real = hub in members
        graph.nodes[hub] = TopicNode(
            topic=hub,
            label=hub,
            is_hub=True,
            is_real=hub_is_real,
            unlocked=hub_is_real and manifest.is_unlocked(hub),
            note_count=note_counts.get(hub, 0),
            has_tripwires=hub in tripwires.by_topic,
        )
        for topic in members:
            if topic == hub:
                continue
            graph.nodes[topic] = TopicNode(
                topic=topic,
                label=topic[len(hub) + 1:] or topic,
                is_hub=False,
                is_real=True,
                unlocked=manifest.is_unlocked(topic),
                note_count=note_counts.get(topic, 0),
                has_tripwires=topic in tripwires.by_topic,
            )
            graph.edges.append(Edge(hub, topic, "branch"))

    # Cross-links from co-tagging. Deduplicated, and never duplicating a branch
    # edge -- a subtopic co-tagged with its own hub adds nothing to the map.
    branch_pairs = {frozenset((e.a, e.b)) for e in graph.edges}
    seen: set[frozenset[str]] = set()
    for note in scan.notes:
        note_topics = [t for t in note.topics if t in graph.nodes]
        for i, a in enumerate(note_topics):
            for b in note_topics[i + 1:]:
                pair = frozenset((a, b))
                if len(pair) < 2 or pair in seen or pair in branch_pairs:
                    continue
                seen.add(pair)
                graph.edges.append(Edge(a, b, "cotag"))

    return graph


# Horizontal room a topic label needs before it runs into its neighbour, and
# the vertical room it needs below its own node. Both are measured from the
# rendered labels rather than guessed: a topic name is short but not narrow.
LABEL_CLEARANCE = 88.0
MARGIN_X = 74.0
MARGIN_Y = 58.0
# A branch shorter than this reads as a blob rather than a branch, however few
# children there are.
MIN_BRANCH = 96.0


def layout(graph: KnowledgeGraph, width: int, height: int) -> KnowledgeGraph:
    """Assign radial positions in place (returns the same graph for chaining).

    Hubs sit on a ring; each hub's subtopics fan outward on an arc centred on
    the hub's own bearing from the centre, so branches grow away from the
    middle like, well, branches.

    Two things the first version got wrong, both visible the moment the map had
    real data in it. It sized everything from `min(width, height)`, so on a
    wide window the whole graph huddled into a circle the height of the canvas
    and left the sides empty. And it used a fixed fan angle and arm length
    regardless of how many children a hub had, so a domain with five subtopics
    stacked their labels on top of each other while a domain with one left a
    gap. Rings are elliptical now, and each hub's arm is derived from the
    clearance its own labels need.
    """
    cx, cy = width / 2, height / 2
    hubs = sorted(graph.hubs, key=lambda n: n.topic)
    if not hubs:
        return graph

    # Budget against the usable half-extent in each axis independently, so a
    # wide window actually gets used horizontally.
    usable_x = max(80.0, width / 2 - MARGIN_X)
    usable_y = max(70.0, height / 2 - MARGIN_Y)
    single = len(hubs) == 1

    # Measure the branches before placing the hubs. The hub ring wants to be as
    # wide as the canvas allows, but "as wide as it allows" depends on how far
    # the outermost branch reaches -- push the hubs out first and the branches
    # get clamped against the edge, which stacks the very labels the arm length
    # was calculated to separate.
    branches = {
        hub.topic: sorted(
            e.b for e in graph.edges if e.kind == "branch" and e.a == hub.topic
        )
        for hub in hubs
    }
    arms = {
        topic: _branch_length(len(children), _fan(len(children), single),
                              usable_x, usable_y, single)
        for topic, children in branches.items()
    }
    reach = max(arms.values(), default=MIN_BRANCH)
    ring_x = 0.0 if single else min(usable_x - reach, usable_x * 0.75)
    ring_y = 0.0 if single else min(usable_y - reach * 0.8, usable_y * 0.72)
    ring_x, ring_y = max(0.0, ring_x), max(0.0, ring_y)

    updated: dict[str, TopicNode] = {}
    for index, hub in enumerate(hubs):
        angle = -math.pi / 2 + (2 * math.pi * index / len(hubs))
        hx = _clamp(cx + ring_x * math.cos(angle), MARGIN_X, width - MARGIN_X)
        hy = _clamp(cy + ring_y * math.sin(angle), MARGIN_Y, height - MARGIN_Y)
        updated[hub.topic] = _at(hub, hx, hy, radius=16 if hub.is_real else 12)

        children = branches[hub.topic]
        if not children:
            continue

        spread = _fan(len(children), single)
        arm = arms[hub.topic]
        for child_index, child_topic in enumerate(children):
            if len(children) == 1:
                child_angle = angle
            else:
                child_angle = angle - spread / 2 + spread * child_index / (len(children) - 1)
            child = graph.nodes[child_topic]
            updated[child_topic] = _at(
                child,
                _clamp(hx + arm * math.cos(child_angle), MARGIN_X, width - MARGIN_X),
                _clamp(hy + arm * math.sin(child_angle), MARGIN_Y, height - MARGIN_Y),
                radius=11,
            )

    graph.nodes.update(updated)
    return graph


def _fan(count: int, single_hub: bool) -> float:
    """How wide an arc this hub's children spread across.

    A lone hub owns the whole canvas, so its children ring it completely. A hub
    on the ring has neighbours, and a fan past about 150 degrees starts curling
    its children back toward the centre and into someone else's branches.
    """
    if count <= 1:
        return 0.0
    if single_hub:
        return 2 * math.pi * (count - 1) / count
    return math.radians(min(150.0, 64.0 + 26.0 * (count - 1)))


def _branch_length(count: int, spread: float, usable_x: float, usable_y: float,
                   single_hub: bool) -> float:
    """How far out to push children so their labels clear each other.

    Neighbouring children sit `2 * arm * sin(step / 2)` apart, so the arm
    follows from the clearance rather than the other way round. Capped so the
    fan still lands on the canvas -- `_clamp` will catch anything that escapes,
    but a clamped node is a node sitting on top of its neighbour, which is the
    overlap this is meant to prevent.
    """
    if count <= 1:
        return MIN_BRANCH
    step = spread / (count - 1)
    needed = LABEL_CLEARANCE / (2 * math.sin(step / 2))
    ceiling = min(usable_x, usable_y) * (0.82 if single_hub else 0.44)
    return max(MIN_BRANCH, min(needed, max(MIN_BRANCH, ceiling)))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value)) if high > low else (low + high) / 2


def _at(node: TopicNode, x: float, y: float, *, radius: float) -> TopicNode:
    from dataclasses import replace

    return replace(node, x=x, y=y, radius=radius)


def summarize(graph: KnowledgeGraph) -> str:
    if not graph.nodes:
        return (
            "No topics yet. Tag notes with topics: [ ... ] frontmatter, or unlock a topic, "
            "and the web grows from there."
        )
    return (
        f"{graph.real_count} topic(s) across {len(graph.hubs)} domain(s) -- "
        f"{graph.unlocked_count} unlocked"
    )
