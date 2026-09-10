# Protégé scene handoff — 10 September 2026

## Latest user feedback — pending roof correction

After the channel correction, the user reported: "the house roof is a little odd looking as well." This has NOT been fixed. Make the cottage roof the first visual follow-up: review the roof planes, ridge, eaves, chimney overlap and their perspective against the cabin walls in `coast.js` / `cabin()`. Inspect the corrected render at full size and in the app, then regenerate the gallery.

The final usage check reached 91% of the five-hour window (62% weekly), up from 87% at the preceding check while the channel fix and delivery were completed. Codex stopped implementation and recorded this final feedback instead of continuing past the requested 90% handoff threshold.

## Outcome

Codex continued the unfinished visual work on branch `rebuild`. The Chats and Code backgrounds now use two authored pixel compositions, **Driftwood Bay** and **The Far Station**, with four cached animation frames each. The current Qt application loads these components through the existing SceneHost; no launcher migration is required. Reopen Protégé to pick up the changed QML.

No commit or push was made in this session. Base HEAD is `2e5098ba6d454b0a5eba823fe145e0c4c262a766`. The accompanying patch represents the complete working-tree difference from that commit, including inherited Claude changes. On the existing working checkout, these changes are already present: do not apply the patch again. For another checkout, use a clean copy of the stated base and run `git apply --check protege-scenes.patch` before applying it.

## User direction to preserve

- Cohesive pixel paintings, not collections of floating sprites. Ground objects, match distant trees to the atmosphere of their terrain, and keep water separate from land.
- Minimal, satisfying, Apple-influenced application framing. Calm short loops and a clear reading surface matter more than continual movement.
- Coast with mountains, trees and beach in every season. Spring flowers/rabbits, summer parasols, autumn pumpkins/scarecrow and very subtle horror, winter Christmas details.
- Space should stay mostly monochromatic, with black holes, neutron stars, planets and small alien details.
- Weather should distinguish drizzle, rain, strong wind, storms and snow, including sea state and foliage movement.
- The reference attachments were unavailable in this Codex context. These are original code-authored interpretations, not claimed matches to unseen references.
- Latest scope was the scenes, with a handoff before the account reaches 90% usage. The larger second-brain/agents/voice platform remains a separate backlog.

## Changes made by Codex

| File | Purpose |
| --- | --- |
| `protege/ui/qml/Protege/scenes/coast.js` | Authored coastal composition: faceted mountains, grounded distant forest, curved shared shoreline, sand/dunes, meadow, cottage/path, shaded foliage, seasonal details, and weather. |
| `protege/ui/qml/Protege/scenes/orbit.js` | Orbital painting: lensing black hole and accretion disk, neutron-star jets, small moon and ringed planet, cratered foreground crescent, telescope station and small visitor. |
| `protege/ui/qml/Protege/scenes/pixel.js` | Integer raster primitives for lines, filled polygons, ellipses and deterministic material marks. |
| `protege/ui/qml/Protege/scenes/PixelScene.qml` | Shared four-frame filmstrip renderer, nearest-neighbour presentation, lifecycle-aware playback and responsive sky extension. |
| `protege/ui/qml/Protege/scenes/BotanicaScene.qml` | Replaced the previous large sprite graph with the coast painter; clock/season/weather bindings and infrequent distant lightning. |
| `protege/ui/qml/Protege/scenes/SpaceScene.qml` | Replaced the sparse drifting-star background with the orbital painter. |
| `protege/ui/qml/Protege/scenes/SceneHost.qml` | Explicitly suspends scene playback when chat content hides the art; shorter composer fade preserves more foreground detail. |
| `protege/ui/qml/Protege/scenes/world.js` | Corrected DST-sensitive calendar arithmetic, leap-year season boundaries, winter progress across New Year, and exact weather preset normalization (`downpour` previously became clear). |
| `protege/ui/qml/SceneGallery.qml` | Controlled scene/date/weather/frame harness, independent of the user's conversations and models. |
| `tools/preview_scenes.py` | Renders fixed cases, records QML warnings, and creates an offline HTML gallery with embedded images and playback controls. |
| `tools/check_scenes.py` | Real Qt checks for cached frames, deterministic wrapping, inactive/minimized/reduced-motion behavior, lightning, current season and aspect ratios. |
| `tests/test_scene_world.py` | 20 calendar and weather regression cases. |
| `.gitignore` | Excludes local preview output under `artifacts/scenes/` and the first scratch preview. |

The scene uses a 480×270 art coordinate system. Taller panes add sky above the composition instead of cutting away the foreground subjects. Canvas contains four horizontally arranged paintings. A timer changes the ShaderEffectSource crop; it does not regenerate procedural geometry on every animation tick. Light/weather/date changes rebuild the strip. Explicit `antialiasing: false` on Canvas is essential: without it Windows 125% scaling produced visible seams between pixel rows and columns.

Motion cadence: calm coast 1.1 seconds/frame, strong wind 520 ms, heavy precipitation 300 ms, space 1.4 seconds. Reduced motion uses the first frame. The storm lightning timer runs only during an active thunder scene, with a minimum 30-second interval (currently 44 seconds for the preset), a 180 ms distant bolt, and no full-screen flash. Rain advances through a vertically repeating pattern so the fourth-to-first-frame transition continues downward.

The coastline, foam and meadow use shared contour functions. Trees are planted on the foreground bluff/meadow; distant trees use the colour and contour of their own landmass. Summer parasols fold during strong wind and the sailboat disappears. The autumn figure is low contrast, stationary, and only appears after dark. Winter adds cottage lights, a decorated tree and a snowman.

Final user correction: the mountain base overhung the channel. The mountain's lower slope now terminates at (247,144), inside a wooded headland ending at (256,146), instead of projecting beyond it to (269,139). The opposing headland begins at x=303. The shared FAR_LEFT/FAR_RIGHT contours ground the forest and leave the channel mouth open. The corrected summer render was inspected and all gallery frames were regenerated after this change. Preserve this relationship in future edits.

## Work inherited from Claude

At entry, BotanicaScene.qml, sprites.js and world.js were modified, terrain.js was deleted, and scene.js was untracked. The unfinished previous renderer was replaced in the active Botanica component. The inherited `scene.js` and `sprites.js` remain on disk, unused by the new scene components, so Claude's work has not been silently discarded. The inherited terrain.js deletion is retained. These inherited changes are included in the full working-tree patch and must not be attributed entirely to Codex.

## Verification performed

- `python -m pytest` — **1020 passed, 1 skipped in 42.44 s**. Existing Tk tests printed `invalid command name ..._drain_events` cleanup messages despite passing. This session did not change the Tk renderer.
- `python -m pytest tests/test_scene_world.py` — **20 passed**.
- `python tools/check_scenes.py` — **passed** after the final painter adjustments; no QML warnings. Covers both scenes, three or more distinct cached images, deterministic return to frame zero, inactive/minimized/reduced-motion states, visible thunder bolt, Sept 10 summer, and 636×556, 1176×856 and 1800×900 panes.
- `python tools/preview_scenes.py --frames --out-dir artifacts/scenes` — **44 captures**: 11 cases × four frames. Cases include all seasons, Halloween night, dawn, night, drizzle, thunder, blizzard and space. Real Qt captures were visually inspected, including full-size summer, winter, storm and space, plus a seasonal contact sheet.
- Main.qml rendered successfully in both light and dark appearances. The subsequent responsive composition adjustment was also inspected in the actual dark application layout.
- One initial lightning check failed because the mountain correctly occluded the entire bolt. Its starting point was raised into the visible sky; the check now passes.

These are visual/runtime and regression checks, not a measured laptop GPU/battery benchmark or a security audit. No new dependencies, model weights, external image assets or network services were installed.

## Review and run

Open `gallery.html` from the handoff bundle in a browser. It is self-contained, uses no network, and includes scene choices and a pause control. It honours reduced-motion preference and pauses its timer when the page is hidden. Gallery dates/weather are fixed studies, not live observations.

In the repository:

```powershell
python tools/preview_scenes.py --frames --out-dir artifacts/scenes
python tools/check_scenes.py
python -m pytest tests/test_scene_world.py
python shell.py
```

The preview and check scripts do not load models or user conversations. Running `shell.py` is the actual application and follows its normal model preload setting. The user's existing desktop shortcut already points to this entry point. The review images in the handoff are isolated scene captures, not screenshots containing conversation history.

## Honest limits and next work

1. **Live weather/location is not connected.** SceneHost still defaults to `weather: "clear"` and `southernHemisphere: false`. All weather effects work with supplied preset values, but clear weather in the app is not evidence of a successful forecast lookup. Add an explicitly configurable provider/location, timestamp/stale-data status, and privacy controls before claiming live conditions. No network lookup was introduced here.
2. Seasons use approximate March 20 / June 21 / September 22 / December 21 calendar boundaries and a hemisphere switch. They do not calculate exact annual equinox times, local growing seasons, real sunrise/sunset, lunar phase or weather-dependent seasonal transitions. Sept 10 remains summer in the northern hemisphere.
3. Halloween and Christmas details currently apply to the corresponding whole season, as the user requested. They could later be narrowed to date windows if preferred.
4. Review the sky-extension balance in tall panes with the user. It intentionally retains the complete scene width and creates more space for the greeting. The composer fade still conceals the lowest details during normal app use. A future wallpaper-only mode could expose the full painting.
5. Preserve the distinction between new Qt shell and legacy Tk app. Prior review found that coding currently routes text to a coding model; file/terminal/VS Code agent tooling and much of the larger platform are not yet implemented. Model-routing invalidation, queued chat tokens after conversation switching, and parity with legacy privacy/PIN protections were earlier review concerns, not fixes made during this scene pass.
6. Optional future cleanup: archive/remove the unused scene.js and sprites.js after reviewing their inherited work. They are not part of active rendering.

## Delivery

`claude-handoff.zip` contains this report, the working-tree patch, the offline gallery, selected scene previews and the capture report. The patch targets the stated base commit; the report explains which changes were inherited. There was no direct message sent to a Claude service. The user is the delivery path for this handoff.
