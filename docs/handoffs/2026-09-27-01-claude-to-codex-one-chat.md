# Claude → Codex: one chat for everyday, code and research (2026-09-27)

The person asked for the Everyday, Coding and Research chats to become one
chat. That chat should work out what each message wants and use the best
model for it. The person asked for Claude to do the backend and for Codex to
build the interface. The backend is done, committed and pushed. The contract
is in `docs/QML_BRIDGES.md`, under `Chat`, in the section "One chat: everyday,
code and research".

## What the backend does

- Every message is sorted as `everyday`, `code` or `research` before it is
  answered (`akira/core/intent.py`). There is no model call and no delay.
  Each kind has its own model:
  - `everyday` → the chat model (Qwen3-8B);
  - `code` → the coding model (Qwen2.5-Coder);
  - `research` → the `deep` route, which is the chat model unless something
    larger is set up.
- Short follow-ups keep the kind of the turn before ("and in Rust?", "what
  about Webb?"). "Thanks!" and "ok" never trigger a search.
- **Research** turns run a gatherer first (`akira/core/brain/research.py`).
  - It reads only what the grants already allow: files, notes, documents,
    Drive, web search and allowed sites. It is read-only and never asks for
    confirmation.
  - The answer is written from what was actually read, and `lastSources`
    lists the pages and files.
  - If the answer names a source that was not read, a "Note: nothing from X
    was read…" line is added to the reply.
- The person can pin a kind with `Chat.setMode("code")` etc., or go back to
  `"auto"`.

## What the interface needs

1. **Retire the per-workspace conversations.** Your uncommitted work splits
   each project's chat into Everyday, Code and Research (`switchWorkspace`,
   `Conversation.workspace`, the workspace test file). The person has now
   asked for the opposite. There should be one conversation list and one chat
   view.
   - I merged my changes into your working copy of `akira/ui/bridge/chat.py`
     without removing anything of yours. Your workspace code is still there,
     beside mine, for you to take out. My commit has only my part.
   - The committed `chat.py` has no workspace code. When you commit, keep my
     parts: `choose`, `_previous`, `_looked_in`, the research step and the
     mode slots. Drop the workspace ones.
2. **Show the choice quietly.** Put the kind and the model beside the
   composer, for example "Research · Qwen3-8B", built from `intentLabel` and
   `routeLabel`. Add a small Auto / Everyday / Code / Research switch from
   `modes`, `mode` and `setMode`. Keep it minimal, per your handoff 06.
3. **Progress while researching.** `stage` shows `Researching` and then each
   step: `Searching the web for “…”`, `Reading en.wikipedia.org`, `Reading
   budget.xlsx`, and so on. A research turn takes 10 to 35 seconds with the
   real models, so these lines are the progress indicator.
4. **Sources.** `lastSources` now also has `web` entries (cite: the page
   address) and `files` entries (cite: the file name). Show the site or the
   file name under the answer.
5. **Tools stay tools.** Investigations and team runs (Research page) and the
   software team and code editor (Code page) remain as they were. Only the
   separate chats go.

## Tried with the real models, one conversation

| Message | Sorted as | Result |
|---|---|---|
| goldfish names | everyday | Qwen3-8B |
| a Python palindrome function | code | Qwen2.5-Coder |
| "now make it ignore spaces and case" | code (follow-up) | Qwen2.5-Coder |
| spending according to budget.xlsx | research | the sheet was read |
| Hubble's launch, "check Wikipedia" | research | the article was read |
| "what about the James Webb telescope?" | research (follow-up) | its article was read: Kourou, Ariane 5 |
| "and which one is further from Earth?" | research (follow-up) | both articles were read |
| "Thanks!" | everyday | no search |

The full suite passes in a clean worktree at HEAD, apart from the two known
settings-geometry tests, which your uncommitted `settings_window.py` fixes.
The offline audit passes.
