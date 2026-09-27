# Claude → Codex: a full test of Akira's functions, and what it changed (2026-09-27)

Thanks for handoff 02, the one-chat UI. The person then asked for three
things: DuckDuckGo and VS Code connected and tested, and a test that uses all
of Akira's functions. All of it is committed and pushed. None of your files
were staged.

## What was tested

- **Phase 1, every tool (27 of 27).** All 53 tools, called as agents call
  them, with scoped grants in a scratch folder. This includes real web search,
  Wikipedia, the browser, a form typed into and pressed on Wikipedia, and the
  page handed over in a window. Every refusal was checked too: an action not
  approved, a folder outside a grant, a site not allowed, and a git push to a
  folder remote.
- **Phase 2, the app with the real models (25 of 25).**
  - Place, weather and time zone; projects.
  - The one chat: everyday, code, research from a spreadsheet and from
    Wikipedia, day counts, notes, identity, and a pinned kind.
  - Drawings; the illustrator; the research and software teams; the errands
    agent in the browser.
  - A scheduled agent job, the content pipeline, and the security review.
  - A folder watch → event → notice job → notice.
  - Memory distilled and accepted into the vault.
  - A picture on the card.
  - A call: Kokoro spoke a question into a scripted microphone, Whisper
    heard it, and the chat answered it.
  - LoRA training, then the adapter switched on and answered with. It was
    removed afterwards.
- **Phase 3, the person's real accounts (read-only).** Google now refuses
  Akira's sign-in for Gmail and Calendar ("withdrawn or expired"), so the
  person needs to reconnect in Settings → Accounts. Drive, Canvas and the bank
  aren't connected, and each says so. Phone Link's window wasn't open.

## Changes that touch the interface

- **`Chat.lastSources` is what the answer drew on** (`docs/QML_BRIDGES.md`,
  updated). While a turn runs, it lists what was found. When the answer ends,
  a searched passage (notes, documents or conversations) stays only if the
  answer cites it. Research's `web`, `files` and `drive` entries stay. Before
  this, a note about the allotment was listed under "What is 15% of 240?".
- **A notify job without `notify.send` among its grants is refused when it is
  made.** Your Watch page already sends that grant, so nothing changes there.
- **`hand_over_page` opens in Microsoft Edge** when Playwright's windowed
  Chromium won't start. On this machine it fails with "side-by-side
  configuration is incorrect"; its headless build is fine. It is the same
  isolated context and proxy.

## Backend-only changes, for the record

- Pressing a button that a page rebuilt after typing now works. Wikipedia's
  search does this: the control is found again by its kind and exact label,
  and only if exactly one control matches.
- Web search falls back to DuckDuckGo's Instant Answer API when the results
  page asks whether a person is searching.
- Agents are told where the notes vault and the documents folders are.
- The illustrator runs on the chat model.

## For the person, not the code

Their Security review will show "fulltest was refused … times within ten
minutes". Phase 3 deliberately tried actions their grants don't allow, as a
check. It is expected, and the activity log was not edited.
