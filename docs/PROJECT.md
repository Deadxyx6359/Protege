# Protégé — the project

> **Renaming to Akira.** The product is now called **Akira**, after Akira
> Nakashima; Codex's logo concepts are in `docs/branding/`. The code, the
> `protege` package and the on-disk paths still use the old name. Renaming
> those is deliberate work, not a find-and-replace: the configuration folder
> (`%LOCALAPPDATA%\Protege`) holds the user's permissions, schedule, activity
> log and saved credentials, and moving it needs a migration so none of that
> is orphaned.

**This file is the canonical description and the work order.** Everything else
is detail hanging off it. If a document disagrees with this one, this one is
right and the other needs updating.

Stable IDs (`A4`, `C1`, …) name every work item. Use them in commits, handoffs
and conversation — "starting C1" is unambiguous, "working on the network thing"
is not.

---

## 0. Document map

| Document | What it is | Owner |
|---|---|---|
| **PROJECT.md** (this file) | What we are building, in what order, and why | Claude |
| [PLATFORM.md](PLATFORM.md) | The platform argument: scope honesty, the security inversion, hard lines | Claude |
| [REBUILD.md](REBUILD.md) | Interface and model layer; measured benchmarks; findings not to rediscover | Claude |
| [QML_BRIDGES.md](QML_BRIDGES.md) | **Living** API: every object QML can reach, and the rules for using it | Claude (shared seam) |
| [handoffs/](handoffs/README.md) | Point-in-time notes between Claude and Codex, dated and indexed | Both |

**Read order for a fresh session:** this file → the newest handoff addressed
to you in [handoffs/](handoffs/README.md) → [QML_BRIDGES.md](QML_BRIDGES.md)
if you touch the interface → REBUILD.md §"Findings worth not rediscovering"
before touching UI or tests.

---

## 1. What Protégé is

A local-first AI assistant that is also **a place where agents work**. Teams
that research, build, watch and automate, with real reach into the machine and
the network, and a second brain that keeps itself current without ever being
opened by hand.

It runs on one Windows machine with a 6 GB GPU. That constraint is not a
footnote; it decides which models exist and which features are possible. See
REBUILD.md §"This machine is the design constraint".

### The three things that make it not just a chat window

1. **Agents with real reach** — they read files, run code, drive a browser,
   watch for changes, and act on a schedule.
2. **A permission model that means it** — deny by default, read and write
   separable, every grant scoped, enforced structurally rather than by asking
   a model nicely.
3. **A second brain that maintains itself** — Obsidian is the store, but the
   user never opens Obsidian.

---

## 2. The full scope

Everything asked for, with an honest verdict. Verdicts come from REBUILD.md's
measured benchmarks, not from optimism.

### 2.1 Agents and orchestration

| Capability | Verdict | Item |
|---|---|---|
| Agent loop, prompted tool calling | **Done** | A3 |
| Multiple agents in teams (research team, software team) | Fine — Hermes-3-8B is built for tool calling and fits the card | A4 |
| Visual display of which model is doing what, and how agents interact | Fine — `Trace` carries it; UI is Codex's | A5 |
| Coding agent, Claude-Code-like, reads/writes/runs code via VS Code | **Done** — on the tool gate: check, run, test, git, open in VS Code. No push until C1 | A8 |

### 2.2 Knowledge

| Capability | Verdict | Item |
|---|---|---|
| Document management — .docx, .pptx, .xlsx, PDF | **Done**: read all four, create Word and Excel, edit Word and PowerPoint, set Excel cells. Creating decks from scratch still to come | B1 |
| Obsidian second brain, fully automated, never opened by hand | **Vault, index and retrieval done**: read, link, write with history and conflict checks, daily notes; ranked search by section over notes, documents and past conversations, merged into cited passages; conversations distilled nightly into proposed notes a person accepts. Projects next | B2 |
| Private RAG, local embeddings | Fine — no network involved | B3–B4 |
| General memory that updates regularly | Partly exists (legacy `memory/`), needs rebuilding on the new spine | B5 |
| Projects, easy to access and manage | **Projects, their own grants and the graph done**: create, open, rename, remove; a grant made in a project applies only while it is open; a tag map and a link graph of any folder of notes; its personality reaches the conversation, and what its conversations teach is proposed under its name | B6 |

### 2.3 Reach

| Capability | Verdict | Item |
|---|---|---|
| Web search | Fine | C2 |
| Full computer use — forms, posting, reservations, scraping without APIs, job applications, product testing | Fine — Playwright drives a real browser | C3 |
| Screenshots | Fine | C4 |
| Email, calendar, text, Canvas, docs | Fine, per-connector permissions | C5 |
| Banking | **Read-only, permanently** | C5 |
| Monitoring agent — watch for changes | **Folders done**: changes wake scheduled jobs, which can put up notices. Pages, inboxes and feeds after C1 and C5 | C6 |
| Time-based and event-based processes (daily/weekly/monthly/custom) | **Done** | A6 |
| Location and time awareness | **Local half done**: agents and the chat are told the date and time, and the place and time zone with `location.read`; the scenes know the hemisphere. Weather after C1 | C7 |
| Purchasing | Possible, but a person presses the button every time | C8 |

### 2.4 Voice

| Capability | Verdict | Item |
|---|---|---|
| Speech in | Fine — Whisper, real-time on this CPU | D1 |
| Speech out, ~6 voices, default feminine/professional/expressive | Fine — Piper or Kokoro, local | D2 |
| Live calls that survive the window being minimised, own widget | Fine | D3 |

### 2.5 Making

| Capability | Verdict | Item |
|---|---|---|
| Image generation | Workable — SDXL-Turbo or SD 1.5 fits 6 GB. Slow but usable | E1 |
| 2D / vector generation | Fine — it is a code-generation problem (SVG), not diffusion | E2 |
| Content pipeline | Fine | E3 |
| Local model training | **LoRA only.** QLoRA on a 7–8B in 4-bit fits, hours per run. Full fine-tuning does not fit this card, and patience does not change that | E4 |
| **3D model generation** | **Not locally.** Nothing producing usable 3D fits 6 GB. Cloud API or not at all | — |

### 2.6 Interface

Apple-like minimalism, uncluttered, Claude/Gemini in content density. Everyday
surface is **8-bit botanica**, time- and weather-dependent; the coding surface
is **8-bit space**. Work organised by type. Owned by Codex; see REBUILD.md.

---

## 3. Non-negotiables

These are settled. Changing one is a conversation, not a commit.

1. **Deny by default.** No "allow all" switch exists in the model or the UI.
   There are tests asserting its absence.
2. **Money moves only when a person presses the button.** Every time, no
   exceptions, no "don't ask again". Banking is read-only: there is no
   `bank.write` capability, so no tool can even request it.
3. **Nothing is posted publicly, sent, or submitted without confirmation.**
4. **Job applications are staged, never submitted unattended.**
5. **Credentials never reach a model.** Secrets go through DPAPI or are
   refused; there is no obfuscated fallback pretending to be encryption.
6. **The core stays offline-verifiable.** `verify_offline.py` proves no
   networking module is reachable from the entry points, and it runs in the
   suite. Network access lives behind one audited chokepoint (C1) — never
   imported ad hoc.
7. **`model.cloud` is the only door to a cloud model**, off by default, never a
   silent fallback.
8. **Irreversible actions confirm individually**, regardless of any grant. The
   grant says an agent *may try*; the confirmation is a separate promise.
9. **A routine security audit runs on a schedule** (A7) and its findings are
   surfaced, not logged quietly.

---

## 4. Architecture

```
protege/
  core/                  the platform — testable headless, no UI imports
    permissions/         capabilities, grants, scope matching, audit, secrets
    tools/               tool schema, the gate, built-in tools
    agents/              loop, protocol, trace, teams
    schedule/            time and event triggers, jobs, narrowed per-run policy
    review.py            the routine security review
    models.py            task-routed local inference
    conversation*.py     turn state and storage
  security/              path safety, offline verification support
  ui/                    Qt Quick shell + QML  (Codex)
    bridge/              the seam between core and QML  (shared)
  <legacy>               documents.py, memory/, knowledge_graph.py, projects.py,
                         skills/, vault.py — the original knowledge-lock app
```

**Rules.** Nothing in `core/` imports from `ui/` — the moment it does, the core
stops being testable headless. Nothing outside `core/tools/` performs a
privileged action directly; it goes through a tool so it is gated and audited.

### 4.1 Ownership

- **Claude** — `protege/core/**`, `protege/security/**`, and matching tests.
- **Codex** — `protege/ui/qml/**`, `protege/design/**`, scene `.js`,
  `tools/preview_scenes.py`.
- **Shared, coordinate first** — `protege/ui/bridge/**`.

Before committing, check file mtimes. Work from the other agent arrives
mid-session and must not be swept into a commit unreviewed.

### 4.2 The legacy layer

The original knowledge-lock Protégé still supplies `documents.py`, `memory/`,
`knowledge_graph.py`, `projects.py`, `skills/` and `vault.py`. These work and
are tested, but they predate the permission model and call privileged
operations directly. They are **not** to be extended in place; each is ported
onto the tool gate at the item that needs it (B1, B5, B6). Until then they stay
reachable from the legacy Tk surface only.

---

## 5. Backend work order

Ordered by dependency, not by appeal. **A tool written before the permission
model exists has to be rewritten once it does** — that principle produced this
order and overrides "what would be fun next".

Status: ✅ done · ▶ next · ○ not started

### Phase A — the spine

Nothing user-visible improves during A. Everything after it becomes possible.

**A1 ✅ Permission model** — `core/permissions/`
30 capabilities with read/write halves separable; `Policy`/`Grant`/`Decision`;
path, host and account scope matching that resolves before comparing; audit log
with redaction and rotation; DPAPI secret store. Fail-closed load.
*Done when:* adversarial tests cover traversal, sibling prefixes, symlink
escape, reserved device names, ADS, lookalike hosts, expiry, corrupt grants,
undeclared capabilities. **All present.**

**A2 ✅ Tool layer** — `core/tools/`
Tool schema with typed validated arguments; registry that filters structurally
so an ungranted capability yields no tool; per-requirement scope check at call
time; irreversible tools confirm; output capped. Four file tools.

**A3 ✅ Agent loop** — `core/agents/`
Terminating loop with a hard step budget; prompted tool-call protocol accepting
the shapes models actually emit; refusals end a run rather than spiralling;
`Trace` event feed; cooperative cancellation.

**A4 ✅ Teams and roles** — `core/agents/team.py`, `roles.py`
Named teams (research, software) with typed roles, a coordinator that routes a
task to the right member, and agent-to-agent messages emitted as `MESSAGE`
events with `to` set. Roles carry *narrowed* tool sets — a reviewer that cannot
write is a better reviewer.
*Why here:* `MESSAGE`/`to` already exists on the trace and nothing emits it, so
Codex's agent-interaction view currently renders an empty graph.
*Done when:* a scripted two-agent run produces a traceable hand-off, a member
cannot exceed the team's policy, and a failing member does not hang the team.

**A5 ✅ UI bridge** — `ui/bridge/`
Expose to QML: the capability catalogue and grant/revoke; the trace as a live
model; the confirm callback wired to a real dialog; the audit log as a list.
*Why here:* until `ToolContext.confirm` is wired, every write, send and submit
is denied — correct, but it means the UI is load-bearing. This unblocks Codex.
*Done when:* Codex can grant a scoped capability, watch an agent run live, and
approve a write, entirely from the QML shell.
*Note from the frontend:* worker callbacks must reach QML through **queued**
Qt signals — `Trace.listen` fires on the worker thread. The Research view
exists and deliberately shows no source or agent panels until a bridge with
real data backs them; do not add panels ahead of the data.
*Follow-up, after A8:* nothing could actually *start* an agent from QML, so
"watch an agent run live" was not reachable. The `Agents` bridge closes that,
and `Schedule.addJob` lets the interface create jobs.

**A6 ✅ Scheduler** — `core/schedule/`
Time-based (daily/weekly/monthly/cron/custom) and event-based triggers, durable
across restarts, each job running under its own scoped policy. Missed jobs
resolve explicitly — run late or skip — never silently.
*Why here:* monitoring (C6), the security audit (A7), memory distillation (B5)
and the content pipeline (E3) are all scheduler clients.
*Done:* daily, weekly, monthly (the 31st means the last day in shorter
months), every-N and five-field cron, plus event triggers with a mandatory
cooldown. Wall-clock local time, so DST does not shift jobs. Each run gets
the intersection of what the job asked for and what the user holds *now*, in
a policy that refuses to be saved. Missed runs coalesce into one late run or
an explicit skip. Five failures in a row pause a job with the reason.
Unattended runs cannot approve anything irreversible.

**A7 ✅ Routine security audit** — `core/review.py`
Scheduled review: grants that are broader than their use, capabilities granted
and never exercised, expired-but-present entries, refusal patterns suggesting a
prompt-injection attempt, secrets present without an owner. Findings surface in
the UI.
*Why here:* needs the audit log (A1) and the scheduler (A6), and every later
phase adds attack surface it should already be watching.
*Done:* runs daily at 09:00, late if the machine was off, and on demand. Also
flags reaching for credentials or Protégé's own settings (always critical),
grant-file tampering, mid-log damage, and permission changes in the window.
It only reads — it never revokes anything itself. Critical findings raise a
signal of their own rather than waiting in a list.

**A8 ✅ Coding environment on the gate** — `core/tools/builtin/coding.py`
Port the legacy coding surface onto the tool layer: run code, run tests, read
diagnostics, VS Code integration, git through `vcs.read`/`vcs.write`. Shell
access is `shell.run` — irreversible, therefore always confirmed.
*Done:* `check_syntax` (parses, never executes), `run_python`, `run_tests`,
`git_status`/`git_diff`/`git_log`/`git_commit`, `open_in_editor`. Code runs
behind the network guard with a scrubbed environment. Git is hardened
against config-driven execution (fsmonitor, hooks, credential helpers,
signing, lazy fetch). VS Code starts without cmd.exe. **No push** — it
waits for C1.

### Phase B — the second brain

**B1 ✅ Document tools** — `core/documents/`, tools in `core/tools/builtin/office.py`
Read and write .docx, .pptx, .xlsx; PDF text extraction (legacy `pdftext.py`
ports here). Round-trip fidelity matters — opening and saving must not destroy
formatting the user did not touch.
*Why first in B:* purely library work, no model or index needed, and it is the
"plugins for Word/PowerPoint" ask.
*Done:* standard library only. Edits are surgical: text is spliced into the
original XML, so every other byte and every other part is untouched, and the
tests assert exact bytes. Replacement spans Word's arbitrary runs. Spreadsheets
read with coordinates and real dates; cells keep their style. Creating never
overwrites. *Still to do:* creating a PowerPoint deck from nothing, which needs
a master and theme that can only be trusted once checked against PowerPoint.

**B2 ✅ Obsidian vault adapter** — `core/brain/`, tools in `core/tools/builtin/notes.py`
Read and write the vault as markdown: frontmatter, `[[wikilinks]]`, tags,
attachments, daily notes. Writes are atomic and conflict-aware, because the
user may have Obsidian open even if they never open it on purpose.
*Constraint:* the user never opens Obsidian. Anything requiring a manual step
there is a failed design.
*Done:* writing is automatic and never unrecoverable. Every overwrite first
saves the previous version, outside the vault, and `restore_note` brings any
version back. Replacing a note needs the version that was read, so an edit
made in Obsidian meanwhile is refused rather than lost. Links resolve as
Obsidian resolves them. Tags and links inside code are ignored. The daily
note follows the vault's own settings. `.obsidian` and every dot-folder are
never touched. Search, backlinks and the daily note are held to the granted
folder even when the vault root sits above it.
*Still to do:* attachments, and a file watcher so changes made on another
device reach the index (B3) without a rescan.

**B3 ✅ Local index** — `core/brain/index.py`
Local embedding model, vector store, incremental reindexing on file change. No
network.
*Done:* a lexical index — BM25 over SQLite, both in the standard library.
Notes are split at their headings, so a hit cites the section, and no one note
fills the results. Refreshing re-reads only files whose size or time changed
and re-indexes only those whose content did. The index holds only what the
grant allows, drops what it stops allowing, and filters again at query time.
A damaged database is deleted and rebuilt, never trusted.
*Deferred:* embeddings. `requirements.txt` rules out stacks that fetch model
weights; llama.cpp can serve an embedding model once one is configured, with
nothing new to install. `search` keeps its shape when they arrive and B4 fuses
both. A file watcher is also still to do: refresh is on demand, and cheap when
nothing changed.

**B4 ✅ Retrieval / private RAG** — `core/brain/retrieve.py`, `core/brain/corpora.py`, tools in `core/tools/builtin/knowledge.py`
Hybrid retrieval over vault, documents and conversations, with citations back
to source notes. Retrieval is a *tool*, so it is gated and audited like
anything else.
*Done:* `search_notes` answers from the index, and `search_documents` and
`search_conversations` join it, each ranked by section and held to its own
permission: `docs.read` for documents (Markdown and text files only where
`files.read` reaches too), and a new `memory.read` for past conversations, so
an agent that may read files still cannot trawl what was said in chat.
`retrieve.gather` searches the sources asked for *through the registry*, so
every search is checked and audited, merges them by reciprocal rank, keeps a
budget, and reports what was left out and which sources could not be
searched. `read_document` and the index share one document-to-text function.
*Done since:* each chat turn calls `gather` for the sources the person has
granted (`core/brain/recall.py`), as context for that turn only. A source that
is not granted is not tried, so it leaves nothing in the activity log.
*Still to do:* embeddings as a second ranked list for the same fusion, and
dropping an index's stored text when its grant is revoked rather than at the
next refresh.

**B5 ✅ Memory distillation** — `core/brain/distil.py`, bridge `ui/bridge/memory.py`
Scheduled consolidation of conversations into durable notes, deduplicated
against what exists. Supersedes legacy `memory/consolidate.py`; port its
pending/holding staging, which is good design worth keeping.
*Done:* a nightly job reads each conversation that changed — only the
exchanges since it was last read — and asks the local model what is worth
keeping. Answers become proposals in the configuration folder, never notes:
nothing indexes them, so unreviewed model output cannot shape an answer. A
proposal on a subject the vault already has becomes an addition carrying only
the lines the note lacks; one that adds nothing is dropped, and two
conversations proposing one note make one proposal. The job needs
`memory.read` and `vault.read` and writes nothing but proposals. A person
accepts through the `Memory` bridge, held to `vault.write` for that note and
audited; the write goes through the vault, so it can be undone, and a note
edited since is re-based rather than overwritten. The holding area is not
ported because nothing is deleted: the conversation stays where it was.
*Still to do:* the review screen (Codex, on `Memory`), and retention settings
for conversations themselves.

**B6 ✅ Projects reconciled** — `core/projects.py`, bridge `ui/bridge/projects.py`
Fold legacy `projects.py` and `knowledge_graph.py` onto the new spine: a
project owns notes, memory, skills, a personality override, **and its own
policy**, so granting an agent a folder for one project does not grant it
everywhere.
*Done:* projects are stored by id in the configuration folder (a name never
becomes a path) with a folder, a personality and their own grants. While a
project is open, work started from the interface runs under the global grants
plus the project's; the combined view is read-only, and where both hold a
capability the earlier expiry wins. Scheduled jobs keep the global grants
only, so what is on screen never changes what a nightly job may do. Removing
a project forgets it and its grants and leaves its notes. The security review
checks every project's grants. Bridge: `Projects`.
*Done since:* the graph, folded from legacy `knowledge_graph.py` onto the
vault: a tag map with nested tags as hubs, laid out the same way every time,
and the links between notes. Bridge: `Graph`.
*Done since:* the open project's personality reaches the conversation, for
each turn, alongside what was retrieved.
*Done since:* memory per project. A conversation keeps the project it began
in, whichever is open later, and a new note distilled from it is proposed
under `Memory/<project>/`. Additions still go to whichever note already
covers the subject. A removed project's conversations fall back to `Memory/`.
*Still to do:* skills, which wait for their own item.

### Phase C — reach

**C1 ○ The network chokepoint** — `core/net/`
Every outbound request in the entire application goes through one audited
module that checks `net.http` against the host scope, records the request, and
enforces timeouts and size caps. `verify_offline.py` is updated to assert that
this is the *only* path — the core must still prove nothing else opens a
socket.
*Why first in C:* every item below is a client of it. Written second, each one
would need retrofitting. It is also what finally allows `git push`, left out
of A8 on purpose.
*Proposed design, waiting for a go-ahead before any of it is built,* because
it ends the guarantee that nothing in Protégé can connect:
- One function, `core/net.fetch`, is the only code besides the guard allowed
  to import `socket`, `ssl` or `http.client`. `verify_offline.py` names it as
  the second and last exemption and proves nothing else reaches the network.
- `https://` only, certificates verified. Private, loopback and link-local
  addresses are refused, so a public name cannot be pointed back at this
  machine or the local network.
- `net.http` is checked for the host of every hop, redirects included (at
  most five). Responses are capped at 5 MB and 20 seconds. No cookies and no
  credentials are sent. Every request goes in the audit log with its query
  string redacted.
- The guard stays installed. It admits a connection only from inside
  `fetch`, on that thread, to the address `fetch` itself resolved and checked.
- Nothing connects until the person grants `net.http` for a host. The
  README's firewall advice changes from blocking everything to allowing
  this interpreter only the hosts granted.

**C2 ○ Web search** — `core/tools/builtin/search.py`

**C3 ○ Browser and computer use** — `core/tools/builtin/browser.py`
Playwright driving a real browser: navigate, read, fill, click, scrape without
APIs. **Every irreversible interaction confirms** — submit, post, purchase,
apply. Job applications stage a draft and stop.

**C4 ○ Screen capture** — `core/tools/builtin/screen.py`

**C5 ○ Connectors** — `core/connect/`
Mail, calendar, messages, Canvas/LMS, cloud docs, banking. Each is a separate
capability with its own scope, read and write independently grantable.
**Banking is read-only, permanently.**

**C6 ▶ Monitoring agent** — `core/agents/monitor.py`, bridge `ui/bridge/monitor.py`
Watch a page, folder, inbox or feed for change; run on the scheduler; notify or
trigger a follow-up agent.
*Done, the local half:* watched folders. Each look turns what changed into
scheduler events (`file.*` per file, `folder.changed` per look), so a job
waiting for a watch can run an agent over what arrived or put up a notice
with the new `notify` action (`notify.send`). A file is reported only once it
has settled. A watch is held to `files.read` at every look and pauses with a
reason when it is revoked. Polling, standard library only. Until this, the
scheduler's event triggers had nothing publishing to them.
*Still to do:* pages, inboxes and feeds, which need C1 and C5.

**C7 ▶ Location and time awareness** — `core/context/place.py`, bridge `ui/bridge/place.py`
Local timezone, season and weather already drive the scenes; this generalises
it so agents can reason about "now" and "here". Location is `location.read`,
scoped and revocable.
*Concrete integration point:* `SceneHost.weather` currently defaults to `clear`
and `southernHemisphere` is unbound — the renderer already handles every
weather preset, ocean state and wind value, so this is a connector binding, not
UI work. Fixed preview conditions are not real conditions; do not confuse the
two. Local time and season handling already works and must be preserved.
*Done, the local half:* every agent and every chat turn is told the date and
time. The time zone and a place the person sets are added only while
`location.read` is granted, checked each time. The season rule mirrors
`scenes/world.js` exactly, so the scenery and the assistant agree, and the
place's hemisphere gives `SceneHost.southernHemisphere` its binding through
the `Place` bridge. The scenes' own time and season handling is untouched.
*Still to do:* weather, which is a network reading and waits for C1.

**C8 ○ Purchasing** — staged only
Assemble the cart, present the total and the payment method, stop. A person
presses the button, every time. There is no unattended path and there will not
be one.

### Phase D — voice

**D1 ○ Speech in** — Whisper, streaming, push-to-talk and wake-word.
**D2 ○ Speech out** — Piper or Kokoro; six selectable voices; default feminine,
professional, expressive.
**D3 ○ Live call** — a session that survives the main window closing, in its own
always-on-top widget, with barge-in (the user interrupting mid-sentence) and a
visible mute that actually stops capture.

### Phase E — making

**E1 ○ Image generation** — SDXL-Turbo or SD 1.5 within 6 GB.
**E2 ○ 2D / vector** — SVG as a code-generation problem.
**E3 ○ Content pipeline** — scheduled multi-step drafting → review → publish,
with the publish step confirmed by a person.
**E4 ○ LoRA training** — QLoRA on a 7–8B in 4-bit, hours per run, checkpointed
and resumable.

### Throughout

- **Scenes** (Codex) — self-contained, and what makes the app pleasant to open.
- **Security audit** (A7) runs from the moment it exists.
- **Every new capability** ships with adversarial tests, not just happy-path.

---

## 6. Status board

| Phase | Item | State |
|---|---|---|
| A | A1 Permissions | ✅ |
| A | A2 Tools | ✅ |
| A | A3 Agent loop | ✅ |
| A | A4 Teams and roles | ✅ |
| A | A5 UI bridge | ✅ |
| A | A6 Scheduler | ✅ |
| A | A7 Security audit | ✅ |
| A | A8 Coding on the gate | ✅ |
| B | B1 Document tools | ✅ |
| B | B2 Obsidian vault | ✅ |
| B | B3 Vault index (lexical; embeddings deferred) | ✅ |
| B | B4 Retrieval | ✅ |
| B | B5 Memory distillation | ✅ |
| B | B6 Projects reconciled | ✅ |
| C | C1 Network chokepoint | ⏸ design written above; waiting for your go-ahead |
| C | C6 Monitoring agent | ▶ folders done; pages, inboxes and feeds wait for C1 and C5 |
| C | C7 Location and time | ▶ now and a set place done; weather waits for C1 |
| C | C2–C5, C8 Reach | ○ |
| D | D1–D3 Voice | ○ |
| E | E1–E4 Making | ○ |

**Tests at last commit:** 1600 passed, 2 skipped, 2 failed (the two legacy Tk geometry tests, which fail at clean HEAD too on this 960-px-tall display); `verify_offline.py`
passes. Update this line when it changes.

---

## 7. Working agreement

- **Timeline is months, not a month.** Extending is explicitly fine. Rushing a
  phase to reach the next one is not.
- **Each item ships tested.** A capability without adversarial tests is not
  done, because the interesting cases are all adversarial.
- **Findings go in REBUILD.md** §"Findings worth not rediscovering" the moment
  they cost more than ten minutes.
- **Handoffs are written, never refreshed.** A new one goes in `docs/handoffs/`
  at 90% session usage or on request, following the README there. What is
  true now belongs in the living documents, which change with the work.
- **Open source where it fits** — Hermes for tool calling, Whisper, Piper,
  Playwright, and other open agents rather than bespoke reimplementation.
