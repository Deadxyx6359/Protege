# Handoffs

These are point-in-time notes between the two agents working on Protégé:
Claude on the backend, Codex on the frontend. Each one records what changed in
a session, what the other side can now build on, and what to watch out for.

They are **not** kept up to date after they are written. The living documents
are:

- [../PROJECT.md](../PROJECT.md) — what is being built, and the work order, with stable IDs like `B1`
- [../QML_BRIDGES.md](../QML_BRIDGES.md) — what QML can reach right now

## Naming

`YYYY-MM-DD-NN-<from>-to-<to>-<topic>.md`

- **Date** is the day it was written. **NN** orders the handoffs written that
  same day, in either direction, starting from `01`.
- **from** and **to** are `claude` or `codex`.
- **topic** is two to five kebab-case words naming the work, not the session.

Sorting by name sorts by time. The newest handoff addressed *to* you is the one
to read first.

## Writing one

- Lead with what the reader can do now that they could not before.
- Name files and APIs exactly, and link to the living references rather than
  copying them in. Copies go stale.
- Say what was *not* done, and anything known to be broken or odd.
- State the test result you actually saw, not the one you expect.
- Never edit an old handoff to bring it up to date. Write a new one.

## Index

| # | Date | Direction | Topic | Status |
|---|---|---|---|---|
| 01 | 2026-09-10 | Codex → Claude | [Scene rebuild](2026-09-10-01-codex-to-claude-scene-rebuild.md) | Historical |
| 02 | 2026-09-10 | Claude → Codex | [Backend spine](2026-09-10-02-claude-to-codex-backend-spine.md) | Superseded by 04 |
| 03 | 2026-09-10 | Codex → Claude | [Research workspace and scene details](2026-09-10-03-codex-to-claude-research-workspace.md) | **Latest to Claude** |
| 04 | 2026-09-10 | Claude → Codex | [Section A complete](2026-09-10-04-claude-to-codex-section-a-complete.md) | **Latest to Codex** |

Add a row when you add a handoff, and move the **Latest** marker.
