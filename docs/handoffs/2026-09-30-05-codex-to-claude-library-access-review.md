# Codex → Claude: Library access and UI review complete

Addressed the frontend follow-ups in September 28 handoff 01 and September 29 handoff 01.

## Changes

- `DocumentsView.qml`: **Your library / Back to files** remains available with a folder or preview open. Switching changes only presentation; the folder and selected document are preserved. File/folder pickers return to the file view, and adding library items opens the library so the result is visible.
- Document actions now wrap with a Flow below the title, preventing narrow-window header overflow. Add documents is the first primary action.
- Replaced the library's long explanatory paragraph with its project/personal scope label. Existing per-item metadata, removal confirmation and error/result messages remain.
- `AllowPrompt.qml`: shorter explanation while preserving the persistent read scope, revocation location, expiry and queue count. Buttons, default refusal and backend behavior unchanged.
- `SetupSheet.qml`: shorter introductory sentence; per-permission scope descriptions remain because they inform the user's decision.
- `SettingsSheet.qml`: removed the redundant paragraph teaching sidebar right-click. Bulk-delete count, pinned behavior, irreversible-action confirmation and Keep default remain.

## Reviewed without unnecessary changes

Chat menu already uses shared surfaces, spacing and destructive colors; mouse/keyboard behavior tests pass. Permission retention actions already use shared ActionButton/Badge styling; their labels were retained to avoid implying that Stop keeping revokes access or adds an expiry. FormRow descriptions stay hidden by design, consistent with the person's minimal-UI request.

Verification notes remain normal selectable Markdown reply text, including the bold Not checked label. No parsing/restyling added: deemphasizing these cautions could hide meaningful uncertainty, especially during streaming.

## Validation

- Library, chat menu, allow prompt, setup, one-chat tests: **15 passed**.
- Library plus general QML views tests: **3 passed**.
- Extended Library test to preserve selected preview as well as folder, then reran: **2 passed**, scales 100%/150%.
- `verify_offline.py`: **PASS**.
- Inspected screenshots of Library, permission prompt, chat menu and bulk deletion with the new palettes. Captures in `%TEMP%/akira-handoff-ui-review/`.

No backend contract changes, no commit/push. Full suite not rerun; these were targeted frontend changes. Shared tree contains earlier uncommitted work from both agents.
