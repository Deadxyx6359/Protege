# Claude → Codex: the library, and answers that say when they could not be checked

The person asked Akira how to read an analog pin on an STM32 Nucleo-G474RE.
The local model answered with STM32F4 names that do not exist on a G4. The
person also found there was no way to give Akira a document from the window.
They asked for both to be fixed, and for Akira to say so when it cannot answer
confidently. Codex was away, so I built the interface parts. The contract is in
`QML_BRIDGES.md`, under "The library" and "Answers about a chip or board".

## Interface I added, for your review

- `DocumentsView.qml`:
  - "Add documents…" in the header;
  - a "Your library" panel in the view's empty state, listing what was added,
    with Add files…, Add a folder…, and Remove, which asks first;
  - the file and folder pickers.

  The panel shows only while no folder is open. If you would rather have the
  library always reachable, a small "Library" row near the top would do it.
- No new chat interface. Checked answers are ordinary reply text: a
  "**Not checked:** …" first paragraph, or a "Checked: …" / "Check before
  using: …" note at the end. They read fine as Markdown; a quieter style for
  those notes would be welcome.

## Worth knowing

When a `Repeater` delegate calls a slot that changes the model, the delegate
is destroyed mid-handler, and the next line fails with "root is not defined".
Remove in the library panel holds `root` and the path in local variables
before calling. Any delete-from-list button needs the same.

## Tests

- `test_qml_library.py` drives the panel.
- `test_library.py` covers the library, the bridge, and the chat end to end.
- `test_grounding.py` checks Akira's real F4 answer against G4 headers, and
  flags `ADC_SAMPLETIME_480CYCLES` and `__HAL_RCC_ADC1_CLK_ENABLE`.
