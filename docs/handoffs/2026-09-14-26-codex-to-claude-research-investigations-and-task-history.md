# Research investigations and persistent task history

Codex → Claude, 2026-09-14. Continues `451c87d` after coordination handoff 25.

## Delivered

- **Research stays in Research.** Conversation and Investigations are separate
  tabs. The existing team entry prepares an editable question using the current
  composer and project folder. Starting is explicit, uses existing grants and
  confirmations, and never happens on navigation. Unsent investigation drafts
  are retained per project in memory.
- **An investigation owns its result.** Saved questions, original project,
  timestamps, outcome and four actual team stages remain linked when another
  task starts. Leaving the view does not stop a run. Stop, incomplete and
  interrupted states are distinct from completion.
- **Gathered material has provenance.** Read-tool results supply source cards:
  search snippets, pages actually read, files read and local indexed excerpts.
  Previews are selectable plain text. No source action is inferred from model
  prose, no preview triggers another read, and these cards do not claim citation
  or verification. Revoked/expired permissions and project changes invalidate
  source previews; late old-context bodies are discarded.
- **Code and Agents retain work too.** Code's clock button opens software task
  history. Agents has Task history, with optional all-project viewing. Results
  show original ownership and model assignments captured at start. Saved runs
  can be removed explicitly without touching project files or audit records.
- **Visual and keyboard polish.** All new surfaces use the existing emerald
  palette and typography; the approved portrait and artwork stay intact. Reading
  remains quiet. Compact layouts, focus reveal, source-sheet focus containment
  and return, and 100%/150% scaling are exercised. Research cards use rounded
  Rectangles because the software renderer let Shape-based cards paint outside
  nested scroll clips.

## Shared seam and ownership

`AgentsBridge` adds run metadata, source previews and history without changing
existing start/stop/result APIs. Each interactive worker gets its own Trace and
forwards events to the shared Trace; scheduled events cannot enter its run
record. `ObservedRegistry` delegates available/invoke unchanged to the existing
registry, then observes successful structured read results. It makes no policy
decision for execution and does not add tools or perform a second invocation.

Shell supplies project identity, resolved model labels and a `RunArchive`.
Its source invalidation connects to the same global/project signals used by
Documents and Coding. Full API and field limits are in `docs/QML_BRIDGES.md`.
No core, model, network, scheduler or permission policy was edited by Codex.

Your pending roles, capabilities, browser/web, netguard, requirements, verification
and related test files remain excluded from this commit. Historical untracked
branding studies are also excluded. No external message was sent to Claude;
this file is the handoff the user can provide.

## Persistence and limits

- UI archive: `config_dir()/investigations.json`, version 1, latest 60 interactive
  runs across all teams, 12 MB cap. Writes occur on workers, serialized and
  atomically replaced; Windows sharing violations get a short bounded retry.
- The archive whitelists task, final answer, member/model/status metadata,
  source references and the last 80 tool/handoff labels, including failure flags.
  It stores no tool arguments, intermediate model messages or separate source
  bodies. Final answers can naturally quote source text, like saved conversations.
- Tasks cap at 4,000 characters; saved answers at 60,000. Each run has up to
  32 source references. Preview bodies cap at 30,000 characters; up to four
  recent runs' bodies stay in memory. Restart, grant change or project switch
  can leave a saved reference without a preview; the UI explains this.
- A start marker is saved before generation, then the finished record. There
  is no checkpoint/resume of intermediate agent work. An interrupted process
  leaves an interrupted investigation on restart. Corrupt archives are kept
  intact and further writes fail visibly; current-session results remain usable.
- History is presentation storage, not second-brain ingestion or an agent memory.
  Scheduled runs remain in Schedule. No source refresh, export, automatic fact
  checking, document editing or concurrent-agent execution was added.

## Validation

**207 tests passed** in the combined regression run (86.61 seconds), covering
core agent/team behavior, Agents/Chat/Documents/Coding bridges, navigation,
Research/Code/Settings layouts, accessibility, branding, text/network guards,
Schedule and existing shell checks. After the last failure-label and interruption
polish, **25 focused tests passed** again.
The standalone `python tools/check_research_ui.py` also passed its original
conversation, editable-starter, streaming, saved-inquiry and appearance checks.
The user-requested commit/push checkpoint was reached at 90% primary usage.

The new unit checks exercise run isolation from scheduled trace events,
project/model ownership after subsequent runs and restart, real permitted
temporary-file reads, denied reads, snippet/page distinction, redirect scopes,
revocation/expiry, late publication, deletion, archive caps, corrupt-file
preservation and failed-save feedback. QML lifecycle checks start a scripted
team, navigate away, return to the result, preview literal markup safely, switch
projects with draft restoration, and recover/delete Code results through Agents.

Visual evidence uses the actual QML shell with isolated settings and fixture
content, at 900×600 and 1440×900, dark/light, 100%/150%. Local screenshots are
under `artifacts/scenes/ui-audit/research-investigations/` and
`artifacts/scenes/ui-audit/research-entry-sep14/` (ignored). No real model,
website, account, live weather or background service was used. GPU animation,
hardware latency and long-running real-model quality are not established by
these offscreen checks. Reopen Akira through its existing launcher to load the
source changes; no installer rebuild is needed.

## Next UI work, in order

1. File-specific Code review and a clearer path from agent-produced artifacts
   to the project file/document preview.
2. Search inside saved conversation and investigation content; Research exports
   and explicit source refresh would need additional guarded tool wiring.
3. Consistent account/permission/setup forms and recovery states. Preserve the
   backend's grant and confirmation boundaries.
4. Memory provenance and readable scheduled-run detail; avoid presenting history
   as automatically indexed memory.
5. Scene preferences/light-mode transitions and physical-device animation checks.
   Voice UI remains dependent on a working backend call/session contract.
