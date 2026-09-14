# QML bridges — what the interface can reach

**Living reference.** This is the seam between `akira/core` and QML: every
object the shell registers with the engine, what it offers, and the rules for
using it. It describes what is true *now*. The notes in
[handoffs/](handoffs/) describe what changed and when.

A change to a bridge is not finished until this file says so. Owner: Claude
(backend). Codex binds to it. `akira/ui/bridge/**` is shared, so coordinate
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
5. **Text from outside is plain text.** Replies, answers, notes, file names,
   page text, notices: anything a bridge passes on that the interface did not
   write itself is shown with `textFormat: Text.PlainText`. Qt's default,
   `Text.AutoText`, renders whatever looks like HTML, and loads an `<img>` in
   it. A web address is refused, because the engine's network access is shut
   (`akira/security/qtguard.py`). A `file://server/share/…` address is not:
   Qt reads it as a local file, and Windows opens it as a network share, which
   offers that server the person's sign-in. The one exception is Markdown a
   bridge serves ready for it, `Chat` message text and `Agents.answer`, whose
   pictures arrive as links. Nothing else goes to `Text.MarkdownText`,
   `Text.RichText` or `Text.StyledText`. `tests/test_qml_text_formats.py`
   holds every QML file to this: a `Text` or `Label` whose text is not a
   literal must set `textFormat`, and rich text may appear only where that
   test allows it.

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
| `Memory` | `MemoryBridge` | Notes distilled from conversations, waiting for a person to accept |
| `Projects` | `ProjectsBridge` | Projects, the open one, and the grants that belong to it |
| `Graph` | `GraphBridge` | A tag map and a link graph of a folder of notes |
| `Monitor` | `MonitorBridge` | Watched folders, and the notices jobs put up |
| `Place` | `PlaceBridge` | Where the person is, and the hemisphere the scenes turn their seasons by |
| `Accounts` | `AccountsBridge` | Connected Google addresses: the client file, signing in, disconnecting |
| `Documents` | `DocumentsBridge` | Local folder rows, document text previews and content search |

Registered in `akira/ui/shell.py` (`AppContext.as_context`). A test asserts
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
- **A site is named plainly**, e.g. `example.com`, and covers its subdomains.
  `grant("net.http", [...])` refuses a bare top-level domain (`com` would
  cover every .com site), a full address, a wildcard or a path, with the
  reason, and stores the name lower-cased. The host picker should ask for a
  site, not a URL. `net.http` is what lets agents read pages from that site
  (`fetch_page`), and nothing reaches any site without it.
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
`git_commit`, `git_push`, `save_screenshot`, the document tools that create or change a file
(`create_document`, `edit_document`, `update_spreadsheet`), and any scheduled
job that reaches one of those. Until something
answers `requested`, each waits five minutes and is refused, and a scheduled
job holds up the scheduler while it waits.

The dialog must be modal, show `summary` verbatim, and put focus on the safe
button. It exists: `ConfirmDialog.qml`, in `Main.qml` above every sheet. It
queues requests and shows one at a time, so an answer can only land on the
question it was given for, and a click outside it answers nothing. Anything that is not an explicit approval is a refusal: timeout,
shutdown, a dismissed window. Do not add "don't ask again". The grant says an
agent *may try*; the confirmation is a separate promise the user asked for.

## `AgentTrace` — watching a run

| Member | Kind | Notes |
|---|---|---|
| `events` | Property, list model | Roles: `at`, `kind`, `agent`, `text`, `tool`, `ok`, `recipient`, `step` |
| `activeAgents` | Property, notifies `activeAgentsChanged` | Who has started and not finished: the graph's nodes |
| `recent(limit)` | Slot → list | The newest `limit` events as plain maps, same fields as the roles, oldest first: for a view that draws a run rather than lists it. `AgentsView.qml` redraws from it whenever `events.count` changes |
| `clear()` | Slot | |

`kind` is one of `started`, `thinking`, `tool_call`, `tool_result`, `message`,
`answer`, `failed`, `note`. **`message` with a `recipient` is an agent-to-agent
edge**: the research and software teams emit one on every hand-off. Scheduled
jobs appear as agents named `schedule:<job name>`.

The model keeps the newest 500 events; older ones fall off the front.

## `Agents` — interactive investigations and task history

Additive presentation seam implemented by Codex after coordination handoff 25
(2026-09-14). Existing `runTeam(team, task, folder)`, `runAgent(role, task, folder)`,
`stop()`, `busy`, `running`, `answer`, `ok`, `stopped` and `finished` remain compatible.

- `runs` (QVariantList, `runsChanged`) contains at most 60 newest interactive
  run summaries: `id`, `kind` (team/agent), `name`, `task`, `projectId`,
  `projectName`, `status`, `started`. Scheduled jobs are not in this archive.
- `currentRun` and `record(id)` return a detailed map: summary fields plus
  `answer`, `folder`, `ended`, `stopped`, ordered `members`, `states`, `models`,
  `sources`, `events`. `models` maps members to resolved route and model label
  at start; it does not claim every member reached generation. Answers are
  passed through `inert_markdown`, including after loading from disk.
- Status is `running`, `complete`, `stopped`, `incomplete` or `interrupted`.
  A running record found on startup becomes interrupted, never complete.
  Member states reflect actual trace events. Events retain only the last 80
  tool/handoff/failure labels; no arguments or intermediate model messages.
- Each interactive worker has its own Trace and forwards its events to the
  existing shared Trace. Unrelated scheduled events cannot enter its record.
  `AgentTrace` remains the global activity stream; its API is unchanged.
- `sourcePreview` (QVariantMap, `previewChanged`) is transient plain text:
  `title`, `locator`, `kind`, `tool`, `body`, `truncated`, `id`.
  `previewSource(runId, sourceId)` returns empty string or a visible explanation.
  `clearSource()` dismisses its content. No browser navigation or new read occurs.
- Structured successful results are observed after the original registry runs
  `web_search`, `fetch_page`, `browse_page` (when available), `read_file`,
  `read_document`, `search_notes`, `search_documents`, `search_conversations`.
  Labels distinguish search snippets, pages read, files read and local excerpts.
  They are gathered material, not inferred citations or source verification.
- A run retains up to 32 source labels; bodies cap at 30,000 characters each.
  Bodies for up to four recent runs remain in memory. Preview use checks the
  original project's identity and current permissions. Redirect destination
  and browser-reported sites are included in page-preview checks. A one-second
  timer clears an open preview when its grant expires.
- Shell connects `invalidateSources()` to global/project grant changes and
  project switches. It clears transient content and rejects later source bodies
  from runs started before that invalidation. Existing task/result history is
  retained, like saved conversations; answers can themselves quote source text.
- `deleteRun(id)` removes the saved task/result/references off the GUI thread.
  Active runs must be stopped first. `archiveBusy` prevents overlapping deletes;
  `historyError` reports save/load/delete failures. A failed save keeps the result
  in this session. The UI asks once before removing a result. This affects no
  underlying project file, agent output artifact or audit entry.
- `ui/run_archive.py` is a UI-owned bounded JSON archive at
  `config_dir()/investigations.json`: version 1, 60 records, 12 MB load/write cap,
  4,000-character task and 60,000-character answer caps. Only whitelisted fields
  are saved. Writes are atomic and serialized on workers, with bounded retry for
  Windows sharing violations. An unreadable existing file is preserved and
  further writes refused with a visible error. `build_context(persist=False)`
  uses an in-memory archive. No model, scheduler, tool or permission rule changed.

UI: Research keeps local conversation and adds Investigations with editable
question, explicit start/stop, project-filtered results, member progress and
gathered-source previews. Code has a software-history button; Agents has Task
history with optional all-project viewing. Both show original task ownership,
model assignments and results. Research source text is always plain; answers
alone use the existing guarded Markdown renderer. The normal launcher loads
these changes from source when Akira is reopened.

## `Schedule` — jobs and the security review

| Member | Kind | Notes |
|---|---|---|
| `jobs` | Property, notifies `jobsChanged` | Maps: `id`, `name`, `action`, `when` (plain English, e.g. "Weekdays at 09:00"), `nextRun`, `lastRun` (epoch seconds, 0 if never), `lastStatus`, `enabled`, `done`, `pausedReason`, `missed` (`run_late`/`skip`), `running`, `watch` (the `Monitor` watch an event job waits on, from its trigger's `match`, or `""`) |
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
- `ScheduleView.qml` shows every job with its last five runs, and the latest
  findings, each with a way to the permission screen when it names a
  capability. It runs the review on request but offers neither pause nor
  remove for it: the review is what notices a grant that should not be there.
  Removing any other job asks twice. A critical finding's banner leads here.

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
- **Arguments:** for `agent`, `role` and `task`; for `team`, `team` and `task`;
  for `notify`, `text` and optionally `title` (the job's name otherwise). A
  `notify` job needs `notify.send` in its `grants`. See `Monitor` for the usual
  pairing with a watched folder.
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
- `answer` is Markdown with its pictures served as links, like `Chat` text.
  Show it with `Text.MarkdownText` or as plain text, never as rich text.

## `Memory` — notes distilled from conversations

| Member | Kind | Notes |
|---|---|---|
| `vault` | Property, notifies `vaultChanged` | The vault memory is kept in. `""` until one is chosen |
| `setVault(path)` | Slot → string | Choose the vault: `""`, or why not. Sets up the nightly job (03:30, run late if the machine was off) |
| `pending` | Property, notifies `pendingChanged` | Proposals, oldest first. Maps: `id`, `title`, `target` (its path inside the vault), `addsTo` (adds to an existing note rather than making one), `preview` (the new note, or a unified diff of the addition), `sources` (conversation titles), `project` (the project those conversations were held in, or `""`), `created` (epoch seconds) |
| `pendingCount` | Property, notifies `pendingChanged` | |
| `accept(id)` | Slot → string | Write it into the vault: `""`, or why not, including **Not permitted** when `vault.write` does not cover that note |
| `reject(id)` | Slot → string | Discard it. The conversation it came from is untouched |
| `distilNow()` | Slot → string | Read recent conversations now rather than tonight. Starts a worker and returns at once |
| `busy`, `lastRun` | Properties, notify `busyChanged` | `lastRun` is the last run started here, in a sentence, e.g. "2 notes proposed from 3 conversations; waiting for review." |

- **Nothing reaches the vault until `accept`.** Proposals wait outside it and
  are not searchable, so what the model wrote cannot shape an answer before a
  person has read it. Show `preview` verbatim; for an addition it is a diff.
- **The job needs two grants the person makes separately:** `memory.read`, and
  `vault.read` for the vault. Without them a run fails, and its summary in
  `Schedule.history` names what is missing. A setup screen can offer both
  grants beside the vault picker.
- **`accept` can refuse after the fact.** If the note changed since the
  proposal was made, nothing is written: the proposal is re-based on the note
  as it is now and `pendingChanged` fires. Show the reason and the new preview.
- Accepting is recorded in the activity log as `accept_memory`, and an accepted
  note can be undone from its history like any vault write.
- The job shows in `Schedule.jobs` as "Memory". Choosing another vault moves it.
- `MemoryView.qml` offers `memory.read` and `vault.read` beside the vault
  picker, and shows each `preview` in a plain-text code block. When `accept` is
  refused it offers `vault.write` for **the folder that note goes in** (for
  example `<vault>/Memory`), never the whole vault, then accepts. A path grant
  may name a folder that does not exist yet; `real()` resolves it anyway.

## `Projects` — projects, and grants that belong to one

| Member | Kind | Notes |
|---|---|---|
| `projects` | Property, notifies `projectsChanged` | Each: `id`, `name`, `folder`, `personality`, `current` |
| `currentId`, `currentName` | Properties, notify `currentChanged` | `""` when no project is open |
| `create(name, folder)` | Slot → string | Make a project **and open it**. `folder` may be `""`. Returns `""`, or why not |
| `openProject(id)` | Slot → string | Open one. `openProject("")` leaves projects |
| `rename(id, name)`, `setFolder(id, folder)`, `setPersonality(id, text)` | Slots → string | `""`, or why not |
| `remove(id)` | Slot → string | Forgets the project and its grants. **Its notes are not touched**; say so when confirming |
| `grants` | Property, notifies `grantsChanged` | The open project's own grants: `id`, `scopes`, `expires` (0 = never) |
| `grant(id, scopes)` | Slot → string | Grant **only in the open project**. Refused when none is open. Otherwise the same rules as `Permissions.grant` |
| `revoke(id)` | Slot → string | |

- **Two places a grant can live.** `Permissions` holds grants that apply
  everywhere. `Projects.grant` holds grants that apply only while that project
  is open. When the person grants something, make the choice explicit
  ("Everywhere" or "Only in <project>"), and lead with the project when one is
  open: it is the narrower answer.
- **What uses which.** Agents and teams started from the interface run under
  the global grants plus the open project's. Scheduled jobs run under the
  global grants only, so a nightly job's permissions never depend on what was
  on screen. A job that needs a folder needs it granted everywhere.
- Project grants and revocations are in the activity log with the project's
  name, and the security review checks them like any other grant.
- `personality` is stored, but the conversation does not use it yet. `folder` is
  where the project's notes live; it grants nothing.
- The sidebar lists `projects` and marks `currentId`; a project's colour comes
  from its id, so it does not change when another is removed. Clicking another
  project opens it; clicking the open one shows `ProjectSheet.qml`: rename,
  folder, the open project's `grants` each with a way to take it away, leave,
  and forget, which asks twice. Granting something only in a project is not
  offered yet: the permission screen grants everywhere.

## `Graph` — what a folder of notes knows

| Member | Kind | Notes |
|---|---|---|
| `build(folder, width, height)` | Slot → string | Read the notes under `folder` and draw them for a canvas that size. `""` once started, otherwise why not, including **Not permitted** without `vault.read` there |
| `busy` | Property, notifies `busyChanged` | |
| `tags` | Property, notifies `builtChanged` | The tag map, laid out: `nodes` (`id`, `label`, `hub`, `real`, `weight`, `x`, `y`, `radius`), `edges` (`a`, `b`, `kind`: `branch` or `cotag`), `hidden`, `summary` |
| `links` | Property, notifies `builtChanged` | The link graph, **not** laid out: `nodes` (`id` is the note's path in the vault, `label` its title, `weight` how many links touch it), `edges` (`kind` `link`, from `a` to `b`), `unresolved`, `hidden`, `summary` |
| `error` | Property, notifies `builtChanged` | Why the last build failed, or `""` |

- **The tag map holds still.** The same notes always give the same positions
  for the same canvas, so the person can learn the map. Rebuild on resize
  rather than animating nodes about.
- A hub with `real` false is a group nobody tagged directly (only
  `#travel/japan`, never `#travel`). Draw it, but not as a tag.
- `summary` is written for the person. Show it, especially when the map is
  empty (it says how to start) or `hidden` is not zero.
- The link graph is QML's to place. Links to notes that do not exist yet are
  counted in `unresolved`, not drawn.
- It reads under the global grants plus the open project's, like agents, and
  each request is in the activity log as `draw_map`.

## `Monitor` — watched folders, pages and feeds, and notices

| Member | Kind | Notes |
|---|---|---|
| `watches` | Property, notifies `watchesChanged` | Each: `id`, `kind` (`folder`, `page` or `feed`), `folder`, `url` (without its query string), `title` (a page's or feed's own, once looked at), `patterns` (file patterns such as `*.pdf` for a folder, words to look for on a page or in a feed; empty means everything), `every` (minutes between looks at a page or feed, 0 for a folder), `paused` (why it is not reporting, or `""`), `lastChange` and `lastLook` (epoch seconds, 0 if never) |
| `addWatch(folder, patterns)` | Slot → string | Watch a folder: `""`, or why not, including **Not permitted** without `files.read` there |
| `addPageWatch(url, words, minutes)` | Slot → string | Watch a web page for new lines. `minutes` is 15 or more, or 0 for hourly. `""`, or why not, including **Not permitted** without `net.http` for its site |
| `addFeedWatch(url, words, minutes)` | Slot → string | Watch an RSS or Atom feed for new entries, the same way |
| `addInboxWatch(address, words, minutes)` | Slot → string | Watch a connected inbox for new mail, the same way. `""`, or why not: an address not connected for mail, or **Not permitted** without `mail.read` for it. Watches carry `address`, and `kind` `inbox` |
| `removeWatch(id)` | Slot → string | `""`, or why not |
| `warnings` | Property, notifies `watchesChanged` | Problems loading or saving the watches. Show them |
| `notices` | Property, notifies `noticesChanged` | Newest first, at most 50: `title`, `text`, `at` |
| `noticed(title, text)` | Signal | Once per notice as it arrives. **The moment to put something on screen** |
| `clearNotices()` | Slot | |

- **What a watch does on its own: nothing visible.** It turns changes into
  scheduler events. Something happens only when a job waits for them. The
  pair a person usually wants is a watch plus a `notify` job:

  ```js
  Monitor.addWatch("C:/Users/me/Downloads", ["*.pdf"])
  Schedule.addJob({
      name: "New PDFs",
      action: "notify",
      trigger: { kind: "event", name: "folder.changed", match: { watch: "<id from Monitor.watches>" }, cooldown: 60 },
      arguments: { text: "New PDFs arrived." },
      grants: [ { capability: "notify.send", scopes: [] } ],
      missed: "skip"
  })
  ```

  `action: "agent"` or `"team"` works the same way, when something should be
  done about what arrived. The event's details are appended to the task, and
  the agent is told they are material to read, not instructions. A page or a
  feed pairs the same way, e.g. `Monitor.addPageWatch("https://example.com/tickets",
  ["on sale"], 0)` with a job on `page.changed`.
- **Events.** A folder: `file.created`, `file.changed` and `file.deleted` for
  each file (`watch`, `folder`, `path`, `name`), and one `folder.changed` per
  look (`watch`, `folder`, `created`, `changed`, `deleted` counts, and the first
  20 `paths`). A page: `page.changed` (`watch`, `url`, `title`, `added` and
  `removed` counts, and up to 10 of the new `lines`). A feed: `feed.item` for
  each new entry (`watch`, `url`, `feed`, `title`, `link`, `published`,
  `summary`), and one `feed.changed` per look (`watch`, `url`, `feed`, `new`,
  and up to 10 `titles`). An inbox: `mail.item` for each new message (`watch`,
  `address`, `from`, `subject`, `date`, `snippet`, `id`), and one `mail.changed`
  per look (`watch`, `address`, `new`, and up to 10 `subjects`); up to ten
  messages a look, from the inbox's last week. Match on `watch`.
- **A file is reported once it has settled**, which takes two looks, about a
  minute. A download in progress is not announced half-finished.
- **A page is compared as text.** Markup, scripts and styles go first, and the
  same lines in another order are no change. Words narrow it to lines that
  mention one, which is also the answer to a page that changes on every look,
  such as one showing the time. A feed reports entries it has not seen before,
  narrowed by words the same way.
- **Pages and feeds are looked at hourly unless the person chooses, never more
  often than every 15 minutes.** The first look is a baseline. What was seen
  is kept across a restart, so a change made while the app was closed is still
  reported.
- **Addresses lose their query strings** in `url`, in events and in the
  activity log, because that is where a private feed keeps its key.
- **`paused` is written for the person.** It fills when the permission is
  revoked, the folder disappears or holds too many files, or a page cannot be
  fetched or read: an error page, a site that is down, a web page watched as a
  feed. The watch resumes by itself when the cause goes away; a site that was
  down is tried again at its next look, not sooner. Show the reason where the
  watch is listed.
- **Notices are plain text** (rule 5). With a page or a feed they quote it.
- Watches use the **global** grants, like scheduled jobs, never the open
  project's.
- **Keep a watch and its jobs together.** The Watching view (`WatchView.qml`)
  pairs a watch with a `notify` job on its `*.changed` event, named "Watching
  <name>", when the person asks to be told; removing the watch removes every
  job whose `watch` (in `Schedule.jobs`) is that watch's id. A view that adds
  or removes watches another way should do the same, or leave jobs waiting for
  events that will never come.
- `noticed` and `Schedule.criticalFound` are put on screen by `NoticeBanner`
  in `Main.qml`: a notice for ten seconds (held while hovered), a critical
  finding until it is dismissed.

## `Place` — where the person is, the scenes' hemisphere, and the weather there

| Member | Kind | Notes |
|---|---|---|
| `name` | Property, notifies `placeChanged` | The place the person set, e.g. "Bristol, UK", or `""` |
| `hemisphere` | Property, notifies `placeChanged` | `north`, `south`, or `""`. A position decides it |
| `southernHemisphere` | Property, notifies `placeChanged` | **Bind `SceneHost.southernHemisphere` to this** |
| `season` | Property, notifies `placeChanged` | Today's season in that hemisphere, by the scenes' own rule |
| `hasPosition`, `latitude`, `longitude` | Properties, notify `placeChanged` | The place's position, which the weather needs. `latitude` and `longitude` are 0 when `hasPosition` is false |
| `setPlace(name, hemisphere)` | Slot → string | `""`, or why not. A new name forgets the old one's position |
| `setPosition(latitude, longitude)` | Slot → string | Give the place a position directly. `""`, or why not |
| `findPlace(text)` | Slot → string | Look a place up by name, on a worker. `""` once started, or why not |
| `candidates` | Property, notifies `lookupChanged` | What the lookup found, best first: `label`, `latitude`, `longitude` |
| `lookupNote`, `lookingUp` | Properties, notify `lookupChanged` | Why the lookup found nothing, or `""`; whether one is running |
| `choosePlace(index)` | Slot → string | Keep one of `candidates`, with its position. `""`, or why not |
| `clearPlace()` | Slot | Forgets the place, its position and its weather |
| `weather` | Property, notifies `weatherChanged` | **Bind `SceneHost.weather` to `Place.weather \|\| "clear"`.** One of the scenes' names, or `""` when there is no current reading |
| `weatherSummary`, `weatherAt` | Properties, notify `weatherChanged` | e.g. "14°C, light rain", and when it was read (epoch seconds). Empty and 0 without a reading |
| `weatherNote` | Property, notifies `weatherChanged` | Why there is no current reading, written for the person, or `""` |
| `weatherSite` | Constant | `open-meteo.com`, the site to offer for `net.http` |
| `refreshWeather()` | Slot → string | Read it now, on a worker. `""` once started, or why not |

- **Setting a place grants nothing.** Models are told the place, the time zone
  and the weather only while `location.read` is granted. They are always told
  the date and time, which say nothing about where anyone is.
- **The weather needs two grants and a position.** `location.read`, and
  `net.http` for `weatherSite`, which covers both the forecast and the lookup.
  Without them nothing is sent and `weatherNote` says what is missing: offer
  the grants there, after the person agrees, rather than sending them to
  Settings. Looking a place up needs only `net.http`; the person typed it and
  asked.
- **Approximate.** A position is kept to two decimals, about a kilometre, and
  sent to the weather service to one, about eleven. The activity log keeps the
  requests without the position.
- **Read every half hour** in the background, under the global grants. A
  reading more than three hours old is not the weather now: `weather` goes
  back to `""` and the scene to its default. A new position forgets the old
  reading at once and reads the new one.
- `candidates` labels come from the lookup service, so show them as plain text
  (rule 5).
- The view is `PlaceSheet.qml`, opened from Settings. `Main.qml` binds
  `SceneHost.weather` and `southernHemisphere` to this bridge. A view that
  changes the weather's site grant must read `Permissions.describe("net.http")`
  fresh at that moment: `grant` replaces the whole list of sites, so adding
  to a stale copy drops any site allowed since.
- The Python season rule is the one in `scenes/world.js`, and the weather
  names are its `WEATHER` list, so the scenery and the assistant agree. A test
  checks the names. Keep them the same if either changes.

## `Accounts` — connected Google addresses

| Member | Kind | Notes |
|---|---|---|
| `clientReady` | Property, notifies `clientChanged` | Whether the Google client file has been chosen and sealed |
| `chooseClientFile(path)` | Slot → string | Seal the client in a file downloaded from Google Cloud: `""`, or why not (a web client, not a client file, sign-ins sent somewhere other than Google) |
| `services` | Property | What an address can be connected for: `id` (`mail`, `calendar`, `send`), `title`, `capability`. `send` asks Google for sending alone (`gmail.send`, under `mail.send`), and is best left off until the person asks for it |
| `accounts` | Property, notifies `accountsChanged` | Each: `address`, `services` (ids), `titles`, `connected` (epoch seconds), `needsSignIn` (why it must be connected again, or `""`) |
| `missing(address, services)` | Slot → list | What must be allowed first: `capability` and `title` for each service not granted for that address |
| `connectAccount(address, services)` | Slot → string | Start signing in: `""` once started, or why not, including **Not permitted** while `missing` is not empty |
| `busy`, `connecting` | Properties, notify `busyChanged` | `connecting` is the address being signed in, or `""` |
| `cancel()` | Slot | Stop waiting for the browser. The sign-in ends through `finished` |
| `finished(ok, message)` | Signal | Once per sign-in, however it ended. **Show `message`**: it says what was connected, or why nothing was |
| `disconnectAccount(address)` | Slot → string | Hand the sign-in back to Google and forget it: `""`, or a note when Google could not be told. It is forgotten here either way |

- **Nothing secret crosses this bridge**: not the client's secret, not a
  sign-in. There is nothing to type but the address.
- **The address is allowed first.** `mail.read` and `calendar.read` are scoped
  to the address. Offer them beside it, from `missing`, and read the grant
  fresh when adding one (`AccountsSheet.qml` does both), since
  `Permissions.grant` replaces the whole list of addresses.
- **Signing in happens in the person's browser**, which Windows opens at
  Google's page; it waits up to five minutes. Google calls the app unverified,
  because it is the person's own client, and says so; the view should too.
- Connecting uses the global grants, never a project's.
- The slots are `connectAccount` and `disconnectAccount` because every QObject
  already has `connect` and `disconnect`.

## `Chat` — what a turn drew on

`Chat` is otherwise as it was (see `bridge/chat.py`). Two properties and a
stage are new:

| Member | Kind | Notes |
|---|---|---|
| `lastSources` | Property, notifies `sourcesChanged` | What the last turn drew on: `source` (`notes`, `documents` or `conversations`) and `cite`, where to find it. Empty when nothing was used |
| `lastContextNote` | Property, notifies `sourcesChanged` | What the search found and what it could not search, in a sentence. Also carries the reason when looking failed |
| `conversationProject` | Property, notifies `titleChanged` | Stored project ID of the loaded conversation; empty for personal/new unsent chats. QML uses it to restore the project when opening a recent chat |
| `stage` | Existing property | Now also `Looking through your notes` before the model starts |

- Before each turn, passages are gathered from the sources the person has
  granted, and the open project's personality and the date and time are
  added. The place and time zone are added only with `location.read` (see
  `Place`). All of it goes with that turn only and is never saved with the
  conversation. A source that is not granted is not searched.
- Show `lastSources` under the answer, as the citations the model was asked
  to give. A turn that used nothing shows nothing.
- New chat, successful conversation open, and deletion of the open chat clear
  both retrieval properties. Failed opens keep the current chat and its labels.
- The shell now starts a fresh conversation on project switches, keeping unsent
  drafts per project in memory. Opening a saved conversation restores its stored
  project (or explains personal context if the original project is gone). UI
  project switches are disabled while chat/agent work runs. No grant is added.
- If gathering fails, the turn still answers without it, and
  `lastContextNote` says why.
- **Message text is served for Markdown.** A picture in a reply arrives as a
  link, `\![alt](address)`, so it is shown and never loaded (see rule 5). The
  saved conversation keeps the words as written. An error's text is plain;
  show it plain.

## Documents

Implemented by Codex after the coordination handoff dated 2026-09-12 (19).
This is a read-only presentation adapter over `read_file`, `read_document`
and `search_documents`; parsing, indexing and permission decisions stay in
the existing backend. It uses the current project's effective policy.

- Properties, all notified by `changed`: `folder`, `entries`, `selected`,
  `preview`, `query`, `passages`, `busy`, `operation`, `error`, `limited`,
  `canGoUp`, `roots`.
- `openFolder(pathOrLocalUrl)` lists supported documents and subfolders under
  `files.read`. Rows have `path`, `name`, `folder`, `kind`, `size`, `modified`,
  `capability`. Folders sort first; dot entries, lock files, links and junctions
  are skipped. Listing caps: 400 displayed items / 4,000 scanned entries.
- `previewFile(pathOrLocalUrl)` calls `read_file` for Markdown/text under
  `files.read`; Office/PDF previews call `read_document` under `docs.read`.
  Text previews cap at 200 KB before reading. Office reader limits apply.
  The preview removes the reader's exact known path/line-number envelope for
  display only, falling back to the complete response if its format changes.
  All headings, tables, cell references and truncation notices are plain text.
- `search(query)` searches the open folder and its subfolders through the
  existing local index. Requires `docs.read` for that folder and also
  `files.read` for text/Markdown. Returned passage maps retain the tool fields
  (`cite`, `rel`, `section`, `text`, `score`, `complete`) plus `path`, `name`.
  Empty query clears search. Search can update the existing local index.
- `refresh()`, `goUp()`, `clearPreview()` and `cancel()` manage the current view.
  `copyPath()` copies the selected file's path, or the folder path, after a
  fresh permission check; returns empty string on success or an explanation.
- `invalidate()` cancels pending publication and clears displayed content.
  Shell connects this to global/project grants and current-project changes.
  A one-second timer also detects expiring read grants. Permissions are checked
  on use, inside the tools and before publishing results. Search passages are
  checked individually again on arrival. Superseded results are discarded.
- One background daemon worker processes requests serially with one replaceable
  pending request. Cancel discards its results; an already running parser may
  finish. `AppContext.close()` closes this adapter, and parsing cannot keep the
  window's process alive on its own.
- The local picker never grants access. Remote URLs, UNC paths and linked
  locations are refused. Refusals are visible and audited; the UI opens the
  existing permission sheet for changes. No document edit, external app launch,
  upload, model call or automatic scan is performed by this workspace.

## Coding

Implemented by Codex after coordination handoff 23 (2026-09-13). A presentation
adapter for the Code workspace, using the current project's effective policy.
It registers only the existing `git_status`, `git_diff`, `git_log` and
`open_in_editor` tools; the registry still authorizes and audits each invocation.

- Properties, all notified by `changed`: `busy`, `operation` (`review`,
  `editor`, or empty), `folder`, `status`, `preview`, `mode`, `changes`,
  `checked`, `error`, `notice`.
- `inspect(folderOrLocalUrl, mode)` accepts `working`, `staged`, `history`.
  It obtains Git status and then the corresponding patch or last 12 commits.
  Requires `vcs.read` over the repository root. Core tools reject a child
  folder whose Git scope would extend beyond the allowed directory. Git's
  existing timeout, output limits, hook restrictions and local-only environment
  remain in effect. This adapter never adds Git command arguments of its own.
- `status` and `preview` are complete tool responses, displayed as selectable
  plain text. No paths, links, navigation or write actions are derived from
  them. `changes` is the status tool's entry count, not a recursive file count;
  untracked directories may be grouped, and untracked content is not a patch.
  `checked` is the local completion time for this snapshot, not a live monitor.
- `openEditor(folderOrLocalUrl)` invokes `open_in_editor` under `files.read`
  after an explicit click. The QML target is the active project's stored
  folder. Editor launch is independent of Git permission. Missing VS Code or
  denied access is shown verbatim. No editor process is launched on navigation.
- Requests use one serial daemon worker and one replaceable pending request.
  `cancel()` discards pending publication; `invalidate()` also clears displayed
  data. The shell invalidates on global/project grant and project changes; a
  one-second timer also detects expiry. Tools consult a live policy and results
  are checked again on arrival. A process already launched cannot be unlaunched
  by cancelling a later UI request. `AppContext.close()` stops this adapter.
- Local-path validation is shared with Documents. No UNC, remote URL or linked
  path is accepted. No new grant, staging, commit, push, code execution, model
  run or repository mutation is introduced by the review panel.

UI notes: Code still shares Chat's conversation/composer and prepares an
editable software-team task in Agents. Settings now groups General, Appearance
and Models; model assignment uses original paths, with display-only name cleanup
and exact paths in File details. Model selectors are disabled during Chat/Agents
work. These are UI safeguards, not changes to the router or agent engine.

Navigation counts use existing `Memory.pendingCount`, `Monitor.notices.length`
and `Schedule.criticalCount`. These mean pending notes, saved notices and the
latest review's critical findings. They are not unread counts. Clearing a notice
or resolving a proposal updates the UI through the existing bridge signals.

## Not reachable yet

- **Tools in the conversation.** `Chat` does not call tools on the model's
  behalf, and nothing typed into it changes a file. It does read, before each
  turn, from the sources the person has granted (see `Chat` above).

## Changing the seam

If QML needs something that is not here, ask for it in a handoff (what, and
why), or add the property or signal to the bridge yourself and record it here
and in your handoff. Keep decisions out of bridges and out of QML: rules belong
in `akira/core`, where they are tested without a running interface.
