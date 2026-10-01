# Codex → Claude: true pixel treatment and distributed cameos

The person requested stronger pixel art, cameos at different depths, and removal of Pochita's clashing orange. `MegastructureScene.qml` now uses `megastructure-v3-pixel-depth.png`, decoded at 384×256 and enlarged without smoothing. Previous images remain intact.

Foreground: Ranni and green SAMURAI graffiti. Middle distance: green Pochita on a recessed gallery and Killy on the central bridge. Far background: tiny fog-muted Pyramid Head on the highest bridge. Spiral remains carved into an upper gallery wall. Red accents are architectural lights only. Prompt and selected-result notes are in `docs/branding/megastructure-v3-prompt.md`.

Existing registered lighting, theme switching, and readable chat surfaces retained. No backend changes. `tests/test_qml_megastructure.py`: **2 passed**, 100% and 150%. Actual empty-chat screenshot inspected; captures in `%TEMP%/akira-megastructure-depth-review/`. No commit or push.
