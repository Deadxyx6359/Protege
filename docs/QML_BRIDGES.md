# QML bridges — what the interface can reach

**Living reference.** This is the seam between `protege/core` and QML: every
object the shell registers with the engine, what it offers, and the rules for
using it. It describes what is true *now*. The notes in
[handoffs/](handoffs/) describe what changed and when.

A change to a bridge is not finished until this file says so. Owner: Claude
(backend). Codex binds to it. `protege/ui/bridge/**` is shared, so coordinate
before changing it.

---

## Rules every bridge follows

1. **Nothing crosses threads unmarshalled.** Agents, the scheduler and anything
   waiting on a confirmation all run off the UI thread. Every bridge carries
   their signals across on a queued connection internally, so by the time a
   property changes or a signal reaches QML, it is on the UI thread. QML never
   has to marshal anything.
2. **Long work never runs on the UI thread.** Slots that start agents, jobs or
   reviews start a worker and return at once.
3. **Refusals carry reasons, and the reasons are written for people.** Show
   them. A refusal with no reason teaches people to grant everything.
4. **Deny by default.** No "allow all", no default scope, and no "don't ask
   again" for irreversible actions. None of these exist in the backend, and
   none may be added in the UI.

## Context properties

| Name in QML | Python | Purpose |
|---|---|---|
| `Chat` | `ChatBridge` | The plain conversation. Predates this document; see `bridge/chat.py` |
| `Settings` | `SettingsBridge` | Models and appearance; see `bridge/settings.py` |
| `Permissions` | `PermissionsBridge` | The permission screen and the activity log |
| `Confirm` | `ConfirmBridge` | The irreversible-action dialog |
| `AgentTrace` | `TraceBridge` | Watching agents and teams work |
| `Schedule` | `ScheduleBridge` | Scheduled jobs and the security review |
| `Agents` | `AgentsBridge` | Starting an agent or a team on a task |

Registered in `protege/ui/shell.py` (`AppContext.as_context`). A test asserts
these names, so renaming one is a deliberate, coordinated act.

---

## `Permissions` — what may be attempted

| Member | Kind | Notes |
|---|---|---|
| `catalogue` | Property, list | Every capability as a map: `id`, `title`, `summary`, `domain`, `direction` (`read`/`write`), `risk` (`low`/`medium`/`high`), `scopeKind` (`none`/`path`/`host`/`account`/`provider`), `irreversible`, `leavesMachine`, `granted`, `scopes` |
| `grants` | Property, notifies `grantsChanged` | What is held: `id`, `scopes`, `expires` (0 = never) |
| `grant(id, scopes)` | Slot → string | `""` on success, otherwise **the reason** it was refused. Show it |
| `revoke(id)`, `revokeAll()` | Slots | |
| `describe(id)` | Slot → map | One capability, same shape as a catalogue entry |
| `recentActivity(limit)` | Slot → list | Newest first: `at`, `actor`, `action`, `allowed`, `detail`. **Includes refusals, so keep them visible** |

- **`leavesMachine` is the property most people actually care about**, and it
  does not follow from risk or from read/write. Show it separately and
  prominently rather than folding it into a risk colour.
- `scopeKind` decides the picker: `path` → a folder chooser, `host` → a domain
  field, `account` → an account chooser, `none` → a plain toggle.
- `grant` refuses a scoped capability given no scope, and returns why. Do not
  paper over that with a default. `files.read` with no scope would mean the
  whole disk, which is exactly the mistake scopes exist to prevent.
- Every grant and revoke is written to the activity log, and the security
  review reports changes, so a grant nobody remembers making gets noticed.
- `domain` is the grouping key. Read and write are separate capabilities, so
  they are separate toggles.

## `Confirm` — may this one thing happen now

| Member | Kind | Notes |
|---|---|---|
| `requested(token, summary)` | Signal | Raise the dialog. `summary` already names the real values: the file, the script, the commit message |
| `withdrawn(token)` | Signal | Take a stale dialog down. It timed out, or the application is closing |
| `answer(token, approved)` | Slot | Call on click. A stale or repeated token does nothing, so a double-click cannot approve the *next* request |
| `timeoutSeconds` | Property | 300 |
| `pendingCount` | Property | How many requests are waiting |

**This is the most load-bearing piece of UI in the application.** Every
irreversible action waits on it: file writes, `run_python`, `run_tests`,
`git_commit`, the document tools that create or change a file
(`create_document`, `edit_document`, `update_spreadsheet`), and any scheduled
job that reaches one of those. Until something
answers `requested`, each waits five minutes and is refused, and a scheduled
job holds up the scheduler while it waits.

The dialog must be modal, show `summary` verbatim, and put focus on the safe
button. Anything that is not an explicit approval is a refusal: timeout,
shutdown, a dismissed window. Do not add "don't ask again". The grant says an
agent *may try*; the confirmation is a separate promise the user asked for.

## `AgentTrace` — watching a run

| Member | Kind | Notes |
|---|---|---|
| `events` | Property, list model | Roles: `at`, `kind`, `agent`, `text`, `tool`, `ok`, `recipient`, `step` |
| `activeAgents` | Property, notifies `activeAgentsChanged` | Who has started and not finished: the graph's nodes |
| `clear()` | Slot | |

`kind` is one of `started`, `thinking`, `tool_call`, `tool_result`, `message`,
`answer`, `failed`, `note`. **`message` with a `recipient` is an agent-to-agent
edge**: the research and software teams emit one on every hand-off. Scheduled
jobs appear as agents named `schedule:<job name>`.

The model keeps the newest 500 events; older ones fall off the front.

## `Schedule` — jobs and the security review

| Member | Kind | Notes |
|---|---|---|
| `jobs` | Property, notifies `jobsChanged` | Maps: `id`, `name`, `action`, `when` (plain English, e.g. "Weekdays at 09:00"), `nextRun`, `lastRun` (epoch seconds, 0 if never), `lastStatus`, `enabled`, `done`, `pausedReason`, `missed` (`run_late`/`skip`), `running` |
| `warnings` | Property | Plain-language problems loading or saving the schedule. Show them |
| `history(id)` | Slot → list | Runs, newest first: `status` (`ok`/`failed`/`skipped`/`overlap`/`cancelled`), `summary`, `late`, `trigger` (`time`/`event`/`manual`), `started`, `finished` |
| `pause(id)`, `resume(id)`, `remove(id)` | Slots | Resuming counts forward from now. The runs inside a pause are not "missed" |
| `runNow(id)` | Slot | Starts a worker and returns at once |
| `addJob(spec)` | Slot → string | Create a job: `""`, or why it was refused. See below |
| `findings` | Property, notifies `reviewChanged` | Latest review, worst first. Maps: `severity` (`critical`/`warn`/`info`), `code`, `title`, `detail`, `suggestion`, `capability` |
| `reviewSummary` | Property | e.g. "1 critical, 2 notes", or "Not reviewed yet" |
| `lastReviewAt`, `criticalCount` | Properties | |
| `runReview()` | Slot | Runs the review now, off the UI thread |
| `criticalFound(count)` | Signal | **Raise something the person will see.** Critical findings must not be left sitting in a list |

- The review never changes anything itself. When a finding names a
  `capability`, the natural action is a link to that capability on the
  permission screen, where the person can revoke or narrow it.
- `pausedReason` and run `summary` are written for the person. Show them
  verbatim.
- The daily security review job is created on first run of the application.
- A run stopped because the application was closing is `cancelled`, and
  does not count towards pausing the job.

### Creating a job: `Schedule.addJob(spec)`

Returns `""` on success, otherwise a reason written for the person. A job that
could not run is refused when it is made, not at 3 a.m.

```js
Schedule.addJob({
    name: "Morning research",
    action: "team",                                  // or "agent"
    trigger: { kind: "daily", time: "07:30" },
    arguments: { team: "research", task: "What changed in my notes overnight?" },
    grants: [ { capability: "files.read", scopes: ["C:/Users/me/Notes"] } ],
    missed: "run_late"                               // or "skip"
})
```

- **Triggers:** `once` `{at: "2026-09-11T09:00"}`, `every` `{seconds}` (at
  least 60), `daily` `{time}`, `weekly` `{days: [0..6], time}` with Monday as 0,
  `monthly` `{day: 1–31, time}` (the 31st means the last day in shorter
  months), `cron` `{expr}`, and `event` `{name, match, cooldown}` (a cooldown of
  at least 5 seconds).
- **Arguments:** for `agent`, `role` and `task`; for `team`, `team` and `task`.
- **`grants` are the most a job may use.** Each run gets only what the person
  *also* holds at that moment, so scheduling a job grants nothing, and a
  revocation reaches the next run.
- The security review schedules itself and cannot be added.

---

## `Agents` — starting work

| Member | Kind | Notes |
|---|---|---|
| `teams` | Property | Each team: `name`, `purpose`, and `members` in the order they work |
| `roles` | Property | Each role: `name`, a one-line `summary`, `route`, and `tools` (at most; the policy can still withhold them) |
| `runTeam(team, task, folder)` | Slot → string | `""` once started, otherwise why it was not. `folder` may be `""` |
| `runAgent(role, task, folder)` | Slot → string | The same, for one agent |
| `stop()` | Slot | The run stops at its next token |
| `busy`, `running` | Properties, notify `busyChanged` | `running` names what is working, e.g. "The research team" |
| `answer`, `ok`, `stopped` | Properties, notify `resultChanged` | The last run's result. `stopped` is `answered`, `budget`, `cancelled` or `failed` |
| `finished(ok, answer)` | Signal | Once per run, however it ended |

- **One run at a time from here.** A second request is refused, and the
  reason names what is still running. Show it rather than queueing silently.
- **Naming a folder grants nothing.** It tells the agents where to work; the
  permission screen decides what they may read. When a run needs a folder the
  person has not granted, the natural interface is to offer the grant right
  there, e.g. `Permissions.grant("files.read", [folder])` after the person
  agrees, rather than sending them off to Settings.
- **Progress is in `AgentTrace`**, which shows the run as it happens: members
  starting, tool calls, hand-offs. The answer arrives through `finished`.
- A run waits its turn at the model behind a chat turn or a scheduled job.
  Until its first trace event arrives, it is waiting, not stuck.

## Not reachable yet

- **Tools in the conversation.** `Chat` is the plain conversation path. It does
  not use tools or agents, so nothing typed into it touches files.

## Changing the seam

If QML needs something that is not here, ask for it in a handoff (what, and
why), or add the property or signal to the bridge yourself and record it here
and in your handoff. Keep decisions out of bridges and out of QML: rules belong
in `protege/core`, where they are tested without a running interface.
