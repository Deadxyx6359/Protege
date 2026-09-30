# Claude → Codex: a calendar kept in Akira, and its page

The person chose option A for the calendar: one of Akira's own, **completely
local**. Google's sign-in for the calendar expired every seven days. Everything
behind the page is done; the page itself is yours. I changed no QML.

## What is done

- **The calendar** (`akira/core/planner.py`): `calendar.json` in the settings
  folder. No account, nothing sent, no sync to a phone. Events are timed or all
  day. They can repeat (daily, weekly, fortnightly, monthly, yearly, until a
  day) and can carry a reminder. Times have no zone: 15:00 is 15:00 on this
  computer. An all-day event's end is the last day it covers.
- **Reminders** are notices, the same `Monitor.notice` banner scheduled
  notices use. Each is given once, only while `notify.send` holds, and not
  given late once the event is over.
- **The chat** (`akira/core/agenda.py`):
  - "Add dentist to my calendar on Friday at 3pm" is read by rules, offered
    back, and added only on the person's yes.
  - "What's on this week?" is answered from the calendar, only with
    `planner.read`.
- **Agents**: new permissions `planner.read` and `planner.write`, which never
  leave the machine. Every change goes through `Confirm` first. The tools
  are `calendar_list`, `calendar_add`, `calendar_change` and
  `calendar_remove`, used by the secretary (and `calendar_list` by
  coursework). Google's tools are still there for an address the person names.
- **Quick setup** has a sixth row, "Your calendar" (both permissions).
- **The bridge** is `Planner` (`akira/ui/bridge/planner.py`), documented in
  full in QML_BRIDGES.md under `## Planner`.

## The page to build

Where it goes in the navigation is your call. It is the person's own material,
so the Library section beside Documents and Memory seems natural, but its own
sidebar entry would work too.

What option A promised the person:

- **Month view**: `Planner.month(year, month, sundayFirst)` gives 42 days.
  - Show each day's number, `today`, and `inMonth` dimming.
  - Show the events as chips: `time` + `title`, all-day first. A multi-day
    event has `first`/`last` for joined bars.
  - Show "+N more" when a day is full.
  - Take `sundayFirst` from `Qt.locale().firstDayOfWeek === Locale.Sunday`.
- **Week view**: `Planner.week(day, sundayFirst)` gives 7 days.
  - Put all-day events in a strip at the top.
  - Place timed events by `startMinute`/`endMinute`, already clipped to the
    day, so an event past midnight shows on both days.
- **An editor** (a sheet), for new and existing events:
  - Fields: title, an all-day switch, start and end (date and time, or dates
    for all day), repeat (`Planner.repeats`) with a last day, reminder
    (`Planner.reminders`), where and notes.
  - Save calls `add(fields)` or `change(id, fields)`. Start from
    `event(id)`, which has every field in the shape they take.
  - Show the returned string when it isn't "": it is written to be shown.
- **Quick add**: a line where the person types "Dentist Friday 3pm".
  `Planner.read(text)` fills the editor with it (`start` is "" if no day or
  time was typed).
- **Moving**: drag to another day or time with `move(id, start)`. A day keeps
  a timed event's time, and the length is kept.
- **Removing**: `remove(id)` removes every repeat and has no undo, so ask once.
- **Refreshing**: bind the models to `Planner.revision`. It goes up for
  changes from the page, the chat, and agents (arriving from other threads).
- **A quiet line** when `!Planner.agentsRead` ("Akira's chat and agents
  can't see this calendar yet") and when `!Planner.noticesAllowed`
  ("reminders will wait until notices are allowed"), each with the way to
  allow it: Quick setup's "Your calendar", or Permissions.

Titles, places and notes are the person's own text, or an agent's (approved),
so show them as plain text.

## Watch out for

- **Setup sheet overflow.** With six rows and a folder picked, a 700-pixel
  window puts "Allow these" below the fold. `test_setup_screen` now scrolls
  the sheet before pressing it. Consider pinning the sheet's action row.
- **Tests** for the page should use a settings folder of their own
  (`tests/conftest.py` now sets one for every test). The calendar is
  `calendar.json` in it.
- **Not committed:** `Main.qml`, `Sidebar.qml`, `qmldir` and the other files
  you have in flight. I committed only my own files, and my lines in
  QML_BRIDGES.md and this README.

## Validation

- Calendar core, tools, chat and bridge: 91 new tests.
- Full suite in a clean worktree and `verify_offline.py`: see the commit.
