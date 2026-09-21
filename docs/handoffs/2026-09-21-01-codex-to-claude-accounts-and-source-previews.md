# Accounts by provider, and usable browser source previews

Codex → Claude, 2026-09-21. Follows handoff 31. Changes are in the working
tree on `rebuild`; not committed or pushed in this pass.

## Accounts UI

`AccountsSheet.qml` now shows Google, Canvas and Banks as keyboard-accessible
segments, using the existing theme and controls. Only the selected provider's
forms are shown. Google setup instructions expand on demand; its client-file
and service-selection steps have separate headings. Service descriptions still
come directly from Accounts. The former generic permission caption incorrectly
said sending/event-changing services only read; it now refers to each service's
actual description.

Connection feedback appears at the top, labelled with its originating provider,
even if an asynchronous result arrives while another provider is selected.
Sections and new feedback return the sheet to the top. `Sheet.scrollToTop()`
is the only shared component addition. Settings counts Google accounts, Canvas
sites and bank connections rather than describing all connections as Google.

Token fields remain password fields, gain accessible labels, and clear on
submission as before. Closing the sheet now also clears unsubmitted Canvas and
SimpleFIN tokens. Disconnect still takes two presses; switching providers or
closing clears its armed state. No Accounts bridge or permission API changed.

## Research and storage follow-ups

- `run_sources.py` no longer treats browser-reported asset hosts as additional
  page-preview grants. The original tool scope and final destination host are
  both checked. The regression covers refused redirects, a subsequent permitted
  fresh source, and revocation clearing a visible preview.
- `run_archive.py` uses `akira.core.files.replace` instead of its separate,
  shorter Windows sharing-violation retry loop. Archive format is unchanged.

## Validation

49 tests passed in 38.49 seconds across investigations, shared file replacement,
Accounts bridge, and QML accounts/settings/links/sheets/text formats/accessibility/
views/investigations. `python verify_offline.py` passed; `git diff --check` passed.

The new `tests/test_qml_accounts.py` exercises real mouse and arrow-key section
selection, provider-labelled plain-text asynchronous errors, password masking,
and secret clearing on close. It renders all three sections in dark and light
at 900×600 and 1440×900, at 100% and 150% scale. Screenshots are local ignored
artifacts under `artifacts/scenes/ui-audit/accounts-sep21/`; inspected compact
Google, compact banking, and larger Canvas screenshots. No real sign-in, bank
connection, email, browser launch or model download was performed.

## Coordination / next work

Backend files changed during this pass: `core/agents/roles.py`,
`core/tools/builtin/__init__.py`, new `core/phone.py`,
`core/tools/builtin/texts.py`, and `tests/test_phone.py`. Left untouched.
Earlier untracked branding explorations are also untouched.

Next UI priorities remain saved-result/conversation search, memory provenance,
and scheduled-run detail. Drive/Canvas research source cards and the hand-over
window banner are not implemented here. Voice UI still needs the backend
session contract. The Google tab scrolls on compact windows; provider tabs are
in the scroll content, not pinned to the sheet header.
