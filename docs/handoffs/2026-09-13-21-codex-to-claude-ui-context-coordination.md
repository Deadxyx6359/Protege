# UI context coordination

Codex → Claude, 2026-09-13. The user asked to continue frontend work until the
usage limit. Latest backend handoff is still 16; your uncommitted browser/network
files are left alone. Navigation UI now uses a grouped sidebar and persistent
project picker instead of duplicate top tabs. Verification is in progress.

Before editing the shared Chat bridge, the next small seam changes are:

- Expose the already loaded conversation's project as `conversationProject`,
  notified by the existing `titleChanged` signal. No new core/store fields.
- Clear `lastSources` / `lastContextNote` on new chat, successful conversation
  open, or deletion of the open conversation. These currently outlive the chat
  they describe; the UI is about to show them, so stale labels must not leak
  into a different conversation.

Please avoid concurrent edits to these portions of `bridge/chat.py` while this
pass is underway. Final contracts, tests and handoff follow. QML will coordinate
project switches/new chats and retain unsent drafts per project in memory.
Background work keeps the existing policies; selecting a project grants nothing.

Research will first surface the existing retrieval labels and provide an
explicit route to the existing research-team runner. No fabricated sources,
new backend agent framework, external service, or silent permission grant.
