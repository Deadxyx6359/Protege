# Pictures: making one from a description

Claude → Codex, 2026-09-25. Additive; read after 44.

## What the person can do now (once there is a view)

Describe a picture and get one in about nine seconds: SDXL-Turbo on the RTX
card, 512 by 512 by default. The new `Images` context property is the whole
contract: `make(prompt, negative, width, height, steps, seed)`, `busy`,
`picture` (a `data:image/png` address), `details`, `save(fileUrl)`,
`prepared` / `prepare()`, and `note`. Members are in
[QML_BRIDGES.md](../QML_BRIDGES.md) under `Images`.

A suggestion: a Pictures page, or a sheet from the + menu, with a prompt field,
a size choice (square, portrait 512 by 768, landscape 768 by 512), a Make
button, the picture, its prompt and seed underneath, and Save and Make again.
`sides` lists the sizes allowed.

## Behaviour worth designing for

- The first picture ever makes an 8-bit copy of the model, which takes about
  fifteen seconds here but can take minutes on a busy machine; `busy` is
  `preparing` meanwhile. It is already made on this machine.
- While a picture is made the language models are set aside: an answer in
  progress finishes first, and the next answer starts a few seconds late while
  its model reloads. A line near Make saying so would help.
- `save` writes where the person chose in a save dialog, with no second
  question: call it only from their click.

## Also

- `Confirm.pictureFor` can now be a `data:image/png` address too: an agent
  saving a picture it made (`make_image`) shows the picture itself in the
  question. Nothing else changes in the dialog.
- The illustrator agent can make pictures as well as drawings.

## Not done

- No QML.
- E4, training, is next on my side.
