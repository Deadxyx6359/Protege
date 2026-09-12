# Sidebar search now works

Codex → Claude, 2026-09-12. Continues
[the branding and UI review](2026-09-12-17-codex-to-claude-brand-and-ui-audit.md),
which was committed and pushed as `9c3457e` on `rebuild`.

After the user asked to continue, I completed a small follow-up from the
review: `Sidebar.qml` now filters project names and recent conversation titles
instead of presenting an inert search field.

- Case-insensitive substring matching, with surrounding whitespace ignored.
- Uses the existing project/recent arrays and updates when they change.
- During search, unrelated navigation rows are hidden so results are clear.
- Enter opens the first match; choosing a result clears the filter.
- Escape and the labeled clear control in `SearchField.qml` reset it.
- An explicit empty state appears when no names match.

This is a local name filter only. It does not search message/file contents,
load older conversations, scan folders or make any network requests. Full
document and conversation search remains in the ranked UI review.

Files: `Sidebar.qml`, `SearchField.qml`, `tests/test_qml_branding.py`,
`docs/UI_AUDIT_2026-09-12.md`, this handoff and the handoff index. No bridges,
policies, backend files or source artwork changed.

**31 tests passed** across `test_qml_text_formats.py`, `test_qml_views.py`,
`test_qml_branding.py` and `test_qt_guard.py`. The added regression covers case
and whitespace handling, matching projects/chats, live model updates, no
results and Escape clearing. The complete pass was rendered again with two
additional result/empty-state screenshots (38 total), using isolated synthetic
data in ignored `artifacts/scenes/ui-audit/after/`.

The latest prioritized list is [UI_AUDIT_2026-09-12.md](../UI_AUDIT_2026-09-12.md).
Documents, navigation/project context and the real Research workspace are next.

Index row: **24**.
