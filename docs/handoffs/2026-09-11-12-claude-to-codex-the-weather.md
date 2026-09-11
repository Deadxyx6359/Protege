# The weather

Claude → Codex, 2026-09-11. Follows
[11](2026-09-11-11-claude-to-codex-page-and-feed-watches.md). It completes work
order item **C7** in [../PROJECT.md](../PROJECT.md): the real weather for the
person's place, for the scenes and for models.

## The one line to add

```qml
SceneHost {
    weather: Place.weather || "clear"
    southernHemisphere: Place.southernHemisphere
}
```

`Place.weather` is one of the scenes' own names (`clear`, `rain`, `gale`,
`snow` and the rest, from `world.js`'s `WEATHER`), or `""` when there is no
current reading. With `""` the scene keeps its default, as it does today. A
test checks that the Python list and `world.js` stay the same, so if you add or
rename a weather, tell me and the test will say where.

## What the person has to do for it

Weather needs three things, and until all three are in place nothing is sent
anywhere:

1. **A position for the place.** A name alone is not enough to ask about the
   weather. Either look it up (`findPlace(text)`, then `choosePlace(index)` on
   one of `candidates`) or type it (`setPosition(latitude, longitude)`).
2. **`location.read`** ("Know where you are").
3. **`net.http` for `open-meteo.com`**, which is `Place.weatherSite`. One grant
   covers both the forecast and the lookup.

`Place.weatherNote` says, in a sentence, which of these is missing, or why the
last reading failed. Looking a place up needs only (3), since the person typed
it and asked.

## Suggestions for the view

- **A small "Where you are" panel**, probably in Settings: the name, a Find
  button that fills a list from `candidates` (show `lookingUp` while it
  runs, and `lookupNote` if nothing was found), and the chosen place's
  `weatherSummary` with the time from `weatherAt`, e.g. "14°C, light rain ·
  10:20".
- **Offer the grants where the note is.** When `weatherNote` starts with
  "Not permitted", the natural next step, after the person agrees, is
  `Permissions.grant("location.read", [])` or
  `Permissions.grant("net.http", [Place.weatherSite])` right there.
- **Say plainly what is sent**: an approximate position, about 11 km, to
  open-meteo.com, every half hour. The backend keeps it to that. Worth one
  line in the panel so nobody has to wonder.
- **`candidates` labels come from the lookup service**, so show them as plain
  text (rule 5 from handoff 10).
- `refreshWeather()` exists for a refresh button, but the reading keeps itself
  fresh every half hour, and a new position is read at once, so the button is
  optional.

## Behaviour worth knowing

- A reading more than three hours old is not the weather now. `weather` goes
  back to `""`, and `weatherChanged` fires when that happens.
- Changing the position forgets the old reading straight away. A new place name
  typed with `setPlace` forgets the old position too, so the weather stops
  until a position is given again.
- Everything runs off the UI thread. Results arrive on `weatherChanged` and
  `lookupChanged`.

## Not changed

No new capability: the weather uses `location.read` and `net.http`, which
already existed. The index row for this handoff is **18**.

## Tests

`tests/test_weather.py`, and more in `tests/test_place.py` and
`tests/test_place_bridge.py`. The full suite count is in the commit message;
`verify_offline.py` passes.
