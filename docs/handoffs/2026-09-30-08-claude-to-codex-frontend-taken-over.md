# Claude → Codex: your work is committed, and Claude holds the interface now

The person asked Claude to commit your work and to take over the frontend as
well as the backend.

## Your work, committed

Everything you had in the tree is committed as you left it, in `900665d`:

- the three sections (Chat, Library, Tools) and the agent roster;
- the megastructure and cave-garden scenes, with their art in
  `akira/ui/assets/scenes`;
- the matched palettes and the interface polish;
- your tests, your handoffs 58 and 62 to 69, and the branding concepts and
  prompts.

The full suite passed on it first: 2,941 tests, plus `verify_offline.py`.

## Since then

- **Search in Accounts.** The Accounts sheet has a fourth section, Search,
  for a Tavily key that makes web search cover the whole web. It's in
  QML_BRIDGES under `Accounts`.
- **Calendar page.** The calendar page from handoff 71 is in the Library.

## If you work on Akira again

Read `docs/PROJECT.md` and `docs/QML_BRIDGES.md` first. Claude now edits QML as
well, so check `git status` and the latest handoffs before starting, and say
in a handoff what you are taking.

Still open from earlier:

- **Clicks through a closing sheet.** A press on a closing sheet's button can
  reach the page underneath (handoff 71). The calendar page guards against
  it; `Sheet.qml` itself does not yet.
- **Setup sheet height.** With six rows, the setup sheet needs a scroll at
  700 pixels tall.
