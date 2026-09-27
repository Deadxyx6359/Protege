# Claude → Codex: changing and deleting chats

The person asked for ways to delete or change their chats, from Settings and by
right-clicking a chat in the side list. The backend is done and committed; the
interface is yours. The contract is in `docs/QML_BRIDGES.md`, under "Changing
and deleting chats — 2026-09-27". Read your handoff 04 (Library and Tools); I
did not touch any of its files.

## What the bridge now does

- `Chat.recents` entries also carry `pinned` and `project`. Pinned chats come
  first, then the most recent. History search results carry them too.
- `renameConversation(id, title)`, `pinConversation(id, pinned)` and
  `moveConversation(id, projectId)` return `""` when done, or a sentence
  saying why not. Renaming, pinning or moving a chat does not move it down
  the list.
- `deleteConversation(id)` is still there for one chat. `deleteConversations(ids)`,
  `deleteAllConversations(keepPinned)` and
  `deleteConversationsOlderThan(days, keepPinned)` return how many chats were
  deleted. `countConversations(days, keepPinned)` returns how many a bulk
  delete would take, before it happens (`days` 0 counts all).
- None of these ask `Confirm`. They are the person's own actions on their own
  files, taken in the interface. Deletes cannot be undone, so the interface
  asks first (below).

## Please build

### 1. A right-click menu on each chat in the sidebar

The chat rows are the `NavRow` repeater over `root.filteredRecents` in
`Sidebar.qml` (around line 244). Add a context menu, opened by:

- a right-click;
- the Menu key or Shift+F10 on a focused row;
- a press-and-hold on touch.

Keep the menu minimal, in this order:

1. **Rename…** Edit the name in place, or open a small field. Enter saves and
   Escape cancels. Call `Chat.renameConversation(id, text)`. If it returns a
   sentence, show it beside the field and keep the field open.
2. **Pin / Unpin.** The label follows `modelData.pinned`. Call
   `Chat.pinConversation(id, !modelData.pinned)`.
3. **Move to project ▸** A submenu with "No project" and then
   `Projects.projects`, with a check on the one it is filed under
   (`modelData.project`). Call `Chat.moveConversation(id, projectId)`.
   - When the moved chat is the open one (`id === Chat.conversationId`),
     switch to that project the way `openRecent` in `Main.qml` does:
     remember the draft, call `Projects.openProject(...)`, and keep
     `restoringConversation` so the switch does not start a new chat.
   - Disable the item for the open chat while `Chat.busy`. The bridge refuses
     that case anyway ("Wait for the reply to finish first.").
4. A separator, then **Delete…**, which opens `ConfirmDialog`. Say which chat
   and that it cannot be undone, for example: Delete "Garden plans"? This
   cannot be undone. On yes, call `Chat.deleteConversation(id)`. Default the
   focus to Cancel.

Show a small pin mark on pinned rows. A thin divider between the pinned rows
and the rest is optional, if it stays quiet. The menu works the same on
search results, since those rows carry the same fields.

### 2. A Chats section in `SettingsSheet.qml`

- **Delete old chats.** A choice of 7, 30, 90 or 365 days, and a Delete
  button. Before asking, call `Chat.countConversations(days, keepPinned)` and
  put the number in the question, for example: Delete 12 chats not used in 30
  days? This cannot be undone. Disable the button when the count is 0, and
  say "No chats that old."
- **Delete all chats.** The same, with `days` 0 and
  `Chat.deleteAllConversations(keepPinned)`.
- **Keep pinned chats.** A checkbox shared by both, on by default.
- After either delete, say how many went, using the returned number.

One confirmation for a bulk delete is right, provided it states the count.
Do not add a "don't ask again" to any of these.

### Things to keep

- A new, empty chat cannot be renamed, pinned or moved. The bridge returns
  "Say something in the chat first; an empty chat is not kept." Disabling the
  items for it is fine.
- If the open chat is deleted, one at a time or in bulk, the bridge starts a
  new empty one, as `newChat` does. The chat that is still answering is left
  out of bulk deletes.
- Every action refreshes `recents`, so the list redraws on `recentsChanged`.
- No new permissions or grants. Nothing leaves the machine.

## Tests to add on your side

- The menu opens by right-click and by keyboard, and Delete asks before it
  deletes.
- Rename shows the returned reason.
- Moving the open chat switches the project and keeps the draft.
- The Settings bulk delete states the count and is disabled at 0.

## Verified here

- `tests/test_chat_manage.py` has 17 bridge and store tests: renaming keeps the
  place in the list, the open chat renamed before its first reply is saved,
  pin order, move, a refused move while answering, deletes by ids, all, by
  age and keeping pinned, the open chat cleared, and the answering chat
  spared.
- The full suite and `verify_offline.py` ran in a clean worktree at this
  commit (see the commit message).
