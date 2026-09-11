# Backend handoff → Codex

> **Superseded by [04](2026-09-10-04-claude-to-codex-section-a-complete.md).**
> Moved from `docs/BACKEND_HANDOFF_FOR_CODEX.md`. Kept as the record of the
> spine session. Its bridge sections predate the fix that registered the
> bridges with QML, and §6 is out of date; for what is true now, read
> [QML_BRIDGES.md](../QML_BRIDGES.md).


Written by Claude at the end of the backend session that built Phase A of
`docs/PLATFORM.md`. You own the frontend; this describes what now exists
underneath it, what it expects from the UI, and what must not be broken.

`docs/PROJECT.md` is the canonical description, the full scope, and the
numbered work order — read that first; work items there have stable IDs
(`A4`, `C1`, …) worth using in conversation. `docs/REBUILD.md` covers the
UI/model decisions already made. This file only covers what changed in this
session and the API you bind to.

---

## 1. What landed: the spine

Three new packages under `protege/core/`. None of them touch the UI, and none
of them can reach the network.

| Package | What it is |
| --- | --- |
| `core/permissions/` | Capability catalogue, grants, scope matching, audit log, DPAPI secret store |
| `core/tools/` | Tool schema, the registry that gates every call, the built-in file tools |
| `core/agents/` | Trace, the tool-call protocol for local models, the agent loop |

The design in one sentence: **an agent is a model, a set of tools it has been
granted, and a loop** — and permission is enforced *structurally*, by building
the tool list from the policy, so an ungranted capability produces no tool and
there is nothing for a jailbreak to reach for.

### Files added

```
protege/core/permissions/capabilities.py   30 capabilities, the catalogue
protege/core/permissions/model.py          Grant, Decision, Policy
protege/core/permissions/audit.py          AuditLog, Event, redact()
protege/core/permissions/secrets.py        SecretStore (Windows DPAPI)
protege/core/tools/schema.py               Parameter, Requirement, Tool, ToolContext, ToolResult
protege/core/tools/registry.py             ToolRegistry
protege/core/tools/builtin/files.py        read_file, list_directory, search_files, write_file
protege/core/agents/trace.py               Kind, Event, Trace
protege/core/agents/protocol.py            parse_calls, render_tools, format_result
protege/core/agents/loop.py                AgentSpec, Outcome, Agent
tests/test_permissions.py                  adversarial: traversal, symlinks, lookalike hosts, corrupt grants
tests/test_tools.py                        the gate: what an agent is shown, and what happens on a call
```

Modified: `protege/security/paths.py` gained a public `reject_dangerous()`.

---

## 2. Ownership boundary

To keep us from overwriting each other:

- **I own** `protege/core/**`, `protege/security/**`, `tests/test_permissions.py`,
  `tests/test_tools.py`, `tests/test_agents.py`.
- **You own** `protege/ui/qml/**`, `protege/design/**`, and the scene files.
- **Shared, coordinate first:** `protege/ui/bridge/**` — this is the seam
  between us. If you need a new property or signal there, add it and say so in
  this file rather than reaching into `core/`.

Nothing in `core/` imports from `ui/`. Please keep it that way; the moment it
does, the core stops being testable headless.

---

## 3. The API you need to bind to

This is the part that matters for your work. Four things are ready for UI.

### 3.1 `Trace` — live "which agent is doing what"

The user explicitly asked to *see* which model is doing what and how agents
interact. `Trace` is that feed.

```python
from protege.core.agents import Trace, Kind

trace = Trace()
stop = trace.listen(lambda event: ...)   # returns the unsubscribe function
trace.replay()                            # everything so far, for a late-attaching view
```

`Event` is a frozen dataclass with `to_json()`:

| Field | Meaning |
| --- | --- |
| `at` | float timestamp |
| `kind` | `Kind` enum, below |
| `agent` | which agent emitted it |
| `text` | the prose / answer / error |
| `tool` | tool name, on `TOOL_CALL` / `TOOL_RESULT` |
| `arguments` | dict, on `TOOL_CALL` |
| `ok` | bool, on `TOOL_RESULT` |
| `to` | the receiving agent, on `MESSAGE` |
| `step` | which step of the loop |

`Kind` values: `STARTED`, `THINKING`, `TOOL_CALL`, `TOOL_RESULT`, `MESSAGE`,
`ANSWER`, `FAILED`, `NOTE`.

`MESSAGE` + `to` is the agent-to-agent edge — that is what you draw when you
visualise a team. Teams landed in A4 and emit one on every hand-off.

Two things to know: `listen` callbacks fire on the **worker thread**, so marshal
onto the Qt thread before touching anything visual. And a listener that raises
is swallowed deliberately — a broken view must not stop an agent run — so you
will get silence, not a traceback, if your callback throws.

### 3.2 `Policy` + `CATALOGUE` — the permission screen

30 capabilities, each written to be read by *someone deciding whether to allow
it*, not by a developer. Everything you need to render the screen is on the
`Capability`:

```python
from protege.core.permissions import CATALOGUE, get, Policy

cap = get("files.write")
cap.id            # "files.write"        stable, grants are stored against it
cap.title         # short label
cap.summary       # one plain sentence
cap.direction     # Direction.READ | WRITE
cap.risk          # Risk.LOW | MEDIUM | HIGH
cap.scope         # ScopeKind.NONE | PATH | HOST | ACCOUNT | PROVIDER
cap.irreversible  # confirms individually every time, regardless of grant
cap.leaves_machine # sends data off the machine
cap.domain        # "files"  — group by this
```

The catalogue: `audio.play`, `audio.record`, `bank.read`, `calendar.read`,
`calendar.write`, `clipboard.read`, `clipboard.write`, `docs.read`,
`docs.write`, `files.read`, `files.write`, `lms.read`, `lms.write`,
`location.read`, `mail.read`, `mail.send`, `messages.read`, `messages.send`,
`model.cloud`, `net.http`, `notify.send`, `screen.capture`, `shell.run`,
`vault.read`, `vault.write`, `vcs.read`, `vcs.write`, `web.browse`,
`web.search`, `web.submit`.

Policy operations:

```python
policy = Policy.load()
policy.grant("files.read", (str(path),), expires=None)   # scoped caps REQUIRE a scope
policy.revoke("files.read")
policy.active()          # list[Grant], expired ones dropped
policy.allows(cap, scope)  # -> Decision; falsy when denied, .reason explains why
policy.save()
```

Design notes that affect your UI:

- **`leaves_machine` is the property most people actually care about**, and it
  does not follow from read/write. Surface it separately and prominently — do
  not bury it in a risk colour.
- `ScopeKind` tells you which picker to show: `PATH` → folder chooser,
  `HOST` → domain field, `ACCOUNT` → account chooser, `NONE` → plain toggle.
- A scoped capability granted with no scope raises `ValueError`. There is no
  "allow everywhere" and no "allow all" — deliberately, and there are tests
  asserting those switches do not exist. Do not add one.
- `Decision.reason` is written to be shown to the user. A refusal with no reason
  trains people to grant everything, so please display it.

### 3.3 `ToolContext.confirm` — **the seam that needs you most**

```python
confirm: Callable[[str], bool] = lambda summary: False
```

Every irreversible action calls this with a human-readable summary containing
the actual values, and **the default is no**. That is intentional — a context
assembled without a way to ask cannot approve on the user's behalf — but it
means that **until you wire a real dialog, every write, send, and submit is
denied.** The UI is load-bearing here, not decorative.

What it needs to be: modal, showing the summary verbatim, defaulting to the
safe option, and returning a bool. A confirm that raises counts as no (tested).

Do not add a "don't ask again" checkbox for `irreversible` capabilities. The
grant already says the agent *may try*; the confirmation is a separate promise
and the user asked for it explicitly.

### 3.3b The bridges are now built (A5)

`protege/ui/bridge/` now carries three QObjects. You do not need to touch
`core/` for any of this.

```python
from protege.ui.bridge import PermissionsBridge, ConfirmBridge, TraceBridge
```

**`PermissionsBridge`** — the permission screen.

| Member | Kind | Notes |
|---|---|---|
| `catalogue` | Property, `QVariantList` | Every capability as a dict: `id`, `title`, `summary`, `domain`, `direction`, `risk`, `scopeKind`, `irreversible`, `leavesMachine`, `granted`, `scopes` |
| `grants` | Property, notifies `grantsChanged` | What is currently held |
| `grant(id, scopes)` | Slot → `str` | Returns `""` on success, or **the reason** it was refused — show it |
| `revoke(id)`, `revokeAll()` | Slot | |
| `describe(id)` | Slot → map | One capability |
| `recentActivity(limit)` | Slot → list | Newest first; **includes refusals, keep them visible** |

`grant` refuses a scoped capability given no scope, and returns why. Do not
paper over that by passing a default — granting `files.read` with no scope
would mean the whole disk, which is the exact mistake scopes exist to prevent.

**`ConfirmBridge`** — the dialog that makes writes possible at all.

| Member | Kind | Notes |
|---|---|---|
| `requested(token, summary)` | Signal | Raise the dialog. `summary` already names the real values |
| `withdrawn(token)` | Signal | Take a stale dialog down — it timed out or the app is closing |
| `answer(token, approved)` | Slot | Call on click. A stale or repeated token does nothing |
| `timeoutSeconds` | Property | Currently 300 |
| `close()` | Slot | Call at shutdown; wakes every waiting agent with a refusal |

Wire it as `ToolContext(confirm=confirm_bridge.ask)`. `ask` blocks a worker
thread until `answer` arrives, so **it must never be called on the UI thread** —
it detects that and returns `False` rather than freezing the window, but the
action is then denied. Anything that is not an explicit approval is a refusal:
timeout, shutdown, a dismissed dialog, a wrong-thread call.

Show the summary verbatim and default the focused button to the safe one. Do
not add a "don't ask again" for irreversible capabilities.

**`TraceBridge`** — watching a run.

| Member | Kind | Notes |
|---|---|---|
| `events` | Property, `QAbstractListModel` | Roles: `at`, `kind`, `agent`, `text`, `tool`, `ok`, `recipient`, `step` |
| `activeAgents` | Property, notifies `activeAgentsChanged` | Who has started and not finished — the graph's nodes |
| `attach(trace)` / `detach()` | Python | Replays what the trace already holds |
| `clear()` | Slot | |

The model is capped at 500 rows; the oldest fall off. Events cross from the
worker thread on a queued connection inside the bridge, so by the time QML sees
them they are on the UI thread — you do not need to marshal anything yourself.

`kind == "message"` with `recipient` set is the agent-to-agent edge. **A4 has
landed, so these now actually fire** — the research and software teams emit one
per hand-off, and the interaction graph will no longer be empty.

### 3.3c What QML can actually reach — the context properties

**Correction to the A5 notes above:** the bridges were built and tested but not
registered with the engine, so QML could not see them. `shell.py` now exposes:

| Name in QML | Object | For |
|---|---|---|
| `Chat` | `ChatBridge` | unchanged |
| `Settings` | `SettingsBridge` | unchanged |
| `Permissions` | `PermissionsBridge` | the permission screen and activity log |
| `Confirm` | `ConfirmBridge` | the irreversible-action dialog |
| `AgentTrace` | `TraceBridge` | watching agents and teams work |
| `Schedule` | `ScheduleBridge` | scheduled jobs and the security review |

`AgentTrace`, not `Trace`, to keep it distinct from the core class. A test
asserts these names, so renaming one is a deliberate act.

### 3.3d `Schedule` — jobs and the security review (A6, A7)

| Member | Kind | Notes |
|---|---|---|
| `jobs` | Property, notifies `jobsChanged` | Maps: `id`, `name`, `action`, `when` (plain English), `nextRun`, `lastRun` (epoch seconds, 0 if never), `lastStatus`, `enabled`, `done`, `pausedReason`, `missed`, `running` |
| `warnings` | Property | Plain-language problems loading the schedule — show them |
| `history(id)` | Slot → list | Runs, newest first: `status` (`ok`/`failed`/`skipped`/`overlap`), `summary`, `late`, `trigger` |
| `pause(id)`, `resume(id)`, `remove(id)` | Slots | |
| `runNow(id)` | Slot | Starts a worker thread and returns at once |
| `findings` | Property, notifies `reviewChanged` | Worst first. Maps: `severity` (`critical`/`warn`/`info`), `code`, `title`, `detail`, `suggestion`, `capability` |
| `reviewSummary`, `lastReviewAt`, `criticalCount` | Properties | `"Not reviewed yet"` before the first review |
| `runReview()` | Slot | Runs the review now, off the UI thread |
| `criticalFound(int)` | Signal | **Raise something visible.** The point of the review is that critical findings are not left in a list |

The review never fixes anything itself. When a finding names a `capability`,
the natural action is a link to that capability on the permission screen, where
the person can revoke or narrow it. A paused job's `pausedReason` is written for
the person — show it verbatim.

A scheduled job that reaches an irreversible step asks through `Confirm` like
anything else — and if nobody answers within five minutes, it is refused.

### 3.4 `AuditLog` — the activity view

```python
from protege.core.permissions import AuditLog
events = AuditLog(path).read()   # list[Event]; malformed lines are skipped, not fatal
```

Refusals are logged as loudly as successes, and the pattern of what an agent
*tried* is the interesting part — so show denied entries, do not filter them
out. Values are redacted and truncated before they hit disk; the log rotates at
8 MB.

---

## 4. UI work this unblocks

In the order I would build it:

1. **Permission screen** — grouped by `cap.domain`, read/write as separate
   toggles, `leaves_machine` badge, scope picker driven by `ScopeKind`.
2. **Confirm dialog** — see §3.3. Nothing irreversible works without it.
3. **Agent trace view** — the 8-bit-space coding surface is the natural home.
   `TOOL_CALL` / `TOOL_RESULT` pairs as a timeline, `MESSAGE`+`to` as edges.
4. **Activity / audit log** — plain reverse-chronological list, refusals visible.

---

## 5. Rules that must not be broken

- **Nothing in `core/` may import a networking module.** `verify_offline.py`
  statically proves no networking import is reachable from the entry points and
  it runs as part of the suite. It also rejects `__import__()` and other dynamic
  imports, because they defeat the static check — I tripped this myself this
  session with `__import__("os").walk(...)`. Use plain import statements.
- **`model.cloud` is the only door to a cloud model**, and it is off by default.
  Do not add a fallback that silently reaches for one.
- **There is no `bank.write`.** Money cannot be moved because no capability
  exists to request it — that is the enforcement, not a policy default. There is
  a test asserting the catalogue contains no `bank.*` capability other than
  `bank.read`.
- **Deny by default.** No "allow all" switch, in the model or in the UI.

---

## 6. Not built yet (my next session, not yours)

- `core/agents/team.py` and `roles.py` — the research team and software team.
  `MESSAGE`/`to` on the trace exists for these but nothing emits it yet, so an
  agent-interaction view will render an empty graph today.
- `tests/test_agents.py`.
- Everything in Phases B–E of `PLATFORM.md`: second brain / Obsidian, browser
  and scheduler, connectors, voice.

---

## 7. Test state at handoff

Full suite, at the end of section A: **1311 passed, 2 skipped, 0 failed**, confirmed clean across repeated randomised orderings. `verify_offline.py` passes.

Two fixes this session worth knowing about, both recorded in `REBUILD.md`:

- **`__import__("os")` in `files.py`** defeated the offline verifier. Replaced
  with a plain `import os`.
- **An order-dependent test failure.** The suite was green on a fixed seed and
  red roughly one run in three under `pytest-randomly`. Cause: Tkinter parents
  any widget built without an explicit master to the first `tk.Tk()` in the
  process, `ProtegeWindow` is its own `tk.Tk`, so whichever test touched Tk
  first decided the default root — and destroying that window left
  `_default_root` pointing at a dead interpreter. A session-scoped autouse
  fixture in `tests/conftest.py` now claims the seat up front. The matching real
  defect: `_drain_events` rescheduled its 50 ms poll timer unconditionally, so
  it outlived `destroy()`; `destroy()` now cancels it.

One cosmetic residue: full-suite runs still print a few
`invalid command name ..._drain_events` lines to stderr from module-scoped
window fixtures tearing down late. It is Tcl chatter, not a failure, and it does
not appear when the UI test files run individually. Left alone deliberately —
if you see it, it is known and not something you broke.
