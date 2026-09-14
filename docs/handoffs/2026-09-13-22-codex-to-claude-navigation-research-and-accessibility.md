# Navigation, project context, research entry and accessibility

Codex → Claude, 2026-09-13. Continues the Documents checkpoint `610d3d1` and
[coordination handoff 21](2026-09-13-21-codex-to-claude-ui-context-coordination.md).
The user asked to keep working until the usage limit; this report is being
finished at the 90% checkpoint. Your browser/backend changes remain unstaged.

## Delivered

- One grouped sidebar: Workspaces, Library, Tools. Removed duplicate top tabs.
  `WorkspaceHeader` supplies the active project picker, explicit Manage action,
  New project option, global-permission labels, and all destinations when the
  sidebar is collapsed. Recent chats are labelled as across projects.
- Project switches begin a fresh chat and preserve unsent drafts per project
  in memory. Opening a saved chat restores its stored project; an unavailable
  project is explained and uses personal context. Project controls and recent
  opening are blocked while chat/agent work runs. New chat is disabled during
  a stream. These are UI safeguards, not changes to backend run isolation.
- `ContextSources` shows the actual `Chat.lastSources` / `lastContextNote` for
  the latest turn in a bounded, collapsible, scrollable plain-text panel. These
  are retrieval labels, not claims that every source was cited in the answer.
  No URLs or file paths are inferred from labels or automatically opened.
- Research prepares an editable research-team task; Code offers the same route
  to the software team. The current draft and project folder are carried over.
  Preparing never starts a run or adds a permission. Agents retains the real
  Start task button. Existing scripted local chat remains functional.
- Agents now uses a team/role dropdown, shows the task and result early, and
  puts the pipeline/tool list and detailed activity behind disclosures. Working
  teams still show their pipeline. Results identify their run/project context.
  Task input is read-only during a run and checks the existing 4,000-character
  limit before starting. Original run/confirmation logic remains in the backend.
- Keyboard switches, arrow/Home/End segmented choices, readable dropdown labels
  and accessible control names. Toggle now emits the requested value without
  overwriting its model binding. Existing rebinding handlers remain compatible.
- Shared sheets contain Tab/Shift+Tab focus and return to their trigger. A
  nested approval retains its own focus behavior and returns to the sheet when
  dismissed. Long sheet titles elide within the close button. Content clipping
  prevents scrolled controls painting over the header.

## Shared seam and ownership

Only `bridge/chat.py` changed on the shared Python seam, as announced in 21:
`conversationProject` exposes the existing field, and navigation clears stale
retrieval labels. The contract is updated in `QML_BRIDGES.md`. No core, router,
store format, permissions, network, browser or agent engine changes.

QML changes are the shell, sidebar/header, conversation/source panel, Research,
Agents, project sheet and shared form/focus controls. Additional changes are
four new test modules, the existing branding test's retired-tab assertion,
`tools/check_research_ui.py` (now supplies the complete isolated app context),
the UI audit, this report and the handoff index. Approved artwork is unchanged.

## Validation and limits

**97 tests passed in the final combined regression run**, covering
`test_chat_bridge`, `test_chat_ui_context`, `test_documents_bridge`,
`test_qml_documents`, `test_qml_navigation`, `test_qml_research_flow`,
`test_qml_accessibility`, `test_qml_branding`, `test_qml_text_formats`,
`test_qml_views`, `test_qt_guard` and `test_schedule_bridge`.
Checks pass for project/draft restoration, retrieval cleanup, literal
markup, bounded sources, editable team handoffs without execution, task length,
all eight collapsed-sidebar destinations, both themes, minimum-size controls,
keyboard focus cycling, controlled toggles and nested approvals.

The standalone scripted Research harness passes: real composer, streamed fake
backend, editable starters, saved conversations, workspace navigation and no
QML warnings. No model, real account, network or background service is started
by these checks. Visual captures use temporary config, synthetic content and
the actual QML window, at 900×600 and larger in both appearances:

- `artifacts/scenes/ui-audit/final-navigation-research/` — 38 overall captures.
- `artifacts/scenes/ui-audit/navigation-context/` — 8 project/header layouts.
- `artifacts/scenes/ui-audit/research-context/` — context, prepared tasks and Code.

Captures are ignored local artifacts. Offscreen software rendering is verified;
native file pickers, high-DPI/GPU behavior and actual model/tool success are not
newly certified. Drafts and run labels introduced here are in-memory only.

## Next

Research still needs structured source/path/preview metadata and persistent
run ownership to become a fully separate research workflow. Code still needs
the project/file/diff/review surface and VS Code integration. Settings/setup,
remaining form consistency, notifications/memory counts and scene scrims follow.
Please keep file/network rules in the core. Do not parse a citation string into
a filesystem action. The original UI audit remains the broader priority list,
with a dated progress section for this pass.

Index row: **28**. This is the file to give Claude; no external message sent.
