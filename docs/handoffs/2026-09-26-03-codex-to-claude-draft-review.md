# Content draft review — Codex to Claude, 2026-09-26

Read your latest handoff index: training adapters (47) remains latest. This
pass implements the content-review part of handoff 44 using Drafts as-is.
No backend files changed.

## Delivered

- Schedule now has a Content drafts card with waiting count and Review drafts.
- DraftsSheet has title/job/destination search, waiting/all filters, full
  editable plain-text draft, original brief, and selectable critic review.
- Save changes persists through Drafts.edit. Closing the sheet retains pending
  edits in this app session; switching drafts requires Save or Reset first.
- The full target is displayed immediately above Publish in the same block.
  Email uses an explicit "Publish · send email" label. Publish is invoked only
  on that button press. No publication occurs on opening, editing or schedules.
- Publication failures remain visible and offer Review permissions. That opens
  the existing permission editor; no grant is added or inferred automatically.
  Return through Schedule to retry. No second publication confirmation dialog.
- Successful publication displays its outcome and removes publication actions.
  Discard uses a second inline press and writes nothing to the destination.
- Editor prevents saving/publishing over the backend's 60,000-character limit.
- Scheduled-job buttons sit below the job identity; run summaries now expand.
- Sheet's scroll surface uses a render layer to stop text bleeding over its
  header during scrolling with Qt's software renderer.

## Validation

34 passed: draft UI (100%/150%), settings, keyboard accessibility, voice UI,
and pipeline backend. 23 passed: QML views and schedule bridge. Screenshots
inspected in light/dark at 900 x 600; local ignored captures in
artifacts/scenes/ui-audit/drafts-sep26/.

The UI test uses real DraftStore, tool registry and policy, publishing only
into a pytest temporary directory. It checks literal HTML-like content stays
plain text, retained edits, save, refused publication, explicit granted retry,
destination visibility beside Publish, final outcome and two-press discard.
No email or external account used. git diff --check passes.

## Remaining

Pipeline creation UI (brief, schedule, read scopes and target) is still needed;
this pass exposes drafts from already configured pipelines. No creation button
pretends that flow exists. Next priorities remain Images/Drawing previews and
browser confirmation pictures, followed by pipeline creation and training UI.
