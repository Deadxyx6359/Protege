# Workspace conversation isolation — Codex to Claude, 2026-09-26

User reported that switching Everyday to Code kept the same chat. Main.qml
previously only changed the view; all three workspaces shared Chat.messages.

## Fix and shared seam

This required a small additive change beyond QML: Conversation.workspace is
persisted in ConversationStore. Legacy/missing/unknown workspace values read
as `chats`. The bridge exposes `workspace` and `switchWorkspace(name) -> bool`;
docs/QML_BRIDGES.md now describes them. No model, routing, tools, permissions or
backend workers were changed.

ChatBridge keeps a live Conversation per project/workspace, preserving the
current one before navigation. Switching saves it, restores the target thread
or starts an empty one, and resets source previews. New chat stays in its
workspace; deleting a thread invalidates its cached session too. Switching is
refused during an active turn. QML additionally refuses during voice calls.

Main.qml stores unsent composer text per project/workspace and returns to the
saved workspace when opening history. Visiting a tool page does not switch the
active chat. Voice's Open chat returns to its actual workspace. Existing
project-change behavior (new chat plus restored project draft) is retained.

Recent-history search remains global. Legacy chats cannot be automatically
classified as coding/research because their old files did not record that.
Unsent text and the current-thread-per-workspace cache last for this app session;
saved conversations retain their workspace across restarts.

## Regression coverage

- Real QML navigation: three distinct transcripts and drafts, return trips,
  tool-page detours, New chat isolation, saved chat ownership, project isolation
  and active-turn guard.
- Real voice UI regression: cannot switch to Code during a call.
- Model boundary with a fake backend: Code's generation prompt contains no
  Everyday messages; cached deleted chats never reappear.
- Store round-trip and backward compatibility for workspace metadata.
- Offline audit passes; no real model loading, account or microphone used for
  these regression tests.

## Full-suite findings and follow-up

Initial full run: 2,467 passed, 27 skipped, five failures (263 seconds).
The five were corrected and all 31 tests in dialog geometry, Research lifecycle,
workspace navigation and text-format validation then passed:

- Two pre-existing Tk Settings geometry failures: the scrollable assembled-
  prompt viewer requested 18 rows, forcing the notebook above the screen cap
  and clipping seven pixels. Its minimum request is now 12 rows and it still
  expands to fill remaining space. Save fits without enlarging the window.
- Two Research lifecycle assertions expected composer sharing. They now check
  that the explicit team handoff receives the original task while Research's
  separate chat composer stays empty.
- Schedule's new waiting-count label lacked explicit PlainText. Added it.

Final full rerun: **2,473 passed, 27 skipped, zero failures**, 262 seconds,
using `python -m pytest --tb=short`. This includes the additional model-prompt
isolation regression. The full suite exercised installed Whisper model tests;
the new workspace tests themselves use seeded messages or fake generation.
No test skips were added by this change. Offline audit and whitespace checks
also passed. Changes remain local and uncommitted.
