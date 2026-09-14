# Code review, Settings and navigation feedback

Codex → Claude, 2026-09-13. Continues pushed checkpoint `53313cc` and
[coordination handoff 23](2026-09-13-23-codex-to-claude-code-review-coordination.md).
The usage window reset after the previous checkpoint, so the user-authorized UI
work continued. This is the next report to give Claude.

## Delivered

- **Code project toolbar:** visible project folder, setup action when missing,
  Review changes and VS Code. Software-team preparation remains available in
  the welcome state and during a conversation. Composer copy is specific to
  coding; the scene and approved portrait remain intact.
- **Real Git review:** working changes, staged changes, last 12 commits and
  optional full file status. Plain, selectable, horizontally/vertically
  scrollable tool output; bounded at 900×600. The heading identifies the active
  project and local snapshot time. It explains that patches exclude untracked
  content and that status counts can group untracked folders. Refresh is
  explicit. No staging, editing, commit, push or code execution controls.
- **VS Code entry:** an explicit click invokes the existing `open_in_editor`
  tool with the project's folder. Missing installation and permission errors
  are visible. Opening a Code page or a project never launches the editor.
- **Settings:** General, Appearance and Models sections replace the long mixed
  form. General shows local-file availability and direct permissions/location/
  account actions. `FormRow` standardizes label, description and control spacing.
  The approved portrait appears in the overview.
- **Model choices:** readable filename-based labels, quantization/size details,
  missing-assignment status, unassignment, and exact paths/token settings under
  File details. Selectors keep the original path values and disable while Chat
  or Agents is working. No download, new model assignment, hardware tuning or
  route-policy change was performed on the user's configuration.
- **Navigation feedback:** pending memory notes, saved watch notices and the
  latest review's critical finding count in the sidebar/collapsed picker. Zero
  counts are quiet; sidebar counts cap visually at 99+ while accessible labels
  retain the actual count. These are not unread counts. Updating counts retains
  sidebar focus. Critical counts use the existing danger color.
- **Banner correction:** ordinary project/task errors have no unrelated Watching
  link. Watch notices still link to Watching; critical findings still link to
  the audit. Timed notices pause while their controls have keyboard focus.
  Dropdown options expose their supplementary details accessibly.

## Shared seam and ownership

New `ui/bridge/coding.py`, registered in `ui/bridge/__init__.py` and `ui/shell.py`.
It is a serial background presentation adapter over your existing tool registry,
with live effective-project policy, grant expiry checks, project/grant invalidation
and late-result suppression. Local path validation is reused from Documents.
`AppContext.close()` closes it. The complete API is in `docs/QML_BRIDGES.md`.

Git/file operations and VS Code launching stay in existing core tools. No core
files were modified by Codex. Your dirty browser, roles, capabilities, web,
netguard, requirements, verification and related test files remain excluded.
Untracked historical branding studies are also excluded. Approved logo files
and scene artwork were preserved.

Other changes are QML, model display-name JavaScript, focused tests, this report,
the handoff index and dated UI audit. No external message has been sent to Claude.

## Validation

**137 tests passed in the combined regression run (79.50 seconds).** This covers
Chat/context, Documents, Coding, navigation, Research, Code/Settings layouts,
accessibility, branding, plain-text/network guards, Schedule, model settings and
the existing shell checks. Focused checks pass for actual
temporary Git repos, unchanged index bytes, staged/unstaged/history separation,
denials, repository-root scope, late-result suppression and revoked/expired grants.
VS Code tests intercept launch or simulate a missing install; they start no editor.

After the final count-label/keyboard-timer polish, 15 navigation/view/plain-text
checks passed again. The standalone `python tools/check_research_ui.py` harness
also passes: real composer, scripted streaming, editable starters, saved prior
inquiry, both sizes/appearances and no QML warnings. The normal `Akira.bat`
launcher still opens `shell.py` from this checkout, so reopening Akira picks up
these source changes without an installer rebuild.

Visual/runtime checks use the real QML window, isolated configuration and fixture
content. Code is checked at 900×600 and 1440×900 in both appearances, at 100% and
150% display scaling. Settings has both sizes/appearances at 150%. Long patches,
literal markup, model path preservation, keyboard containment, focus return and
busy-state model controls are covered. No model or background service is started.

Ignored local evidence:

- `artifacts/scenes/ui-audit/code-workspace/` — Code, permission refusal, patches,
  and history at both scales.
- `artifacts/scenes/ui-audit/settings-sections/` — setup, appearance, models and
  exact file details.

This validates offscreen software rendering, not physical multi-monitor movement,
GPU animation performance, a real VS Code launch or successful model loading.
The model overview deliberately says file availability, not model health.

## Next priorities

1. Structured research source/preview metadata and persistent run ownership.
   Please provide an explicit structured contract; do not turn citation prose
   or Git output into a filesystem action.
2. Code file navigation, structured diffs/review actions and persistent task/run
   context. Code currently shares Chat's conversation; the actual team runs
   remain in Agents. Git review is a snapshot, not attributed to a particular run.
3. Shorter account-setup guidance; consolidate more legacy forms using FormRow;
   complete run-detail and memory-provenance search.
4. Quiet-scene preference and light-mode scene transitions; retain the original
   art and reduced-motion behavior. A persistent scene setting needs an agreed
   configuration field or UI preferences store.

Index row: **30**. The current broad priorities remain in
`docs/UI_AUDIT_2026-09-12.md`, with a dated progress update for this pass.
