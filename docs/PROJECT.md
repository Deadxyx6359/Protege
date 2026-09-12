# Akira — the project

> **Now called Akira**, after Akira Nakashima, and renamed throughout: the
> package is `akira`, the QML module `Akira`, the settings folder
> `%LOCALAPPDATA%\Akira`. That folder holds the person's permissions, schedule,
> activity log and saved credentials, so it is moved from
> `%LOCALAPPDATA%\Protege` at the first start after the rename, in one step, and
> used where it is until it can be (`core/config.py`, `migrate_config`). Kept
> on purpose: the legacy app's `.protege` folder inside a vault, the name sealed
> into saved credentials, the `PROTEGE_PLUGIN` name plugins declare, and the
> repository folder's own name.

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

## 1. What Akira is

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
| Coding agent, Claude-Code-like, reads/writes/runs code via VS Code | **Done** — on the tool gate: check, run, test, commit, push, open in VS Code. A push uses the person's own git login, never forces, and is asked each time | A8 |

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
| Web search | **Done**: DuckDuckGo, under its own permission that reaches DuckDuckGo and nothing else | C2 |
| Full computer use — forms, posting, reservations, scraping without APIs, job applications, product testing | Fine — Playwright drives a real browser | C3 |
| Screenshots | **Done**: agents read the words on screen; the person can save a capture where writing is allowed | C4 |
| Email, calendar, text, Canvas, docs | Fine, per-connector permissions | C5 |
| Banking | **Read-only, permanently** | C5 |
| Monitoring agent — watch for changes | **Folders, pages and feeds done**: changes wake scheduled jobs, which can put up notices or set an agent to work. Inboxes after C5 | C6 |
| Time-based and event-based processes (daily/weekly/monthly/custom) | **Done** | A6 |
| Location and time awareness | **Done**: agents and the chat are told the date and time, and the place, time zone and weather with `location.read`; the scenes know the hemisphere and the weather | C7 |
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
6. **The network has one door.** `verify_offline.py` proves that no
   networking module is reachable from the entry points except the audited
   chokepoint (C1, `core/net/client.py`), and that nothing else can open the
   runtime guard; it runs in the suite. Nothing connects to a site the person
   has not allowed.
7. **`model.cloud` is the only door to a cloud model**, off by default, never a
   silent fallback.
8. **Irreversible actions confirm individually**, regardless of any grant. The
   grant says an agent *may try*; the confirmation is a separate promise.
9. **A routine security audit runs on a schedule** (A7) and its findings are
   surfaced, not logged quietly.

---

## 4. Architecture

```
akira/
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

- **Claude** — `akira/core/**`, `akira/security/**`, and matching tests.
- **Codex** — `akira/ui/qml/**`, `akira/design/**`, scene `.js`,
  `tools/preview_scenes.py`.
- **Shared, coordinate first** — `akira/ui/bridge/**`.

Before committing, check file mtimes. Work from the other agent arrives
mid-session and must not be swept into a commit unreviewed.

### 4.2 The legacy layer

The original knowledge-lock Akira still supplies `documents.py`, `memory/`,
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
*Since:* `AgentsView.qml` draws a team as its members in working order, with
the hand-offs lit as they happen (handoff 13).
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
flags reaching for credentials or Akira's own settings (always critical),
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
signing, lazy fetch). VS Code starts without cmd.exe.
*Done, push:* `git_push`, the way the person would: their own git login, so no
credential passes through Akira; the checked-out branch only, never forced;
https and ssh remotes only; and a question that names the address and how many
commits, every time. git is its own process, out of the network guard's sight,
so `vcs.write` and that question are the controls, and nothing a repository's
own configuration names (hooks, credential helper, ssh command) is run. The
implementer may propose commits and pushes.

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
*Done since:* the indexes drop their stored copy of anything the grants stop
covering as soon as they change, and once at each start for grants that
expired meanwhile. Covered means allowed globally or in any project. The
sweep reads only the index databases, and deletes one that cannot say what it
holds.
*Still to do:* embeddings as a second ranked list for the same fusion.

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
*Still to do:* retention settings for conversations themselves. The review
screen is `MemoryView.qml` (handoff 14): a refused accept offers writing for
that note's folder only, never the whole vault.

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
checks every project's grants. Bridge: `Projects`. The sidebar lists the real
projects, and `ProjectSheet.qml` makes one or shows the open one (handoff 14).
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

**C1 ✅ The network chokepoint** — `core/net/`, tool `fetch_page` in `core/tools/builtin/web.py`
Every outbound request in the entire application goes through one audited
module that checks `net.http` against the host scope, records the request, and
enforces timeouts and size caps. `verify_offline.py` is updated to assert that
this is the *only* path — the core must still prove nothing else opens a
socket.
*Why first in C:* every item below is a client of it. Written second, each one
would need retrofitting. It is also what finally allows `git push`, left out
of A8 on purpose.
*Done, as proposed and approved:* `core/net.fetch` is the one way out. Its
module, `client.py`, is the only code besides the guard that may import the
network, and `verify_offline.py` names exactly those two exemptions and fails
if any other module opens the guard (`netguard.admitting`). Requests are
`https://` only, certificates verified; a site that leads to this machine or a
private network is refused; `net.http` is checked for every hop, redirects
included (at most five); the connection goes to the address that was checked,
never looked up again; responses are capped at 5 MB and 20 seconds; no cookies
or credentials are sent; every request is audited with its query string left
out. The guard lets a connection through only inside the chokepoint, on that
thread, to that address. A grant names a site plainly: a bare top-level
domain, an address or a wildcard is refused. `fetch_page` gives agents pages,
and PDFs, as text framed as material rather than instructions; the gatherer
role has it. The README's firewall advice now says what blocking costs.
*The interface's own door, shut:* Qt fetches web addresses in QML itself
(pictures, including those in Markdown and HTML text, fonts, `XMLHttpRequest`)
in C++, out of sight of both checks. Every engine now refuses the network
(`security/qtguard.py`); `verify_offline.py` fails on an engine made without it
and on QML that imports its own connection; and pictures in replies are served
as links, because Qt opens `file://server/…` as a file and Windows as a
network share.
*Still to do:* the clients C3 browser and C5 connectors. Search (C2) uses it
under its own permission; `git push` is done under A8 with its own controls,
since git is a process of its own.

**C2 ✅ Web search** — `core/net/search.py`, tool `web_search` in `core/tools/builtin/web.py`
*Done:* DuckDuckGo, as the person chose: its plain HTML results page, no
account and no key, one GET through the chokepoint. `web.search` is its own
permission, and the chokepoint is told that under it the only host is
DuckDuckGo's, so a query reaches DuckDuckGo and nobody else, redirects
included, whatever `net.http` allows. The words searched for stay out of the
activity log with the rest of the query string. Adverts are left out, the
engine's wrapped links are unwrapped, and results reach agents framed as
material; reading one is `fetch_page` under `net.http` for that site. When
DuckDuckGo asks whether a person is searching, the answer is "try later".
The gatherer may search.

**C3 ○ Browser and computer use** — `core/tools/builtin/browser.py`
Playwright driving a real browser: navigate, read, fill, click, scrape without
APIs. **Every irreversible interaction confirms** — submit, post, purchase,
apply. Job applications stage a draft and stop.

**C4 ✅ Screen capture** — `core/screen.py`, tools in `core/tools/builtin/screen.py`
*Done:* the whole screen captured with GDI and encoded as PNG with zlib, and
its words read by Windows' own OCR through PowerShell: nothing installed,
nothing sent. `look_at_screen` gives an agent the text, framed as material, and
keeps no picture; `save_screenshot` writes a new PNG only where `files.write`
allows, after a yes. Both need `screen.capture`, now rated high risk.

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
*Done, pages and feeds:* through the chokepoint, held to `net.http` for the
site at every look. A page is compared as readable text, line by line
(`page.changed` with the new lines); a feed, RSS or Atom, by its entries
(`feed.item` each, `feed.changed` per look). Words narrow either. Looked at
hourly by default, never more often than every 15 minutes. What was seen
survives a restart. Addresses in events lose their query strings. A feed with
a document type is refused before anything is expanded. A job's agent is told
that what an event carries is material, not instructions.
*Still to do:* inboxes, which need C5.

**C7 ✅ Location and time awareness** — `core/context/place.py`, `core/context/weather.py`, bridge `ui/bridge/place.py`
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
*Done, the weather:* read from Open-Meteo, which needs no account or key,
through the chokepoint, and only while `location.read` and `net.http` for
open-meteo.com are both granted, checked before every reading. The position is
kept to two decimals and sent to one (about 11 km); the log keeps the request
without it. Readings are turned into the scenes' own weather names, checked by
test against `scenes/world.js`, and bind `SceneHost.weather` through `Place`.
Every half hour in the background; a reading over three hours old is not
reported as now, and a reading for another place never is. Models are told it
with the place. A place can be looked up by name for its position, on the same
site, when the person asks.

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
| C | C1 Network chokepoint | ✅ |
| C | C6 Monitoring agent | ▶ folders, pages and feeds done; inboxes wait for C5 |
| C | C7 Location and time | ✅ |
| C | C4 Screen capture | ✅ |
| C | C2 Web search | ✅ |
| C | C3, C5, C8 Reach | ○ |
| D | D1–D3 Voice | ○ |
| E | E1–E4 Making | ○ |

**Tests at last commit:** 1808 passed, 2 skipped; `verify_offline.py`
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
