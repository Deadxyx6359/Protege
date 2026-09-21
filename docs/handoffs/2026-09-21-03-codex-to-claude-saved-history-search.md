# Find saved chats and agent answers by their contents

Codex → Claude, 2026-09-21. Completes the search coordination in handoff 02
and includes the earlier Accounts pass (handoff 01) in the same UI checkpoint.
Usage reached 91% of the five-hour window before committing.

## What the person can do

- Sidebar search matches saved user/assistant message bodies as well as titles,
  with short plain-text excerpts and visible search progress. Opening a match
  uses the existing conversation/project restoration flow.
- Research searches questions and final findings within the current project's
  research team. Code/Agents task history searches tasks and final answers,
  retaining team/project filters and the explicit all-projects toggle.
- Search result menus stack excerpts below titles. Empty results leave a usable
  search box; clearing restores the list. A Research answer no longer remains
  selected after the filter excludes it.
- Long sidebar lists no longer paint vector icons over the footer in Qt's
  software renderer: the scroll viewport owns a render layer.

## Implementation and boundaries

The additive contract is documented in `QML_BRIDGES.md`:
`Chat.historySearch` (child QObject, search/clear/results/busy/note) and
`Agents.searchRuns(query)`. `ui/history_search.py` owns matching, excerpts and
the conversation worker. Only one worker runs at once; a pending request is
replaced when typing changes and stale completions cannot publish. Shutdown
cancels publication, including when a file read finishes after Qt destruction.

Search examines at most the newest 200 conversation summaries, at most 32 MiB
of saved files, and returns the newest 40 matches. Size/skipped/result limits
are disclosed. The unfiltered sidebar still shows 40 recents. Invalid ids and
linked files are refused. System prompts/messages are excluded. Agent search
uses the existing 60-run in-memory archive. Queries have a 200-character cap;
all case-folded whitespace-separated terms must match somewhere in the title
or body. No regex syntax, semantic model, network, source fetch or new index.

Existing saved answers may quote source text, as before. Searching an archived
answer does not grant access to the original source or artifact. Their preview
permissions remain independent. Archive formats and core stores are unchanged.

## Evidence and remaining work

**136 tests passed in 118.42 seconds**, spanning history search, investigations,
Chat/Agents bridges, chat context, real-window history/accounts/branding/
navigation/research/code/documents/settings/links/accessibility/text formats,
views, shell, Qt network guard, atomic file saves, and Accounts bridge.
`python verify_offline.py` passed on the working tree (including Claude's
concurrent checker changes); `git diff --cached --check` passed. No live
accounts, websites or real models were used by this validation.

New tests cover case folding, body-only matches, system-text exclusion, corrupt
and missing files, result limits, cancellation, refresh after deletion, and
single-worker/latest-query publication. Real-window tests search a chat older
than the 40 visible recents, open its original project, test no-match/clear,
and verify research/team/project boundaries at 100% and 150% scaling.

Screenshots: ignored local `artifacts/scenes/ui-audit/history-sep21/`.
Inspected dark/light sidebar results, compact task history, and compact research
results. A local matching-only timing check over 60 60,000-character answers
took 13.1 ms; this is not a full end-to-end performance benchmark.

Next: memory provenance and scheduled-run detail, findings export, Drive/Canvas
source cards, and the hand-over-window banner. A physical GPU/animation pass is
still useful. No voice work was added here.

Concurrent Claude changes to `verify_offline.py`, `tests/test_verify_offline.py`
and `akira/core/voice/` are intentionally excluded, as are older untracked
branding explorations. Phone Link landed in `bbe04ff` during the UI work.
