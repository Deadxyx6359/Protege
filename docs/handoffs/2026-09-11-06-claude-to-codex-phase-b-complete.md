# Phase B complete, and where the backend stands

Claude → Codex, 2026-09-11. Follows
[05](2026-09-11-05-claude-to-codex-chat-draws-on-notes.md). It closes work order
item **B6** in [../PROJECT.md](../PROJECT.md), and with it Phase B, the second
brain. Read this one first. 01–05 carry the detail.

## One small bridge change

- **`Memory.pending` rows now carry `project`**: the project the source
  conversations were held in, or `""`. Worth showing beside each proposal,
  e.g. "From a conversation in Garden".
- Nothing to build for the rest. Chat conversations are now stamped with the
  project open when they begin, with no API change. What they teach is then
  proposed under `Memory/<project>/`.

## What the interface can reach now, all in [../QML_BRIDGES.md](../QML_BRIDGES.md)

| Property | For | Handoff |
|---|---|---|
| `Memory` | Reviewing notes distilled from conversations | 02 |
| `Projects` | A project switcher, and grants that belong to one project | 03 |
| `Graph` | The tag map and link graph | 04 |
| `Chat.lastSources` | What an answer drew on | 05 |
| `Permissions` | One new row, `memory.read` | 01, corrected in 02 |

Screens these want, roughly in order of how much they unlock:

1. The **Memory review** screen. Proposals pile up unseen without it.
2. **Sources under chat answers**, from `Chat.lastSources`.
3. The **project switcher**, and "Everywhere" or "Only in <project>" when
   granting.
4. The **graph view**.

## Where the backend stands

- **Phase B, the second brain, is done:** documents, the vault, the index,
  retrieval, memory, and projects.
- **C1, the network chokepoint, is designed but not built.** The design is
  under C1 in `PROJECT.md`. It ends the guarantee that nothing can connect, so
  it waits for the person's go-ahead. Everything else in Phase C is a client of
  C1 and waits with it.
- Until then, the backend can take work that needs no network, if the person
  wants it: skills (the legacy `skills/` onto the new spine), screen capture
  (C4, `screen.capture`), or the local half of voice (D1/D2). The work order is
  theirs to change.

## Housekeeping

- **The handoff index still lacks rows 07 to 12.** `README.md` has had your
  uncommitted edits all day, and I do not commit other people's in-flight files.
  When you commit yours, please add:

  | # | Date | Direction | Topic |
  |---|---|---|---|
  | 07 | 2026-09-11 | Claude → Codex | [Documents, the vault, the index and retrieval](2026-09-11-01-claude-to-codex-second-brain-and-retrieval.md) |
  | 08 | 2026-09-11 | Claude → Codex | [Memory review](2026-09-11-02-claude-to-codex-memory-review.md) |
  | 09 | 2026-09-11 | Claude → Codex | [Projects and their grants](2026-09-11-03-claude-to-codex-projects-and-their-grants.md) |
  | 10 | 2026-09-11 | Claude → Codex | [The graph view](2026-09-11-04-claude-to-codex-graph-view.md) |
  | 11 | 2026-09-11 | Claude → Codex | [The chat draws on notes](2026-09-11-05-claude-to-codex-chat-draws-on-notes.md) |
  | 12 | 2026-09-11 | Claude → Codex | [Phase B complete](2026-09-11-06-claude-to-codex-phase-b-complete.md), **latest to Codex** |

  The `#` column in the index runs on from 06. The files themselves are
  numbered within their day, 01 to 06, as the README's naming rule says.

## Tests

Full suite at the B6 commit: 1563 passed, 2 skipped, 2 failed. The two failures
are the usual legacy Tk settings-geometry tests, which fail on this 960-px
display at a clean checkout too. `verify_offline.py` passes.
