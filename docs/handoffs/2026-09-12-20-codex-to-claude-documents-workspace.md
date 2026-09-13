# Documents is now a working workspace

Codex → Claude, 2026-09-12. User asked to begin the ranked UI backlog, then
asked to continue. This completes a bounded Documents browsing/reading/search
pass after [the seam coordination note](2026-09-12-19-codex-to-claude-documents-coordination.md).
Usage reached the user's 90% handoff checkpoint during implementation.

## Delivered

- Documents has its own full-page view; it no longer falls through to chat.
  The composer is hidden there. The approved logo and emerald/neutral theme
  remain shared with the rest of Akira; no new artwork or backend edits.
- Native folder/file pickers, project-folder and permitted-location shortcuts,
  structured folder rows, Up, Refresh, immediate file-name filtering and real
  indexed content search through `search_documents`.
- Read-only text previews for DOCX, XLSX, PPTX, PDF, Markdown and TXT through
  the existing readers. Legacy Office files show the existing conversion
  explanation. File type/size/date/location, selectable text and Copy path.
- A quiet two-pane layout at larger sizes; file/preview navigation with
  Back to files at 900×600. Dark and light appearances; keyboard activation
  for file rows and existing shared controls. Plain text throughout.
- Explicit loading/cancel, empty-folder/search/refusal states, permission
  sheet access. Choosing a path never grants access. No external Office app
  launch, editing, upload, automatic folder scan or model call.

## Shared seam

Added `akira/ui/bridge/documents.py`, exported through `bridge/__init__.py`,
registered as `Documents` in `shell.py`. Full API and limits are recorded in
[QML_BRIDGES.md](../QML_BRIDGES.md#documents).

Existing tools keep format parsing, policy enforcement and index maintenance.
The adapter only builds structured list metadata and translates results for
Qt. It checks the effective global/current-project policy on use and again
before publication. The worker is serial, with one replaceable pending request.
Cancellation/project changes discard late results. Global/project grant changes
clear displayed data; a one-second check also handles expiry. Individual text
search passages are checked again on arrival, even if the broader docs grant
still exists. Log write failures show an error and leave the worker alive.

Paths are local-only in this workspace: reject remote URLs, UNC paths and
linked locations before resolution; don't follow junctions in list metadata.
Folder listing is bounded to 400 rows / 4,000 scanned entries. Plain-text
previews cap at 200 KB before the existing reader, which otherwise reads before
truncating. Office/search limits remain the backend's. Cancel does not interrupt
a parser already running, but its output is discarded; daemon work cannot hold
app shutdown open on its own. Content search may update the existing local index.

`preview_text()` strips only the exact known reader envelope (path and tool
line numbers), never user document lines or parsed path metadata. An unknown
envelope is displayed intact. A future structured `data.text` from the two read
tools would remove this presentation coupling; please preserve truncation notes.

## Validation

69 tests passed across:

```powershell
python -m pytest -o addopts='' tests/test_documents_bridge.py tests/test_qml_documents.py tests/test_qml_text_formats.py tests/test_qml_views.py tests/test_qml_branding.py tests/test_qt_guard.py tests/test_schedule_bridge.py -q
```

A final disk-full/log-failure regression was added; all 16 Documents bridge
tests then passed. **70 distinct tests passed across the final two runs.**
Coverage includes all four modern document formats, literal markup, separate
file/document grants, scope boundaries, local URLs, large/missing files,
cancelled/superseded work, real indexed passages, final permission rechecks,
project/revocation wiring, keyboard file navigation, compact layout, and QML
warnings. No app-wide full backend suite claim: Claude is changing those files.

Twelve captures from the real QML window cover empty, list, preview, content
search, refusal and compact states in both appearances, using synthetic files
and temporary config. Saved locally (ignored):
`artifacts/scenes/ui-audit/documents/`. Headless software rendering with explicit
Windows font registration; this does not certify GPU/high-DPI or native file
picker appearance. No real mailbox, model, weather or scheduler was started.

## Ownership and next work

Files in this checkpoint: `DocumentsView.qml`, `Main.qml`, `Akira/qmldir`,
`bridge/documents.py`, `bridge/__init__.py`, `shell.py`, two new Documents test
files, the bridge contract, UI audit and handoffs/index. Claude's dirty browser,
netguard, capabilities, agent roles, requirements and related tests are left
unstaged. Old untracked branding concepts are also excluded.

The UI audit now records Documents as delivered for browsing/reading/search.
Remaining UI-01 work: conversation-content search, richer document previews and
reviewed editing/save flows. OCR, visual page rendering, spreadsheet
editing, content-search indexing performance and Office application launching
are not newly implemented here. Next design priority remains simpler navigation
and clearer project context (UI-02), followed by a real Research workflow.

Index row: **26**. This file is the report to give Claude; no external message
was sent. Commit/push checkpoint follows successful verification on `rebuild`.
