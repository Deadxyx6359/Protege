# Codex → Claude: one chat UI (2026-09-27)

Implemented the person's one-chat request against `rebuild` / `b6cba11`.
Read your September 26 handoffs 06 and 07, September 27 handoff 01, and the
one-chat contract in `docs/QML_BRIDGES.md`.

## Result

- There is one Chat destination, one transcript, one composer, and one global
  conversation list. Code and Research are grouped with Tools. Visiting either
  tool leaves the conversation and unsent draft intact, including during calls.
- The compact composer selector binds to `Chat.modes`, `Chat.mode`, and
  `Chat.setMode`. Auto remains the backend default. The adjacent label shows
  `Chat.intentLabel` and `Chat.routeLabel`; pinning during a reply does not
  relabel that reply or alter its route.
- Research progress uses `Chat.stage`, with wrapping for long search/read
  steps. The existing Stop action still calls `Chat.stop()`.
- The latest answer's Sources disclosure recognizes web, files, Drive, notes,
  documents, and conversations. Citation strings are plain text, never remote
  images or automatically opened links. It remains bounded and scrollable.
  Expanding it keeps the latest answer in view when following the transcript;
  a reader who has scrolled up is not pulled down.
- Backend-added Note and Correction lines remain ordinary reply content.
- Research opens Investigations directly, with its existing saved runs,
  editable task, sources, artifacts, and permission flow. Code retains project
  setup, software-team tasks, Git review/history, and VS Code access.
- Removed the SceneHost instance from Main. No landscape, space, abyss, or
  other pixel background runs in the app. Old scene source/assets remain in
  the repository for reference, unused by Main. The person will provide new
  pixel-design direction separately; no replacement has been invented.

## Backend boundary

Removed only Codex's uncommitted workspace isolation from conversation.py,
conversations.py, and chat.py, plus its backend tests and obsolete bridge-doc
section. Those files now match HEAD. In particular,
`git diff HEAD -- akira/ui/bridge/chat.py` is empty. Your routing, research,
source-note, cancellation, mode, and intent behavior is unchanged.

Deleted the untracked `tests/test_qml_workspace_chats.py`; its earlier handoff
2026-09-26-04 is historical and superseded by this one. No new bridge members
are required. Existing project changes and explicit New chat still start a
conversation; changing kind or visiting a tool does not.

## Validation

`tests/test_qml_one_chat.py` exercises the actual Main.qml at 100% and 150%
scale with fake model inference and a gated fake researcher. It covers the
keyboard selector, all four kinds, next-message pinning, intent/model labels,
one transcript across tools, each research stage, Stop, web/file source text,
hostile HTML-like filenames, and unmodified Note/Correction lines. Screenshots
were inspected in both themes, including the compact 900×600 window.

Updated existing navigation, history, investigation, research-flow, and voice
tests to reflect one chat. Voice tests at both scales confirm that tool visits
leave a call and conversation alive. Your committed software-team fixture is
preserved.

Full suite: `python -m pytest -q --tb=short` completed with 2,560 passing,
27 skipped, and two failures in the existing picture-preview checks (both
scales). The fake renderer was finished but Qt's inline-PNG decode still had
Image.Loading status; the test had assumed a fixed 40 ms was enough. Changed
only that test to await Image.Ready with a bounded five-second deadline.
`python -m pytest tests/test_qml_pictures.py -q` then passed both cases.
No application or backend changes were needed for those failures. Thus every
non-skipped check has passed across the full run and targeted rerun; the full
suite was not run a second time after the test-only timing correction.

The dedicated one-chat tests passed at both scales after the source-panel
scroll correction. Navigation, research/investigation, code tools, voice,
and plain-text checks also passed. No known failing checks remain.

`python verify_offline.py`: PASS (196 Akira modules, 69 QML/script files,
274 reachable external modules; informational unreachable-import notes only).

## Working-tree coordination

Earlier Codex UI work is still present: memory review, voice/widget, draft
review, pictures, minimal copy, and the settings-window geometry correction.
This handoff covers the one-chat integration rather than claiming those as
new backend work. No files were staged or committed by this turn, and no
Claude files were swept into a commit. The handoff index includes your missing
September 26-06, September 26-07, and September 27-01 rows, plus this handoff.

Your `Images.stop()` and `Place.clockNote` additions from September 26-07 are
acknowledged but not wired in this narrowly scoped one-chat pass.
