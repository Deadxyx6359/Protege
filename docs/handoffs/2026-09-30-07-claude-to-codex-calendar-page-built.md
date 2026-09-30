# Claude → Codex: the calendar page is built

The person asked me to build the calendar page myself, so **handoff 70 is done;
please don't build it again.** Restyle it as you like: it uses only `Theme`
tokens and the shared components.

## What is new

- **`CalendarView.qml`**: a month or a week. Weeks start on the locale's first
  day.
  - The chosen day's events are listed beside it, from 900 pixels wide.
  - The header wraps onto two lines below 1,160 pixels.
  - A quick-add line: a line with a day or a time is added at once, with Undo.
    A line without one opens the editor.
  - Drag an event to another day, or, in the week view, to another time.
  - One quiet line with an Allow… button appears when the chat and agents
    can't read the calendar, or when notices (for reminders) aren't allowed.
- **`CalendarEventSheet.qml`**: add or change an event.
  - Fields: title, all day, start and end (typed as `2026-10-02` and `15:00`),
    repeat and until, reminder, where, notes.
  - Removing asks once, in place.
  - What the bridge refuses is shown as it is.
  - It is parented to the window's content item, so it covers the whole window
    like the other sheets.
- **Navigation**: Calendar is a third Library tab, after Documents and Memory.
- **`qmldir`**: both files are registered.

## Your uncommitted files

`Main.qml` and `qmldir` have your uncommitted changes, so I edited them in
place and committed only my lines on top of the last commit.

- In **your working copy** of `Main.qml`:
  - `"calendar"` is in the two `["documents", "memory", …]` lists.
  - The Library `Segmented` has the Calendar option and is 420 wide.
  - The page has `anchors.topMargin: 56`, like the others.
- In the **committed** `Main.qml`: a `nav` item
  `{ id: "calendar", icon: "calendar", label: "Calendar", group: "Library" }`
  and the page with no top margin.

When you commit your navigation, keep the calendar in it.

## Watch out for

- **Clicks through a closing sheet.** A press on the editor's Save was also
  taken, passively, by the day under it. When Save closed the sheet
  (`enabled: _open` drops mid-click), the release chose that day. The
  calendar page now takes no clicks while its editor is open. Any page with
  its own `TapHandler`s under a `Sheet` can meet the same thing. It may be
  worth fixing once in `Sheet.qml`, for example by keeping `enabled` until
  the click is over.
- **Setup sheet overflow.** Still true from handoff 70: with six rows, a
  700-pixel window puts the setup sheet's "Allow these" below the fold.

## Validation

- `tests/test_qml_calendar.py` drives the real window by mouse and keys.
  It covers opening and renaming an event, quick add and Undo, quick add
  without a day opening the editor, the editor refusing an unreadable date,
  removing with its confirmation, dragging to another day, the week's
  blocks, and an agent's change reaching the page. It checks there are no QML
  warnings.
- All QML tests pass (66), including your uncommitted ones and
  `test_qml_text_formats` (every text on the page is plain).
