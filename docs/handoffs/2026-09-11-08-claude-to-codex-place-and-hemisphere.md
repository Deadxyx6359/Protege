# Where the person is, and the scenes' hemisphere (C7, local half)

Claude → Codex, 2026-09-11. Follows
[07](2026-09-11-07-claude-to-codex-watched-folders-and-notices.md). It covers
the half of work order item **C7** in [../PROJECT.md](../PROJECT.md) that needs
no network.

## What you can build on now

**A new context property, `Place`** (`PlaceBridge`), documented in
[../QML_BRIDGES.md](../QML_BRIDGES.md).

- **`SceneHost.southernHemisphere` finally has something to bind to:**
  `Place.southernHemisphere`. That is the one-line change this handoff is
  mostly for. `PROJECT.md` called it a connector binding, not UI work, and
  this is the connector. With it, the scenes' seasons turn the right way round
  for someone in the southern hemisphere.
- **A small setting.** `Place.setPlace(name, hemisphere)` keeps where the
  person is, e.g. `("Sydney, Australia", "south")`, and returns `""` or why not.
  `clearPlace()` forgets it. `Place.name`, `hemisphere` and `season` are there
  to show it.

Setting a place grants nothing. What the models are told depends on
`location.read`, so the setting is honest to label: "Used by the scenery. Told
to the assistant only if 'Know where you are' is allowed."

## What changed for the assistant

- Every agent and every chat turn is now told the date, the time and the part
  of the day. A model has no clock, and it was guessing.
- With `location.read` granted, it is also told the time zone and the place.
- The Python season rule is a copy of `scenes/world.js`'s `season()`, so the
  scenery and the assistant agree. If you change the rule there, tell me and I
  will change it here, or change both.

## Not done yet

- **Weather** is a network reading, so `SceneHost.weather` stays `clear` until
  C1. C1 is still waiting for the person's go-ahead.
- Index: add row **14** for this handoff when you commit `README.md`.

## Tests

Full suite at the C7 commit: 1600 passed, 2 skipped, 2 failed. The two failures
are the usual legacy Tk settings-geometry tests, which fail on this 960-px
display at a clean checkout too. `verify_offline.py` passes.
