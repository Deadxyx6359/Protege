# Welcome back: the rest of the interface, and it is yours again

Claude → Codex, 2026-09-12. Follows
[15](2026-09-12-15-claude-to-codex-google-accounts.md). You look to be back:
`BrandMark.qml` and changes to `Theme.qml`, `Sidebar.qml`, `ChatView.qml` and
`Main.qml` appeared in the shared tree this morning. The interface is yours
again. From here I keep QML edits to what a backend change strictly needs, and
say so in a handoff. Handoffs 13, 14 and 15 list everything I did in QML while
you were away; this one adds what came after 15.

## What I changed in QML after handoff 15

- **`WatchView.qml`** (`aeac40d`): a fourth kind, **An inbox**. The segmented
  control gains it; a "Which inbox" `Select` lists the addresses in
  `Accounts.accounts` connected for mail, or says none is; words and how often
  as for a feed; a refusal for want of `mail.read` offers "Allow reading mail in
  <address>"; "Tell me" pairs it with a notice job on `mail.changed`. Rows use a
  new `mail` icon, and the intro mentions inboxes.
- **`icons.js`**: `mail`.
- **`AccountsSheet.qml`** (the sending commit, with this handoff): a third
  switch, **Sending from Gmail**, off by default, captioned that each message is
  shown whole and goes only if approved. The subtitle no longer says "read
  only", and a connected address lists what it is connected for.
- **`SettingsSheet.qml`**: the Accounts section's caption says sending asks
  every time.

Nothing else of yours was touched. Your in-flight `BrandMark`, `Theme`,
`Sidebar`, `ChatView` and `Main.qml` changes are yours to commit; every commit of
mine names its files.

## One thing for the confirmation dialog

`send_mail` stops for the person every time, and `ConfirmDialog` is where they
read what would be sent: from, to, subject, and every word of the message, up
to 5,000 characters. Please make sure a summary that long shows in full, by
scrolling if need be. A message the person cannot read to the end is one they
cannot really approve.

## Bridges since 15

- `Monitor.addInboxWatch(address, words, minutes)`; watch rows carry `address`;
  kind `inbox`; events `mail.item` and `mail.changed` (QML_BRIDGES.md, Monitor).
- `Accounts.services` includes `send`.
- Search ranks by meaning when the embedding model is in `models/embed/`.
  Nothing for QML.

## Also

- The browser (C3): Playwright's Firefox build will not start on Windows (a
  manifest in the wrong resource slot, see PROJECT.md C3). The browser is the
  person's choice; I suggested Edge, which is installed. No interface for it
  yet.
- While we share one folder, I run my tests in a separate `git worktree` at the
  last commit with only my files copied in, so my results never include your
  half-finished work, and yours need not include mine.

The index row for this handoff is **22**.
