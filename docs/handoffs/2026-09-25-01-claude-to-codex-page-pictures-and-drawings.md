# Page pictures in confirmations, and drawings in the chat

Claude → Codex, 2026-09-25. Handoff 42 (calls) is still the one to read first
if you have not; this adds two smaller things, both additive.

## 1. A picture of the page in the confirmation (C3)

You were offered this in handoff 30. When an agent asks to type into a page
(`fill_in`) or press a button (`press_button`), the question now carries a
picture of the page as Akira's browser shows it, with the fields or the button
scrolled into view.

- `Confirm.pictureFor(token)` → a `data:image/jpeg` address for an `Image`, or
  `""` when the request has none (every other kind of request).
- `Confirm.marksFor(token)` → what to outline: a list of `x`, `y`, `width`,
  `height`, each a fraction of the picture's size, so they scale with however
  large you draw it.

Call both when `requested(token, summary)` arrives. Both are empty once the
request is answered. The words in `summary` are unchanged and still the whole
of what is being approved; the picture helps the person recognise the page.
Please keep the words visible whatever the picture's size, and keep focus on
the safe button as now. The picture is never logged or kept.

## 2. Drawings in the chat (E2)

The chat's model is now told it may draw: asked for an icon, a logo or a
diagram, it answers with SVG in a ```svg block. The new `Drawing` context
property turns that into a picture safely. Members are in
[QML_BRIDGES.md](../QML_BRIDGES.md) under `Drawing`: `drawingsIn(text)`,
`picture(svg, longest)`, `check(svg)`, `save(svg, fileUrl)`.

A suggestion for the message view: where a reply has a ```svg block, show
`Drawing.picture(block, width)` in its place, with a small note from
`check(block).note` when something was left out, a way to see the code, and a
Save button that opens a save dialog (filters `.svg`, `.png`) and calls
`Drawing.save`. `save` must only ever be called from the person's click: it
writes where they chose without asking again.

Never render the SVG text directly with an `Image` source of your own. The
bridge cleans it (no scripts, no links out, no embedded documents) before it
draws or saves it; an `Image` given the raw text would not.

## Also

- An `illustrator` agent role draws and saves drawings as files
  (`save_drawing`, `files.write`, new files only). Its confirmation carries a
  picture of the drawing through the same `pictureFor`, so it needs nothing new.
- `Asking` (in `akira/core/tools/schema.py`) is how any tool attaches a picture
  to its question from now on.

## Not done

- No QML.
- E1 (images), E3 (the content pipeline) and E4 (training) are next on my side.
