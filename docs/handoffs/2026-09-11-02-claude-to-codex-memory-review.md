# Memory: a review screen for notes distilled from conversations (B5)

Claude → Codex, 2026-09-11. Follows
[01](2026-09-11-01-claude-to-codex-second-brain-and-retrieval.md) and covers
work order item **B5** in [../PROJECT.md](../PROJECT.md).

## What you can build on now

**A new context property, `Memory`** (`MemoryBridge`). It is documented in
[../QML_BRIDGES.md](../QML_BRIDGES.md#memory--notes-distilled-from-conversations).
It needs a screen with three parts:

1. **Setup.** A vault picker (`setVault(path)`) and the two grants the job needs:
   `memory.read` and `vault.read` for that vault. Without both, every run
   fails, and the run's summary in `Schedule.history` names what is missing. The
   natural place to offer the grants is beside the picker, with
   `Permissions.grant(...)` after the person agrees.
2. **The queue.** `pending`, oldest first. Each proposal is either a new note
   (`addsTo` false, `preview` is the whole note) or an addition to an existing
   one (`addsTo` true, `preview` is a unified diff). Show `preview` verbatim,
   with `sources`, the titles of the conversations it came from.
3. **Accept / reject** on each proposal. Both return `""` or a reason written
   for the person. Show it.

**Nothing reaches the vault until a person accepts.** That is the whole point
of the screen, so do not add "accept all". A model wrote these, and each needs
reading. `accept` can also refuse after the fact: if the note changed since the
proposal was made, nothing is written, the proposal is re-based on the note as
it is now, and `pendingChanged` fires. Show the reason, then the new preview.

**`distilNow()`** reads recent conversations now instead of at 03:30. It starts
a worker, `busy` goes true, and `lastRun` then says what was found, e.g.
"2 notes proposed from 3 conversations; waiting for review."

**A badge is worth it.** `pendingCount` is small and cheap to read, and
proposals that nobody sees are proposals nobody reviews.

## A correction to 01

01 said the new `memory.read` row "belongs with *Read your notes* and *Read
documents*". That was wrong. The catalogue groups rows by `domain`, the part
of the ID before the dot, so `memory.read` forms its own `memory` group. In
catalogue order that group sits between `vault` and `docs`. Group by `domain`
as [../QML_BRIDGES.md](../QML_BRIDGES.md) says, and it lands in the right
place.

## What changed underneath

- `protege/core/brain/distil.py`: the nightly job. It sends only the exchanges
  since a conversation was last read, drops proposals that say nothing new,
  and merges proposals for the same note across conversations. It writes
  proposals to the config folder, never to the vault.
- `protege/ui/bridge/memory.py`: the bridge, wired in `protege/ui/shell.py`.
- The job shows in `Schedule.jobs` as **Memory**. Choosing another vault moves it.

## Not done yet

- There is no screen for it. That is yours.
- Retention for the conversations themselves: they are kept until deleted, as
  before.

## Tests

Full suite at the B5 commit: 1522 passed, 2 skipped, 2 failed. The failures are
the same two legacy Tk settings-geometry tests as before: they need an
847-px-tall window on this 960-px display, and fail at a clean checkout too.
`verify_offline.py` passes.
