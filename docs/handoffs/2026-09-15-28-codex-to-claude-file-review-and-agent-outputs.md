# File review and agent output access

Codex → Claude, 2026-09-15. Continues `9523909` after coordination handoff 27.
The latest handoff to Codex is still 16. This pass is frontend/UI; your pending
browser, network, capability, role, requirements and verification changes remain
untouched and excluded from the commit.

## Delivered

- Code review has a file-section selector, visible addition/removal counts and
  diff colors matching light/dark appearances. Full patch selection is retained.
  The source is still plain text, including literal HTML/image-like content.
- File labels handle quoted Git names, spaces, Unicode, renames, deletions and
  binary/mode-only changes. Unknown headers get a neutral label. These labels
  are display-only and are never converted into an action path.
- The review explicitly indicates a backend-truncated snapshot. Navigation uses
  only the existing snapshot; it does not issue another Git command or change
  the repository/index. Missing sections are not presented as reviewed.
- Interactive runs retain up to 24 file references from successful write/create/
  document-edit/spreadsheet-update tool calls. Denied writes produce none.
  References survive restart and repeat writes to one path update its entry.
- Research and task history show these files with their current path. Opening
  a reference offers a document/text preview or a VS Code action. Reading uses
  fresh, independent permissions; it is not granted by the earlier write.
  References from another project's run cannot be opened under the current
  project. Current file contents can differ from what the agent originally wrote.

## Implementation and constraints

New UI modules: `ui/diff_view.py`, `RunArtifacts.qml`, `ArtifactSheet.qml`.
Additive changes to Coding/Agents presentation bridges, run observer/archive,
Research/Code/history QML and Main wiring are documented in `QML_BRIDGES.md`.
There is no new core tool or policy, automated run, stage/commit/push action,
permission grant, filesystem write from the review, or inferred model-prose link.

Diff formatting follows Qt's supported syntax-highlighter access to the QML
text document. The wrapper must remain alive with its highlighter; the first
probe caught a borrowed-document lifetime issue, now fixed and tested across
file changes, review modes, theme changes and closing the sheet.
[Qt documentation](https://doc.qt.io/qt-6/qquicktextdocument.html).

The existing Git tool still caps each captured output at 20,000 characters.
Section counts cover only visible hunk lines. The optional `git_diff.file`
argument remains unwired; this UI does not treat parsed filenames as trusted
inputs or attempt to bypass the output cap. Future complete per-file retrieval
should use a structured Git manifest and literal pathspec handling.

Artifact metadata uses ToolResult.data.path for writes/creation and validated
absolute arguments for Office edits that do not return a path. No body is added
to history, and old version-1 records load with an empty artifact list. Supported
document extensions use the existing Documents reader; other files use the
existing VS Code tool. No native Word/Excel/PowerPoint launching was added.

## Verification

**214 tests passed in the combined regression run (117.65 seconds).** It covers
agent/team execution, presentation bridges, navigation, Research/Code/Documents,
Settings, accessibility, branding, text/network guards, Schedule and the shell.
The agreed checkpoint was reached at 90% weekly usage (49% of the current
five-hour window); the commit and push follow this verified state.

Focused tests cover real temporary Git repositories, unchanged index bytes,
zero tool invocations on section selection, malformed/unusual Git headers,
read denial/revocation, explicit editor launching (intercepted), confirmed versus
refused file writes, persisted output references and independent read grants.
The QML checks verify actual highlighter formats while retaining plain text,
file selection, nested output previews and returning to task history.

Screenshots are under the ignored local directory
`artifacts/scenes/ui-audit/code-output-sep15/`: 900×600 and 1440×900, both
appearances, 100% and 150% display scaling. All content and writes are isolated
fixtures. No real model, account, website or VS Code process was started by these
checks. GPU/native-editor performance remains a physical-device check.

## Next UI priorities

1. Search within saved conversations and investigations, plus a simple export
   path for findings. Source refresh/export needs explicit guarded tool wiring.
2. Consistent account/permissions setup and recovery states across the remaining
   legacy forms.
3. Memory provenance and scheduled-run detail, keeping saved task history
   distinct from second-brain ingestion.
4. Quiet-scene preferences, light-mode transitions and physical-device animation
   checks. Voice UI still needs the backend call/session contract.

Reopen Akira through the existing launcher to load the source changes. This file
is the report the user can give Claude; no external message was sent.
