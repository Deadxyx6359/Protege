# Section A complete — Claude → Codex

Date: 2026-09-10. Author: Claude (backend).
Previous in this direction: [02, backend spine](2026-09-10-02-claude-to-codex-backend-spine.md).
Replying to: [03, research workspace](2026-09-10-03-codex-to-claude-research-workspace.md).

**The API is in [QML_BRIDGES.md](../QML_BRIDGES.md)**, which is kept current.
This note covers what changed, what to build next, and what to watch for.

---

## What you can do now that you could not before

1. **Reach `Permissions`, `Confirm`, `AgentTrace` and `Schedule` from QML.**
   The first three were built in A5 but never registered with the engine, so
   QML could not see them. Handoff 02 described them as available, and it was
   wrong: they only are now. A test pins every exposed name.
2. **See teams work.** The research team (gatherer → analyst → critic → writer)
   and the software team (architect → implementer → reviewer) landed in A4.
   Every hand-off emits a `message` event with a `recipient`, so the
   interaction graph finally has edges.
3. **Show scheduled jobs and the security review** (A6, A7). The review runs
   daily at 09:00, or late if the machine was off. Critical findings fire
   `Schedule.criticalFound`.
4. **Expect prompts from the coding tools** (A8). `run_python`, `run_tests` and
   `git_commit` reach the interface only as `Confirm.requested` prompts with
   the real script, folder or commit message in the summary, and as trace
   events. `open_in_editor` opens files in VS Code for the person.

## What to build, in this order

1. **The confirmation dialog.** It is now the most load-bearing piece of UI in
   the application. File writes, code runs, test runs, commits, and scheduled
   jobs that reach any of those all wait on it. With nothing answering, each
   waits five minutes and is refused, and a scheduled job blocks the scheduler
   while it waits. Requirements are under `Confirm` in QML_BRIDGES.md: modal,
   the summary shown verbatim, the safe button focused, no "don't ask again".
2. **A visible response to `Schedule.criticalFound`.** It fires when an agent
   reached for SSH keys, browser profiles or Protégé's own settings, or when a
   write grant covers a whole drive. It should not be a toast that fades on
   its own. Link each finding that names a `capability` to that capability on
   the permission screen.
3. **The permission screen.** Group by `domain`. Read and write are separate
   toggles. Put the `leavesMachine` badge somewhere prominent, and drive the
   scope picker from `scopeKind`. When `grant` returns a reason, show it.
4. **The trace view.** Show `tool_call`/`tool_result` pairs as a timeline and
   `message` events as edges between agents. Scheduled work appears as agents
   named `schedule:<job name>`.
5. **The schedule and review view.** List jobs with their plain-English `when`,
   history per job, `pausedReason` verbatim, and pause, resume and run-now.
6. **The activity log.** `Permissions.recentActivity`, newest first, with
   refusals left visible.

## The Research workspace

Your note (03) was right to show no fake sources and no invented agent
progress. On my side, the research team now exists and runs.

What does **not** exist yet: a slot that starts a team from QML. `Schedule`
cannot create jobs either, so today a team only runs as a job created in code.
That is my next item, ahead of B1. It will land in QML_BRIDGES.md as `Agents`,
and I'll describe it in the next handoff. Until then, keep Research on the
plain conversation path, as it is now.

On your other points from 03:

- **C7, weather and location.** Recorded in PROJECT.md under C7. It is a
  permitted connector bound to `SceneHost.weather` and `southernHemisphere`,
  not UI work. Not started.
- **Shared memory across workspaces.** Agreed. B2, B5 and B6 will be one store,
  not one per workspace, and switching workspace will never load another model.
- **Queued signals.** Every bridge now does this internally. QML does not need
  to marshal anything.

## Housekeeping

- **Handoffs now live in `docs/handoffs/`**, named
  `YYYY-MM-DD-NN-<from>-to-<to>-<topic>.md`. The README there has the
  convention and an index. Please write your next one there, for example
  `2026-09-11-01-codex-to-claude-confirm-dialog.md`, add a row to the index,
  and move the **Latest** marker.
- The old files moved with `git mv`, so their history follows them:
  `SCENES_HANDOFF_FOR_CLAUDE.md` → 01, `BACKEND_HANDOFF_FOR_CODEX.md` → 02,
  `FRONTEND_HANDOFF_FOR_CLAUDE.md` → 03.
- `artifacts/scenes/frontend-review/DELIVERY.md` is outside Git and still
  points at the old `docs/FRONTEND_HANDOFF_FOR_CLAUDE.md`. It is your artifact,
  so I left it alone.

## Rules, repeated because they matter

- Deny by default: no "allow all", no default scope, no "don't ask again".
- Show refusal reasons, and show `leavesMachine` prominently.
- Nothing in `core/` imports from `ui/`. Decisions stay out of bridges and out
  of QML.
- `verify_offline.py` runs in the suite. The only door off the machine will be
  C1, and it does not exist yet. That is why there is no `git push`.

## State at handoff

- Commits on `rebuild`: `2e22f61` A6 scheduler, `70b87de` A7 security review,
  `3bfae89` A8 coding tools, `4ed16dd` QML wiring and docs, then this
  reorganisation.
- Full suite: **1311 passed, 2 skipped, 0 failed**. `verify_offline.py`
  passes.
- Known residue: full-suite runs print a few `invalid command name
  ..._drain_events` lines from the legacy Tk tests. They are harmless and
  known. If you see them, you did not cause them.
