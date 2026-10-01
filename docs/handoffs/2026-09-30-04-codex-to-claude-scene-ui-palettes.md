# Codex → Claude: surrounding UI matches the scenes

The person approved the cave and requested complementary surrounding UI colors. Updated the shared `Theme.qml` palettes, so sidebar, header, controls, library/tools, popovers and sheets inherit the same treatment.

- Dark: green charcoal canvas `#0D1814`, surface `#15231D`, progressively lighter green-gray hover/active/overlay layers. Soft pale-green text.
- Light: cream limestone canvas `#F1F1E6`, surface `#E8EADF`, muted sage-gray control layers. Dark green-gray text.
- `Main.qml` reading column and composer backing now use `Theme.canvas` in both modes, replacing the separate hardcoded light color.
- Scene artwork and existing green/red interactive accents unchanged. No backend changes.

Validation: branding and scene tests **7 passed**, including minimum 4.5:1 text contrast across all six surface variants and button states, plus scene lifecycle at 100%/150%. Visually inspected both actual themed windows. Captures: `%TEMP%/akira-scene-palette-review/`. No commit/push.
