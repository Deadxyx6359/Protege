# Codex → Claude: Library, Tools, and agent activity

The person asked to merge all tool destinations into one tab, merge Documents
and Memory into one tab, keep the interface minimal, and show each agent's
current activity. They explicitly authorized backend work where needed and
asked me to read your updates and leave this handoff.

Read your September 27 handoff 03, including the updated answer-source
semantics. The existing source UI remains compatible. Your backend changes
and in-progress knowledge tool work have been left alone.

## Interface

- Sidebar and collapsed navigation now offer only Chat, Library, and Tools.
- Library contains Documents and Memory. Tools contains Agents, Code,
  Research, Watching, and Schedule, behind one compact segmented control.
- Each section remembers its last page. Existing deep destinations, notices,
  team preparation, and project scope still resolve to the correct page.
  Visiting a section leaves the chat, call, and unsent draft intact.
- The agent page lists every registered role in a compact responsive roster.
  It shows Idle, Waiting, Thinking, tool use, Done, Stopped, Failed, or Not run.
  During interactive work, the edit form gives way to the current task and
  roster; Stop stays at the top. Detailed activity remains optional.
- Pixel backgrounds remain absent. No replacement art was introduced.

## Small backend presentation change

`TraceBridge.activity`, notified by `activityChanged`, exposes the latest
short state by agent name: `{label, at, working}`. This includes scheduled
agents, which publish to the same trace but have no `Agents.currentRun`.
It contains no task text, tool arguments, or tool results. Repeated Thinking
tokens do not repeatedly notify this property; `at` marks the state event.
Completed entries are bounded; active entries survive trace scrollback
eviction. `clear()` clears the record and completed statuses but preserves
ongoing activity rather than pretending a scheduled agent stopped.

The roster combines this with existing `Agents.currentRun.states` to show
interactive waiting and terminal states. Agent execution, model selection,
permissions, and scheduling are unchanged. `docs/QML_BRIDGES.md` documents
the added property and the clarified clear behavior.

Statuses are the latest observed state per role, not separate cards per
concurrent invocation of the same role. The existing trace identifies roles,
not globally unique run IDs; no new execution IDs were invented in the UI.

## Verification

Focused tests cover navigation, remembered pages, all agents, state changes,
stopped/failed/unused agents, new-run reset, and scheduled activity at 100%
and 150% scale. Screenshots inspected in light/dark at 900×600 and 1440×900.
Bridge tests cover privacy of the status map, ongoing work after Clear,
scrollback eviction, and attachment to a fresh trace.

Validation completed:

- Focused trace/permission/section tests: 34 passed, including both UI scales.
- Broader QML selection: 51 passed initially. Five branding fixture errors
  came from its obsolete Research sidebar lookup; updated it to Tools.
  One application-context test hit the shared worktree while your shell was
  passing `project` and the loaded Researcher constructor still lacked it.
  Your current files now agree; I did not modify either file.
- Rerun of all affected checks plus the latest trace, section, and view tests:
  11 passed. No known failing check remains from this verification.
- `python verify_offline.py`: PASS, 196 Akira modules, 70 QML/script files,
  274 reachable external modules.
- `git diff --check`: clean.

Checked handoffs again before finishing: 03 remains your latest. No files
were staged or committed by this turn. Only trace.py was changed under the
backend bridges; your shell.py, agents.py, research/recall and knowledge work
was preserved. The shared bridge reference has only the activity/clear
contract edits from me.
