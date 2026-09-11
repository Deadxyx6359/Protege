# The graph: a tag map and a link graph (B6, part 2)

Claude → Codex, 2026-09-11. Follows
[03](2026-09-11-03-claude-to-codex-projects-and-their-grants.md) and covers the
second half of work order item **B6** in [../PROJECT.md](../PROJECT.md).

## What you can build on now

**A new context property, `Graph`** (`GraphBridge`), documented in
[../QML_BRIDGES.md](../QML_BRIDGES.md). It replaces the legacy Tk "knowledge
web" (`protege/ui/knowledge_web.py` drew the same geometry, if you want a
reference for how it looked).

`Graph.build(folder, width, height)` reads the notes under a folder off the UI
thread. `busy` goes true, then `builtChanged` fires and two maps are ready:

- **`tags`, the tag map, already laid out** for a canvas of that size. Draw each
  node at `x`, `y` with `radius`. A `branch` edge runs from a hub to a tag under
  it, and a `cotag` edge joins two tags used on one note. The second kind is
  lighter, a relation the person made, not a hierarchy. A hub with `real` false
  was never tagged directly, so draw it as a group, not a tag.
- **`links`, the link graph, not laid out.** Nodes are notes (`id` is the path in
  the vault, `label` the title) and edges are links between them. Placing them
  is yours. If a force layout is used, seed it, so the picture does not change
  every time it opens.

Show `summary` in both. When the map is empty it tells the person how to start.

**The tag map holds still on purpose.** The same notes on the same canvas always
come out in the same place. Rebuild on resize (debounced) rather than animating
nodes about. A map that moves cannot be learned.

## Which folder

Whatever the screen is about: the open project's `folder` (from
`Projects.projects`), the vault memory is kept in (`Memory.vault`), or one the
person picks. It needs `vault.read` there, either everywhere or in the open
project. Without it `build` returns **Not permitted** with the reason. Show it,
and offer the grant as the other screens do.

## Not done yet

- The link graph has no layout from the backend.
- This handoff is not in the [index](README.md) either, because `README.md` has
  your uncommitted edits. Rows 07 to 10 are still to add.

## Tests

Full suite at the graph commit: 1548 passed, 2 skipped, 2 failed. The two
failures are the usual legacy Tk settings-geometry tests, which fail on this
960-px display at a clean checkout too. `verify_offline.py` passes.
