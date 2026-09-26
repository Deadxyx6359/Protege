# Claude → Codex: using Akira with its real models (2026-09-26)

Backend only; no bridge or QML API changed. Everything below is committed and pushed.

## Fixed, each checked again with the real models
- **Content pipeline** (6128793): a gatherer reads first, and the files it read go on to the drafter and critic as read. The critic checks each date, name and number against them. Agents are told which folders their file tools can reach, so they no longer guess `/path/to/…`. Grounded agents (gatherer, drafter) are told to read before answering. Titles skip "Dear …," and drop `**`. The newsletter now has the right dates and the committee news.
- **Chat** (2afe38e, 1642c3e): "how many days until …" and "what day was …" are counted in code, for written dates, Christmas and Easter. When the notes were searched and nothing matched, the model says "I couldn't find that in your notes." Maths comes as plain text, not LaTeX.
- **Memory** (4a2f387): the distiller is told the vault's note names, so it adds to existing notes. An addition is only proposed when the person named that note's subject. It keeps what the person said, not the assistant's suggestions, and does not invent the person's gender.

## Still open
- Voice accuracy loopback (Kokoro → Whisper, with no microphone) was not run.
- The 8B model still sometimes proposes a memory note for a recipe it suggested, and the pipeline's critic sometimes asks for private detail. Both are reviewed by the person before anything is kept or published.
- The README row for this handoff is not added: `docs/handoffs/README.md` has Codex's uncommitted edits, so I left it alone. Please add a row (48) and move **Latest**.
