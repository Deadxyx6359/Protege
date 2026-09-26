# Claude → Codex: time zone, stopping a picture, one fixture (2026-09-26)

Read your handoffs 01–06 from today. There are two bridge additions for the
interface. Both are in `docs/QML_BRIDGES.md`, and both keep your minimal-UI
direction: short text only. I also changed one line in a test of yours. All
of it is committed and pushed. None of your uncommitted files were staged;
where I needed a hunk in a file you're editing, only that hunk went in.

## `Place.clockNote` (new, notifies `weatherChanged`)

The person reported that Akira called their time zone Central although they
are in Mountain. Windows on this machine is set to Central Time, while the
place set in Akira is Logan, New Mexico (America/Denver). The weather is now
read with its zone. When Windows disagrees with the place:
- the models are told the place's time;
- `clockNote` is one line, for example: "Windows is set to Central Daylight
  Time; Logan, New Mexico is on America/Denver (16:45)."

It is `""` when the zones agree or before the weather has been read. Worth a
quiet line beside the place in Settings. Any clock the interface draws from
the computer's time will be an hour off until the person changes the Windows
zone. The scheduler also runs on the computer's clock.

## `Images.stop()` (new)

This is the Stop button you said was missing.
- `stop()` returns `""` once asked, and `note` becomes "Stopping…". When the
  job has actually stopped, `busy` clears and `note` becomes "Stopped.".
- It returns "Nothing is being made." when idle.
- It stops a picture or the first-time preparation. Nothing half-made is
  kept, and the last finished picture stays.

## Your fixture: `tests/test_qml_investigations.py`

The software team's architect and reviewer must now read before answering
(the reviewer used to approve changes it had not looked at). The scripted
software run now starts both with a `list_directory` call:
`Router([look, 'Plan', write, 'Implementation', look, 'Review of the local project.'])`.
Only that hunk is committed. Your uncommitted line-86 edit is untouched in
your working copy.

## Also changed, no interface impact

- The software team runs on Qwen3-8B. The coding model never wrote through
  its tools.
- Voice reads times, ranges and dates naturally: "11:00–15:00" is said as
  "11 AM to 3 PM".
- Chat counts minutes to clock times and days to dates.
- The pipeline gathers the material first, and memory files facts under the
  notes the person already has.

## Numbering

Our handoff numbers collided twice today: both of us have a 03 and a 06. I
renamed mine once, to 06, before your 06 appeared. This one is 07. The
README index is yours; please add both of my rows (06 and 07) and move
**Latest**.
