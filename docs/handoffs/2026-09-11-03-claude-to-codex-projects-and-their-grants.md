# Projects, and grants that belong to one (B6, part 1)

Claude → Codex, 2026-09-11. Follows
[02](2026-09-11-02-claude-to-codex-memory-review.md) and covers the first half
of work order item **B6** in [../PROJECT.md](../PROJECT.md).

## What you can build on now

**A new context property, `Projects`** (`ProjectsBridge`), documented in
[../QML_BRIDGES.md](../QML_BRIDGES.md). It has two jobs.

**1. A project switcher.** `projects` lists them, and `currentName` says which
one is open (`""` for none). `openProject(id)` switches, and `openProject("")`
leaves projects. `create(name, folder)` makes a project and opens it. `rename`,
`setFolder`, `setPersonality` and `remove` do what they say. **`remove` never
touches notes**: it forgets the project and its grants, and the confirmation
should say so, because "delete project" reads as "delete my files".

**2. A second place a grant can live.** Until now every grant applied
everywhere. Now a grant can belong to one project: `Projects.grant(id, scopes)`
stores it with the open project, and it applies only while that project is
open. The permission screen needs to make the choice visible:

- When granting while a project is open, offer **Only in <project>** first, and
  **Everywhere** second. The project grant is the narrower one, and the
  narrower answer should be the easy one.
- Show the open project's grants (`Projects.grants`) as their own section, apart
  from the global ones (`Permissions.grants`).
- Both refuse a scoped capability given no scope, with a reason. Show it.

## What uses which grants

- **Agents and teams started from the interface**: the global grants plus the
  open project's.
- **Scheduled jobs**: the global grants only. That is deliberate. A nightly job
  must not gain or lose a permission because of which project was on screen.
  So a job that needs a folder needs it granted everywhere. If the schedule
  screen offers to add a missing grant, it should use `Permissions.grant`.
- **Memory**: global.

## Please confirm with the person

I took the reading of the spec that a project's grants **add to** the global
ones while it is open. The other possible reading is that a project **limits**
what may be done inside it. Adding is what "granting an agent a folder for one
project does not grant it everywhere" asks for, and it never widens anything
outside the project. Limiting is not built. If it is wanted, it would go on top
of this, not replace it.

## Not done yet

- The **graph view**, from the legacy `knowledge_graph.py`. The plan is links
  between notes, taken from the vault, served by a bridge. No bridge exists yet.
- Memory per project, and `personality` applied in the conversation. Both are
  stored and neither is used yet.
- `folder` is recorded, but agents started in a project do not default to it
  yet.
- As before, this handoff is not in the [index](README.md), because
  `README.md` has your uncommitted edits. Rows 07, 08 and 09 are still to add.

## Tests

Full suite at the B6 commit: 1537 passed, 2 skipped, 2 failed. The two failures
are the usual legacy Tk settings-geometry tests, which fail on this 960-px
display at a clean checkout too. `verify_offline.py` passes.
