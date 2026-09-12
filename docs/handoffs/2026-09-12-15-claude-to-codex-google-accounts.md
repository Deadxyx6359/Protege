# Google accounts, and one more sheet

Claude → Codex, 2026-09-12. Follows
[14](2026-09-11-14-claude-to-codex-the-views-that-were-missing.md). You are
still away. The person chose Gmail and Google Calendar for C5 and agreed that
the one network door may carry a sign-in; the backend is in PROJECT.md under C1
and C5. This note is the interface part, so you can review it.

## What I added

**`AccountsSheet.qml`**, opened from a new **Accounts** section in
`SettingsSheet` (signal `accountsRequested`, handled in `Main.qml` like the
others). Three parts:

- *The Google client*: whether the client file has been chosen, the steps in
  Google Cloud in a few lines, and a `FileDialog`. The file is sealed the
  moment it is chosen.
- *Connect an address*: the address, a switch each for Gmail and Google
  Calendar with what reading means, and whatever must be allowed first offered
  right there (`Accounts.missing`), beside what it allows. Connect is enabled
  only when nothing is missing. While signing in it says Google will call the
  app unverified, and offers Stop.
- *Connected*: each address, what it reads and since when, or why it must be
  connected again with Connect again; Disconnect asks twice.

The bridge is `Accounts`, documented in QML_BRIDGES.md.

## Requirements, and what is only a look

Keep these:
- Nothing secret is typed or shown. The only thing typed is the address.
- A permission is taken only on a press, and the grant is read fresh first:
  `Permissions.grant` replaces the whole list of addresses.
- The sheet says Google will call the app unverified. Without that, the person
  meets Google's warning page cold, mid sign-in.
- Disconnecting asks twice.
- Data-bound text is plain (rule 5).

The layout, the wording of the steps and the switches are yours.

## Tests

`tests/test_qml_views.py` drives the sheet: objectName `accountsSheet`, and the
functions `chooseClient`, `allow`, `connectNow`, `again` and `disconnect`. It
replaces the bridge's browser opener with a stand-in before it starts a sign-in,
so a test never opens the person's own browser. Keep that if you change how the
sign-in starts. `tests/test_accounts_bridge.py` covers the bridge itself.

## Also visible

A new agent, **secretary**, shows among the Agents chips. It reads mail and the
calendar and has no tool that changes anything.

The index row for this handoff is **21**.
