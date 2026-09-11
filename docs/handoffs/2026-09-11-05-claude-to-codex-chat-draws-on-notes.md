# The chat draws on the second brain

Claude → Codex, 2026-09-11. Follows
[04](2026-09-11-04-claude-to-codex-graph-view.md). It finishes two "still to do"
lines in [../PROJECT.md](../PROJECT.md): B4 (retrieval in the chat turn) and B6
(the project's personality in the conversation).

## What you can build on now

Before each turn, `Chat` now gathers passages from the sources the person has
granted: notes, the open project's documents, and past conversations. It also
adds the open project's personality. Both go with that turn only and are never
saved into the conversation. The additions are documented in
[../QML_BRIDGES.md](../QML_BRIDGES.md) under `Chat`:

- **`Chat.lastSources`**: what the last turn drew on, as maps of `source`
  (`notes`, `documents`, `conversations`) and `cite` (e.g.
  `Garden.md › Tomatoes`). Show these under the answer as its sources. The
  model is asked to cite them in the text too, using the same labels. When a
  turn used nothing, the list is empty; show nothing.
- **`Chat.lastContextNote`**: one sentence, e.g. "3 passages from notes,
  documents". It also carries the reason when looking failed. It suits a
  tooltip or a footnote better than the main view.
- **A new `stage`**: `Looking through your notes`, before the model starts.

`sourcesChanged` fires when a turn starts (clearing the list) and again when
its context is ready.

## What does not change

- With nothing granted, nothing is searched and the chat behaves exactly as
  before. There is no new setting. Granting `vault.read`, `docs.read` or
  `memory.read` on the permission screen is what switches each source on.
- The chat still does not call tools on the model's behalf, and nothing typed
  into it changes a file.

## For the person, not for you

`PROJECT.md` now carries a proposed design for **C1, the network chokepoint**.
It is written down but not built, because it ends the guarantee that nothing
in the application can connect. It waits for the person's go-ahead. Nothing on
your side depends on it yet.

## Not done yet

- Memory distilled per project (B6).
- As before, this handoff is not in the [index](README.md), because `README.md`
  has your uncommitted edits. Rows 07 to 11 are still to add.

## Tests

Full suite at the chat commit: 1556 passed, 2 skipped, 2 failed. The two
failures are the usual legacy Tk settings-geometry tests, which fail on this
960-px display at a clean checkout too. `verify_offline.py` passes.
