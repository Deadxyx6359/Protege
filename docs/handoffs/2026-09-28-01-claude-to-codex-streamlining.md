# Claude → Codex: fewer questions, the chat menu, and a call that always closes

The person asked for Akira to be less of a chore to use: read new websites
without a trip to Settings, and "do all the streamlining suggestions". They also
said the right-click on a chat did not work, and later that Akira would not
close after a call. Codex was away, so I built the interface parts myself.
Please review them for design; the behaviour is tested. Your handoff 04
(Library and Tools) is still uncommitted in the shared tree. I left its files
alone and committed only my own hunks of `Main.qml`, `qmldir`,
`QML_BRIDGES.md` and the handoff index.

## What changed, by commit

- **`c1b44f0` Right-click menu on chats, and Settings → Chats.** Handoff 05
  asked you to build this, but the person needed it now, so it is done:
  - `ChatMenu.qml` opens by right-click, the Menu key, Shift+F10, or press and
    hold. It offers Rename, Pin, Move to project, and Delete, which asks first
    with the focus on Keep.
  - `NavRow` gained `mark`, `markDescription`, `hasMenu` and `menuRequested`.
    Pinned chats show a pin.
  - Settings has a Chats tab: delete chats older than a set number of days, or
    all of them, optionally keeping pinned ones. It shows the count before
    asking.
  - Switching Settings tabs now scrolls back to the top.
  - A bug worth knowing: `ActionButton` and `TapHandler` take presses
    passively, so a press inside a popup also reached the row underneath. That
    is how "Rename" opened the chat under it. The popup's background now has a
    `MouseArea` that stops the press. Any future popup over clickable rows
    needs the same.
- **`d62b6c9` Asked in place (`Allow`, `AllowPrompt.qml`).** When work reaches
  a site or folder next to one already allowed, a card at the top of the window
  asks: Allow once / Always allow / Don't allow. The work waits for the answer;
  the card is not modal. See `QML_BRIDGES.md` → `Allow` for the rules on what
  may be asked about.
- **`5d80387` Fewer questions.** No interface change. In work the person
  started:
  - a new file is saved without asking;
  - the same script or tests run again in one piece of work is covered by the
    first yes;
  - `fill_in` can name the button to press, so one question covers both.
  Promise 8 in `PROJECT.md` records this; the person chose it.
- **`cd0c596` Keep on purpose; default job grants.** A "Keep on purpose"
  button is on a no-expiry finding in `ScheduleView`. On the permission
  screen, a kept grant has a badge, and a "Keep on purpose" / "Stop keeping"
  button appears for high-risk, no-end-date grants. `Schedule.addJob` without
  `grants` now fills them in.
- **The call closes** (next commit). Details below.
- **Reminders in the chat, and the first screen** (next commit):
  - "Remind me to … at …" is answered with a question, and the person's yes
    creates a notice job. No interface change.
  - `SetupSheet.qml` opens once on first run. It offers web search and
    Wikipedia, weather, notices, a notes folder and a documents folder.
    Settings → General → Quick setup opens it again.

## The call that would not close

`Main.onClosing` hid the main window whenever `Voice.inCall` was true, on the
assumption that the call window was on screen. The person's call window had
gone while the call kept running. Two things followed: Akira refused to close,
and the microphone stayed open. The fix:

- `CallWindow` ends the call if it is ever hidden while a call runs.
- `Main.onClosing` keeps the call only while its window is visible; otherwise
  it ends the call and closes.
- `callWindow.showNormal()` removed the `visible: Voice.inCall` binding. Use
  `Main.showCall()`, which restores it.

The echo the person heard came from `interrupt_by_voice`: it was on while they
used speakers. I switched it off in their settings. The call now waits 0.7 s
after Akira stops speaking, where it waited 0.4 s. On speakers, with the
default setting, a call listens only when Akira is not speaking.

## For you, when you are back

1. Look over `ChatMenu.qml`, `AllowPrompt.qml`, `SetupSheet.qml`, the Chats
   tab of Settings, and the keep buttons, and bring them to the house style if
   they are not. The screenshots in the tests' `AKIRA_REVIEW_DIR` show them in
   both themes.
2. The rows of `FormRow` show only `title`. Several sheets pass a
   `description` that is never drawn. If that was deliberate for the minimal
   UI, the setup sheet already draws its own detail lines. If not, it is worth
   restoring.
3. Handoff 05's list is done, so there is nothing more to build for chats.

## Tests

- `test_qml_chat_menu.py`, `test_qml_allow_prompt.py`,
  `test_setup_screen.py` and `test_qml_voice.py` drive the real window by
  mouse and keys, the first two at 100% and 150%.
- The full suite runs in a clean worktree for each commit; the counts are in
  each commit message.
