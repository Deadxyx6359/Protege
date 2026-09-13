# Handoffs

These are point-in-time notes between the two agents working on Akira:
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
| 03 | 2026-09-10 | Codex → Claude | [Research workspace and scene details](2026-09-10-03-codex-to-claude-research-workspace.md) | Historical |
| 04 | 2026-09-10 | Claude → Codex | [Section A complete](2026-09-10-04-claude-to-codex-section-a-complete.md) | Historical |
| 05 | 2026-09-10 | Claude → Codex | [Agents and one generation at a time](2026-09-10-05-claude-to-codex-agents-and-one-model-at-a-time.md) | Historical |
| 06 | 2026-09-10 | Codex → Claude | [Akira branding concepts](2026-09-10-06-codex-to-claude-akira-branding-concepts.md) | Historical; local exploration |
| 07 | 2026-09-11 | Claude → Codex | [Second brain and retrieval](2026-09-11-01-claude-to-codex-second-brain-and-retrieval.md) | Historical |
| 08 | 2026-09-11 | Claude → Codex | [Memory review](2026-09-11-02-claude-to-codex-memory-review.md) | Historical |
| 09 | 2026-09-11 | Claude → Codex | [Projects and grants](2026-09-11-03-claude-to-codex-projects-and-their-grants.md) | Historical |
| 10 | 2026-09-11 | Claude → Codex | [Graph view](2026-09-11-04-claude-to-codex-graph-view.md) | Historical |
| 11 | 2026-09-11 | Claude → Codex | [Chat draws on notes](2026-09-11-05-claude-to-codex-chat-draws-on-notes.md) | Historical |
| 12 | 2026-09-11 | Claude → Codex | [Phase B complete](2026-09-11-06-claude-to-codex-phase-b-complete.md) | Historical |
| 13 | 2026-09-11 | Claude → Codex | [Watched folders and notices](2026-09-11-07-claude-to-codex-watched-folders-and-notices.md) | Historical |
| 14 | 2026-09-11 | Claude → Codex | [Place and hemisphere](2026-09-11-08-claude-to-codex-place-and-hemisphere.md) | Historical |
| 15 | 2026-09-11 | Claude → Codex | [Network door and logo](2026-09-11-09-claude-to-codex-network-door-and-logo.md) | Historical |
| 16 | 2026-09-11 | Claude → Codex | [The interface's own door](2026-09-11-10-claude-to-codex-the-interfaces-own-door.md) | Historical |
| 17 | 2026-09-11 | Claude → Codex | [Page and feed watches](2026-09-11-11-claude-to-codex-page-and-feed-watches.md) | Historical |
| 18 | 2026-09-11 | Claude → Codex | [Weather](2026-09-11-12-claude-to-codex-the-weather.md) | Historical |
| 19 | 2026-09-11 | Claude → Codex | [UI while Codex was away](2026-09-11-13-claude-to-codex-ui-while-you-were-away.md) | Historical |
| 20 | 2026-09-11 | Claude → Codex | [The missing views](2026-09-11-14-claude-to-codex-the-views-that-were-missing.md) | Historical |
| 21 | 2026-09-12 | Claude → Codex | [Google accounts](2026-09-12-15-claude-to-codex-google-accounts.md) | Historical |
| 22 | 2026-09-12 | Claude → Codex | [Welcome back / inbox and sending](2026-09-12-16-claude-to-codex-welcome-back.md) | **Latest to Codex** |
| 23 | 2026-09-12 | Codex → Claude | [Brand integration and UI audit](2026-09-12-17-codex-to-claude-brand-and-ui-audit.md) | Historical |
| 24 | 2026-09-12 | Codex → Claude | [Working sidebar search](2026-09-12-18-codex-to-claude-sidebar-search.md) | Historical |
| 25 | 2026-09-12 | Codex → Claude | [Documents seam coordination](2026-09-12-19-codex-to-claude-documents-coordination.md) | Historical |
| 26 | 2026-09-12 | Codex → Claude | [Documents workspace](2026-09-12-20-codex-to-claude-documents-workspace.md) | **Latest to Claude** |

Add a row when you add a handoff, and move the **Latest** marker.
