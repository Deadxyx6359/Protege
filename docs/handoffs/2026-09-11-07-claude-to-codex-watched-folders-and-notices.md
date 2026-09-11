# Watched folders, and notices (C6, local half)

Claude → Codex, 2026-09-11. Follows
[06](2026-09-11-06-claude-to-codex-phase-b-complete.md). It covers the half of
work order item **C6** in [../PROJECT.md](../PROJECT.md) that needs no network.

## What you can build on now

**A new context property, `Monitor`** (`MonitorBridge`), documented in
[../QML_BRIDGES.md](../QML_BRIDGES.md). It does two things.

**1. Watched folders.** `Monitor.addWatch(folder, patterns)` watches a folder,
optionally only files like `*.pdf`. It needs `files.read` there; without it,
it returns **Not permitted** with the reason. `Monitor.watches` lists them. A
watch whose permission is revoked, or whose folder disappears, fills `paused`
with the reason and resumes by itself when the cause goes away. Show the reason
next to the watch.

A watch on its own shows nothing. It turns changes into scheduler events, and
something happens when a **job** waits for them. The usual pairing is a watch
plus a `notify` job. `QML_BRIDGES.md` has the exact `Schedule.addJob` call.
Match the event on the watch's `id`, not its folder. A screen for this could
be one form: "When files like ___ arrive in ___, [tell me | have the research
team look at them]". It creates the watch, then the job, and offers the
grants each needs (`files.read` for the folder, plus `notify.send` or whatever
the agent needs).

**2. Notices.** Jobs with the new `notify` action put up notices.
`Monitor.noticed(title, text)` fires once per notice, which is the moment to
show a toast or a tray message. `Monitor.notices` keeps the last 50, newest
first, for a list. `notify.send` must be in the job's grants, and granted on the
permission screen, or the notice is refused and the run's summary says so.

## Worth knowing

- A file is announced only once it has settled, which takes two looks, about a
  minute apart. That is deliberate: a job never wakes to half a download.
- Watches use the **global** grants, like scheduled jobs, never the open
  project's.
- `Schedule.addJob` now also accepts `action: "notify"`. Its docstring and the
  `addJob` notes in `QML_BRIDGES.md` say what it takes. It refuses
  `distil_memory`, which sets itself up through `Memory.setVault`.

## Not done yet

- Watching pages, inboxes and feeds, which waits for C1 (network) and C5
  (connectors). C1 is still waiting for the person's go-ahead.
- Index: add row **13** for this handoff when you commit `README.md`, after the
  rows 07–12 listed in 06.

## Tests

Full suite at the C6 commit: 1577 passed, 2 skipped, 2 failed. The two failures
are the usual legacy Tk settings-geometry tests, which fail on this 960-px
display at a clean checkout too. `verify_offline.py` passes.
