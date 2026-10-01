# Codex → Claude: dark cave garden

Dark-theme chat now shows a single coherent cave garden: emerald foliage, hanging roots, stone terraces, waterfall and pool, and sparse red torchlight. Light chat still uses the original untouched megastructure. Theme alone selects the scene; no time/weather dependencies or cameos.

- `CaveGardenScene.qml` registered in `qmldir`; asset `akira/ui/assets/scenes/cave-garden-v1.png`, generated with the built-in image tool. Exact prompt in `docs/branding/cave-garden-v1-prompt.md`.
- Same 768×512 decode grid and unsmoothed scaling as the light painting.
- Fixed-coordinate torch illumination varies gently; no moving sprites or per-frame canvas redraw. The waterfall and pool are painted, not simulated.
- `Main.qml`: dark scene selection, theme-appropriate reading column and composer backing. The light artwork is unchanged.
- Animations stop on reduced motion, hide/minimize, other pages, and inactive theme. No backend or bridge contract changes.

Validation: scene lifecycle tests extended for both themes, including real torch-opacity movement/freeze, matching pixel sizes, dark reading-surface color, navigation, minimize/hide and draft retention. Combined scene/one-chat/section suite: 6 passed at 100% and 150%. `verify_offline.py`: PASS. Inspected actual empty and populated dark chat captures at desktop and minimum sizes; captures in `%TEMP%/akira-cave-garden-review/`. No commit or push.
