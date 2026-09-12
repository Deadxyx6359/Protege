# The approved identity is in the UI, and long approvals now fit

Codex → Claude, 2026-09-12. Follows your
[welcome-back handoff](2026-09-12-16-claude-to-codex-welcome-back.md).

The interface now uses the approved portrait and an emerald interaction
palette. Your long-message confirmation concern is fixed: the entire summary
can be scrolled at 900×600 while both decisions stay visible. The next UI work
is ranked in [the review](../UI_AUDIT_2026-09-12.md).

## Changes in this pass

- `BrandMark.qml` and `qmldir`: the existing production PNG, loaded locally,
  sampled for small display sizes. No regeneration or changes to PNG/ICO files.
- `Sidebar.qml`, `ChatView.qml`: 36px sidebar mark, 64px greeting, 32px assistant
  avatar. New chat uses the shared ActionButton; the welcome panel is more
  legible over bright scenes. Error replies retain their error marker.
- `Theme.qml`: emerald in both appearances; contrast-adjusted danger red;
  stronger supporting copy; separate `textOnDanger`. `contrastText` now compares
  actual contrast ratios rather than using an inaccurate luminance cutoff.
- `ActionButton.qml`: optional icon, accessible activation, visible outer focus
  ring. `IconButton.qml`: labels/tooltips and keyboard activation. `NavRow.qml`
  and `TabStrip.qml`: keyboard activation and selection/focus semantics.
- `Composer.qml`: attachment action is hidden by default until a host provides
  a real flow; stop uses `textOnDanger`. `TabStrip.allowNewTab` is false in Main
  because the three current tabs are fixed modes.
- `Main.qml`: Everyday naming agrees with its tab. New chat / recent selection
  leaves a full-page tool so the selected conversation is actually visible.
- `ResearchView.qml`: honest guidance to the Research team in Agents for web
  research; greater panel opacity fixes grey-on-grey copy in light appearance.
  It still uses Chat, and does not pretend to call the research team itself.
- `ConfirmDialog.qml`: scrollable verbatim plain-text summary, visible overflow
  hint/scrollbar, fixed decisions, keyboard scrolling and contained tab order.
  Don't allow remains the initial focus, Escape refuses, outside clicks do
  nothing, and the next queued request starts at the top. No bridge change.

## Verification

**30 tests passed**:

```powershell
python -m pytest tests/test_qml_text_formats.py tests/test_qml_views.py tests/test_qml_branding.py tests/test_qt_guard.py -q
```

`test_qml_branding.py` is new and separate from your view tests. It checks
actual QML token contrast (4.5:1 on opaque surfaces and action states), loaded
logos, keyboard navigation, a roughly 5,000-character approval at 900×600,
verbatim text, scrolling to the end, contained tab order and Escape refusal.
`git diff --check` passed.

Rendered 36 isolated review captures across both appearances: every destination,
the five settings/project sheets, compact layouts, sample chat/code/error
content and long approvals. They live in ignored `artifacts/scenes/ui-audit/`.
No user conversations/accounts were loaded, no model was run, and no network
services or sending were exercised. Native Windows fonts resolve correctly;
offscreen screenshots need explicit font loading and aliases. GPU animation,
high-DPI layouts and all weather/season combinations still need a separate pass.

## Ownership and next steps

Only the frontend files above, the new test and the review/identity/handoff
documentation belong to this change. Your inbox work (`aeac40d`) and Gmail
sending (`36f12dd`) landed during it. Your verifier changes and other uncommitted
work were left untouched. No Python bridge or permission policy was changed.

The source art, production icons and earlier local design drafts are retained.
The historical exploration document is backed up in `scratch/akira-branding-history.md`;
`docs/branding/AKIRA.md` now describes the approved identity only. Old local
concept assets/prompts are not staged as part of this UI pass.

The user previously requested a handoff and a confident commit/push at 90–95%
usage. Usage reached 95% as this pass finished; the verified frontend files and
this handoff are being committed and pushed together on `rebuild`.

Recommended next pass: Documents/search, navigation and persistent project
context, then a source-aware Research workspace. Your public QML bridge
contracts remain the source of truth; request any needed backend additions
explicitly rather than embedding service logic in QML.

Index row: **23**.
