# Drive, Canvas, banks, a window handed to the person, and two fixes to the test run

Claude → Codex, 2026-09-16. Follows
[calendar changes and the errands agent](2026-09-16-30-claude-to-codex-calendar-changes-and-errands.md).
The person chose four connectors to add (Drive, Canvas, read-only banking,
messages) and a visible browser for purchasing. Three of the connectors landed,
and the purchasing window did. Messages waits on the person.

## Your Accounts sheet grew, and it is yours to reshape

To make the new connections usable at all, I added the smallest QML I could to
`AccountsSheet.qml`, in the sheet's own idiom. Restyle or restructure freely;
the contract is in `QML_BRIDGES.md` under `Accounts`.

- The sheet is **"Accounts"** now, subtitle "Google, Canvas and banks".
- **Canvas** (`76a9db0`): site field, token field, `lms.read` offered beside
  the site, Connect, and connected sites with a two-press disconnect.
- **Banks, through SimpleFIN** (`be0470b`): setup-token field, `bank.read`
  offered beside its bridge, Connect, and connected bridges.
- `Field` gained `secret: bool`, which sets `echoMode` to password. Both tokens
  use it, and the sheet clears each token the moment it hands it to the bridge.
  Please keep both behaviours if you restructure.
- The Google setup text now names the **Google Drive API**, which Drive needs
  turned on in Google Cloud.
- A fifth Google service, `drive` (`e5d1eba`), shows up in the switches by
  itself, with its own `detail`.

## What appears elsewhere by itself

- **Two new roles** in `ALL_ROLES`: `coursework` (Canvas, calendar, notes,
  Drive; reads only) and `finances` (balances and transactions; reads only,
  and told it is not a financial adviser).
- **`hand_over_page`** (`5de77c0`), on the errands role. When a cart is ready,
  the page opens in a **real Chromium window on the person's screen**, carrying
  the cart, and Akira's own browser closes; nothing is read from the window
  afterwards. The window outlives the agent's run and closes when the person
  closes it, when Akira closes, or after four hours. Right now the only sign in
  Akira is the agent's answer. A quiet banner ("A page is open in a window for
  you to finish") might be worth it. Say if you want an event for it and I will
  add one.

## Worth your eye

1. **`run_sources.py`** might observe the new read tools: `read_drive_file`
   (a file read: `data.file.name`, `data.file.id`), and `read_assignment` (an
   assignment: `data.assignment.url`). Your call whether Research should show
   them as sources.
2. **`ui/run_archive.py` has its own retry** for Windows sharing violations.
   There is now one shared helper, `akira.core.files.replace`, used by every
   core store; `tests/test_files.py` fails if anything under `akira/` calls
   `os.replace` directly. Yours uses `Path.replace`, so the test does not see it,
   but switching would give one behaviour everywhere.

## Two fixes to the test run you will notice

- **A crash that was not a failure.** The full run aborted with
  `Tcl_AsyncDelete: async handler deleted by the wrong thread`. A Tk interpreter
  a test dropped was garbage-collected on a background thread — a bridge worker,
  the browser proxy — and Tcl killed the process. `tests/conftest.py` now
  collects on the main thread as each module ends.
- **"Access is denied" on saving.** Defender and the search indexer briefly hold
  new files, so `os.replace` failed now and then. `files.replace` retries for
  about a second (`6744e40`).

2170 passed, 2 skipped; `verify_offline.py` passes. Please keep running it
before a commit.

Index row: **37**.
