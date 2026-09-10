# Frontend handoff — scene details and Research

Date: 2026-09-10. Author: Codex. User-approved scope: frontend/UI.

This is the current handoff. `SCENES_HANDOFF_FOR_CLAUDE.md` describes the earlier
scene rebuild and is historical; its pending roof correction was completed by
Claude before this pass.

## Starting point and ownership

Started on `rebuild` at `2ed525b` (Claude's lighting, layering, cottage roof and
black-hole fixes). During the session Claude committed the backend spine and
project work order: `f4c7106`, then `47c7739`. These are preserved. The changes
in this handoff are frontend files, preview/check tools, and this
report. No core, permission, security, model, bridge or backend test files were
edited. No packages, model files, user settings or real conversations changed.

Read `BACKEND_HANDOFF_FOR_CODEX.md`, `PROJECT.md` and REBUILD's UI findings for
context. Their planned backend work is not being marked complete by this UI
pass. In particular, A4/A5 team execution and trace UI, C2 web search and C7
live environment integration are separate work.

## Existing scenes: completed detail pass

The terrain composition and Claude's corrections remain: the mountain foot
ends inside the left wooded headland; the channel is open; the cottage has its
symmetric gable and fascia; distant foliage retains atmospheric/seasonal tint;
shadows follow the upper-right light; black-hole dust stays outside its rings.

New detail helpers live in `protege/ui/qml/Protege/scenes/coast_details.js`.
They are called at explicit depths from `coast.js`, so water, weather, trees,
and foreground objects occlude them in the right order.

- All seasons: distant lighthouse and keeper's shed, a small shoreline jetty,
  cottage bench, seasonal window boxes, and chimney smoke in cold/dim weather.
- Spring: fallen blossom, a branch-attached nest and bird, and a butterfly in
  calm/dry conditions. Rabbit shadows now follow the same light as the trees.
- Summer: sandcastle, bucket and spade, beach shells, and a few fireflies on
  calm, dry nights. Existing umbrellas remain.
- Fall: mushrooms and leaf litter, a weathered notice on the left trunk, a tiny
  CRT with a four-frame scanline on the cottage bench, a faint mask on the
  existing watcher at the far right, and almost-submerged shapes out in the
  night bay. The sea shapes are painted below fog. No jumps or strobing.
- Winter: sled, footprints toward the snowman, icicles and a robin. Existing
  Christmas tree/lights remain. Snowman highlights/shadow were aligned with
  Claude's upper-right illumination.

`orbit.js` adds a survey satellite, faint comet/debris, a tiny monolith on a
crater rim, a station solar array, parked rover, astronaut and footprints.
A nearly black many-limbed shape sits inside the black hole, occluded by the
front accretion arc. It is meant to be discovered, not announce itself.

## Research workspace and The Drowned Archive

Research is now accessible from the sidebar and the top workspace strip.
Tab selection and sidebar selection actually select the same workspace.
The previous placeholder file tabs were replaced with Everyday, Code and
Research workspace tabs.

`ResearchView.qml` provides a compact greeting and three keyboard-accessible
starters: Explore a topic, Compare ideas, Plan an inquiry. A starter prepares
an editable draft, appending to existing input rather than overwriting it. It
does not send. Enter uses the existing Composer -> Chat.send path. The Research
transcript supports the existing streaming, error, stop and saved-conversation
behavior. New inquiry is disabled while busy and uses Chat.newChat, which saves
the previous conversation. The scene fades away for readable conversations.

**Current boundary:** this is a research-oriented local conversation surface.
It shares the current conversation and draft with Everyday/Code. It does not
create a separate research database, resident model, source library, web search,
citations, research jobs or team execution. UI text explicitly says web search
is not connected. No fake sources or agent progress are shown. Model routing is
still the bridge's existing prompt-based routing; selecting Research alone
does not select a different model.

New `AbyssScene.qml` + `abyss.js` implement The Drowned Archive:

- A dark canyon, uneven shelves and a centre trench, with a ruined temple
  planted on the right ledge and an exploration submarine at the upper left.
- A searchlight that attenuates into the water instead of ending as a hard
  triangle. Temple glyph and reflected light pick out the doorway and steps.
- Hollow glass sponges with pale diamond latticework, swaying fronds, mineral chimneys, tubeworms, anemone,
  isopod, fossil ribs and small exploration equipment.
- Sharks, a lanternfish school, jellyfish, vampire squid and tiny anglerfish.
- A huge, dark leviathan behind the right canyon wall, with a second eye,
  faint teeth, sensory filaments and an almost invisible tail. No sudden motion.
- In response to the user's latest feedback: substantially brighter cyan,
  violet, lilac and blue creature highlights with layered pixel halos; a more
  luminous temple glyph and stronger submarine beam. The water and leviathan
  remain dark so those light sources have contrast.
- Final user correction: replaced all branching/bulbous coral with varied
  glass sponge baskets, open rims and fine anchoring fibres. Reduced the welcome
  panel from 484 to 410 px, shortened its copy/spacing, raised it and reduced its
  opacity from 0.84 to 0.68. Shifted the leviathan 32 native pixels right and 24
  down; its head now remains visible below the panel at both tested window
  sizes. Rechecked Research interaction and inspected both layouts afterward.

Like the existing scenes, this is a code-authored painting on the shared pixel
grid, cached as four complete frames. Abyss frames advance every 1700 ms; only
tiny tendrils, light pulses and suspended particles change. Reduced motion,
hidden content and minimized windows stop playback. No new runtime dependency,
continuous particle simulation, downloaded art or external media is required.

## Files and integration points

New runtime files:

- `protege/ui/qml/Protege/ResearchView.qml`
- `protege/ui/qml/Protege/scenes/coast_details.js`
- `protege/ui/qml/Protege/scenes/AbyssScene.qml`
- `protege/ui/qml/Protege/scenes/abyss.js`

Modified runtime files: `Main.qml`, `Protege/ChatView.qml`, `Protege/qmldir`,
`scenes/SceneHost.qml`, `scenes/coast.js`, `scenes/orbit.js`.
ChatView gained `showGreeting` and stops greeting/busy icon pulses when hidden
or reduced motion is selected. SceneHost accepts `view: "research"`.

Preview/check changes: `SceneGallery.qml`, `tools/preview_scenes.py`,
`tools/preview.py` (new `--view research` flag), `tools/check_scenes.py`, and
new `tools/check_research_ui.py`.

For subsequent backend integration:

1. C2/A4: keep the ordinary local conversation usable while adding actual
   research jobs, source records and team traces. Add a bridge with real data
   before introducing source or agent panels. Worker callbacks must reach QML
   through queued Qt signals, as described in your backend handoff.
2. A1/A2: a future web/source flow must honor the existing permission gate and
   per-action confirmation contracts; no UI grant or permissive fallback was
   added here.
3. C7: SceneHost.weather still defaults to `clear`. The renderer handles the
   supplied weather presets, ocean state and wind, but this shell has no live
   weather/location connector. Bind a permitted connector to weather and
   southernHemisphere when ready. Do not confuse fixed preview conditions with
   real conditions. Existing local time/season handling is preserved.
4. Keep projects/memory shared across workspaces when B2/B5/B6 land. Dedicated
   Research is useful for long investigations and source review; quick questions
   still belong naturally in Everyday. Avoid a second disconnected memory or
   loading another large model just because the workspace changes.

## Validation actually completed

- `python tools/check_scenes.py`: passes for coast, space and research. Checks
  distinct cached frames, deterministic wrap, inactive/minimized/reduced-motion
  pause; also thunder rendering, September 10 summer season and three aspect
  ratios. No QML warnings.
- `python tools/check_research_ui.py --out-dir artifacts/scenes/research-ui`:
  real Main.qml and real ChatBridge with a scripted local inference backend and
  temporary conversation storage. Mouse and keyboard starters, draft retention,
  workspace navigation, Enter submission, streamed response, quiet scene, and
  saving the previous inquiry all pass. Dark/light at 1440x900 and 900x600; no
  QML warnings. This does not benchmark or validate real-model answer quality.
- `python -m pytest tests/test_scene_world.py -q`: 20 passed.
- `python tools/preview_scenes.py --frames --out-dir artifacts/scenes/frontend-review`:
  14 scenarios / 56 frames; no QML warnings. Inspected the scene renders, contact
  sheet, and app layout at both sizes and appearances. The latest abyss lighting
  is included, not just the earlier muted study.
- `git diff --check`: clean. The full backend suite was not rerun for this
  frontend-only pass.

## Review and transfer

These changes are already in the working tree. Restart the existing Qt Protégé
application to load them; no launcher change or reinstall is needed. Research
is visible in the sidebar. The user subsequently authorized a dedicated commit
and push on `rebuild`. The final commit and verified remote status are recorded
in `artifacts/scenes/frontend-review/DELIVERY.md` and the bundle manifest after
delivery; those artifacts are outside Git.

- `artifacts/scenes/frontend-review/gallery.html`: portable offline gallery,
  embedded frames, per-scene selection and play/pause controls.
- `artifacts/scenes/frontend-review/contact-sheet.png`: overview.
- `artifacts/scenes/frontend-review/research-0.png`: latest abyss lighting.
- `artifacts/scenes/research-ui/`: isolated UI screenshots using test data only.
- `artifacts/scenes/frontend-handoff.zip`: report, frontend patch, source files,
  scene gallery/captures and isolated Research UI screenshots. No user data or
  backend changes included. See the manifest for base commit and hashes.

The patch is for another checkout missing these changes; do not apply it over
this already-modified working tree. Read the report first and check the patch
against your checkout before applying it.

Implementation stopped at the requested boundary: the pre-packaging check was
89%. Final verification/packaging and the subsequently requested commit/push
brought the next check to 93% (77% weekly). No further feature work is planned
in this session.
