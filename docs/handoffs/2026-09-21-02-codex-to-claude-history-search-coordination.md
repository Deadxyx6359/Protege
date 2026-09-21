# Local history search coordination

Codex → Claude, 2026-09-21. Starting the next UI pass after Accounts.

Additive shared seam changes planned: `Chat.historySearch` will expose a child
QObject for asynchronous search of the existing recent saved-conversation
snapshot, with bounded plaintext excerpts and cancellation of stale queries.
`Agents.searchRuns(query)` will search the already-loaded interactive run
archive and return result summaries; QML retains current project/team filters.
No model, network, source fetch, new permission or archive-format change.

Implementation belongs to UI helpers and the existing Chat/Agents bridges;
the core conversation store remains untouched. Will document the final API in
QML_BRIDGES.md and report validation in a completion handoff. Other backend
changes and older untracked branding drafts remain untouched.
