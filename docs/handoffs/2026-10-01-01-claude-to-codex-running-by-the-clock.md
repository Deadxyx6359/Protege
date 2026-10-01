# Claude → Codex: Akira keeps running when its window closes

The person asked for Akira to keep running in the background with its window
closed, like the Claude and ChatGPT apps, as long as it takes nothing from a
game. They also asked that quitting leave no process behind, and that the
model unload while hidden. They did not want it to start with Windows.

## What it does

- **Closing hides the window.** Akira goes on from its icon by the clock. The
  icon's menu has Open Akira, New chat and Quit Akira, and a click opens the
  window. The first close ever shows a notification saying Akira is still
  running and how to quit. Settings, General has "Keep running when closed"
  (on by default) and Quit. Ctrl+Q quits from anywhere in the window.
- **Hidden, it keeps out of the way:**
  - The model leaves the graphics card once nothing is answering, and the
    speech models are let go too. Measured: 5,683 MB with the model loaded,
    309 MB four seconds after closing.
  - The process runs in Windows' background mode. Idle while hidden, it used
    0.08 s of processor time in 10 s.
  - A scheduled job that needs a model waits while a full-screen program or
    another program holding a gigabyte or more has the card. The Schedule page
    says "Waiting for the graphics card: …" for such a job.
  - Notices become Windows notifications.
- **Quit ends everything.** Each program Akira starts through `subprocess` is
  put in a Windows job object, so it ends with Akira however Akira ends. The
  process also ends itself on a 45-second deadline. VS Code and the person's
  own browser are theirs and stay open.
- **One Akira at a time.** Launching it again brings the running one forward.
  Measured: the second launch was gone in 2 seconds.

## QML you would touch

- `Main.qml`:
  - `onClosing` asks `Background.hidesOnClose` first.
  - The sidebar's new-chat code is now `win.newChat()`, which the tray menu
    calls too.
  - A `Shortcut` handles Ctrl+Q.
- `SettingsSheet.qml`: the new row, the last one in General.
- `ScheduleView.qml`: `next(j)` reads `j.waiting`.

The `Background` bridge is in QML_BRIDGES.md. The tests are
`test_qml_background.py` (the real window), `test_background.py`,
`test_processes.py`, `test_quiet.py`, `test_schedule_card.py` and
`test_instance.py`.

## Watch out for

- The application is now a `QApplication`, because the tray icon and its menu
  are widgets. Tests still build `QGuiApplication`. Nothing in QML changes.
- Qt's `quit()` asks each window to close, and this window refuses while it
  hides on close. Quit goes through `Background.quit()`, which uses `exit`.
  `Qt.quit()` from QML is wired to it as well.
- The router's `loaded` must stay lock-free. The window's thread asks it on
  closing, and a load holds the router's lock for seconds. The first version
  froze there.
