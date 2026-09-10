# Protégé — the project

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
| [BACKEND_HANDOFF_FOR_CODEX.md](BACKEND_HANDOFF_FOR_CODEX.md) | Live API surface Codex binds the UI to | Claude → Codex |
| [SCENES_HANDOFF_FOR_CLAUDE.md](SCENES_HANDOFF_FOR_CLAUDE.md) | Scene work handed back the other way | Codex → Claude |

**Read order for a fresh session:** this file → the handoff for your role →
REBUILD.md §"Findings worth not rediscovering" before touching UI or tests.

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
| Coding agent, Claude-Code-like, reads/writes/runs code via VS Code | Largely done in the legacy app; needs porting onto the tool gate | A8 |

### 2.2 Knowledge

| Capability | Verdict | Item |
|---|---|---|
| Document management — .docx, .pptx, .xlsx, PDF | Fine — library work, no model needed | B1 |
| Obsidian second brain, fully automated, never opened by hand | Fine | B2 |
| Private RAG, local embeddings | Fine — no network involved | B3–B4 |
| General memory that updates regularly | Partly exists (legacy `memory/`), needs rebuilding on the new spine | B5 |
| Projects, easy to access and manage | Legacy `projects.py` exists; needs reconciling | B6 |

### 2.3 Reach

| Capability | Verdict | Item |
|---|---|---|
| Web search | Fine | C2 |
| Full computer use — forms, posting, reservations, scraping without APIs, job applications, product testing | Fine — Playwright drives a real browser | C3 |
| Screenshots | Fine | C4 |
| Email, calendar, text, Canvas, docs | Fine, per-connector permissions | C5 |
| Banking | **Read-only, permanently** | C5 |
| Monitoring agent — watch for changes | Fine | C6 |
| Time-based and event-based processes (daily/weekly/monthly/custom) | Fine | A6 |
| Location and time awareness | Fine | C7 |
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

**A4 ▶ Teams and roles** — `core/agents/team.py`, `roles.py`
Named teams (research, software) with typed roles, a coordinator that routes a
task to the right member, and agent-to-agent messages emitted as `MESSAGE`
events with `to` set. Roles carry *narrowed* tool sets — a reviewer that cannot
write is a better reviewer.
*Why here:* `MESSAGE`/`to` already exists on the trace and nothing emits it, so
Codex's agent-interaction view currently renders an empty graph.
*Done when:* a scripted two-agent run produces a traceable hand-off, a member
cannot exceed the team's policy, and a failing member does not hang the team.

**A5 ○ UI bridge** — `ui/bridge/`
Expose to QML: the capability catalogue and grant/revoke; the trace as a live
model; the confirm callback wired to a real dialog; the audit log as a list.
*Why here:* until `ToolContext.confirm` is wired, every write, send and submit
is denied — correct, but it means the UI is load-bearing. This unblocks Codex.
*Done when:* Codex can grant a scoped capability, watch an agent run live, and
approve a write, entirely from the QML shell.

**A6 ○ Scheduler** — `core/schedule/`
Time-based (daily/weekly/monthly/cron/custom) and event-based triggers, durable
across restarts, each job running under its own scoped policy. Missed jobs
resolve explicitly — run late or skip — never silently.
*Why here:* monitoring (C6), the security audit (A7), memory distillation (B5)
and the content pipeline (E3) are all scheduler clients.

**A7 ○ Routine security audit** — `core/audit/review.py`
Scheduled review: grants that are broader than their use, capabilities granted
and never exercised, expired-but-present entries, refusal patterns suggesting a
prompt-injection attempt, secrets present without an owner. Findings surface in
the UI.
*Why here:* needs the audit log (A1) and the scheduler (A6), and every later
phase adds attack surface it should already be watching.

**A8 ○ Coding environment on the gate** — `core/tools/builtin/code.py`
Port the legacy coding surface onto the tool layer: run code, run tests, read
diagnostics, VS Code integration, git through `vcs.read`/`vcs.write`. Shell
access is `shell.run` — irreversible, therefore always confirmed.

### Phase B — the second brain

**B1 ○ Document tools** — `core/tools/builtin/documents.py`
Read and write .docx, .pptx, .xlsx; PDF text extraction (legacy `pdftext.py`
ports here). Round-trip fidelity matters — opening and saving must not destroy
formatting the user did not touch.
*Why first in B:* purely library work, no model or index needed, and it is the
"plugins for Word/PowerPoint" ask.

**B2 ○ Obsidian vault adapter** — `core/brain/vault.py`
Read and write the vault as markdown: frontmatter, `[[wikilinks]]`, tags,
attachments, daily notes. Writes are atomic and conflict-aware, because the
user may have Obsidian open even if they never open it on purpose.
*Constraint:* the user never opens Obsidian. Anything requiring a manual step
there is a failed design.

**B3 ○ Local embeddings and index** — `core/brain/index.py`
Local embedding model, vector store, incremental reindexing on file change. No
network.

**B4 ○ Retrieval / private RAG** — `core/brain/retrieve.py`
Hybrid retrieval over vault, documents and conversations, with citations back
to source notes. Retrieval is a *tool*, so it is gated and audited like
anything else.

**B5 ○ Memory distillation** — `core/brain/distil.py`
Scheduled consolidation of conversations into durable notes, deduplicated
against what exists. Supersedes legacy `memory/consolidate.py`; port its
pending/holding staging, which is good design worth keeping.

**B6 ○ Projects reconciled** — `core/projects.py`
Fold legacy `projects.py` and `knowledge_graph.py` onto the new spine: a
project owns notes, memory, skills, a personality override, **and its own
policy**, so granting an agent a folder for one project does not grant it
everywhere.

### Phase C — reach

**C1 ○ The network chokepoint** — `core/net/`
Every outbound request in the entire application goes through one audited
module that checks `net.http` against the host scope, records the request, and
enforces timeouts and size caps. `verify_offline.py` is updated to assert that
this is the *only* path — the core must still prove nothing else opens a
socket.
*Why first in C:* every item below is a client of it. Written second, each one
would need retrofitting.

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

**C6 ○ Monitoring agent** — `core/agents/monitor.py`
Watch a page, folder, inbox or feed for change; run on the scheduler; notify or
trigger a follow-up agent.

**C7 ○ Location and time awareness** — `core/context/place.py`
Local timezone, season and weather already drive the scenes; this generalises
it so agents can reason about "now" and "here". Location is `location.read`,
scoped and revocable.

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
| A | A4 Teams and roles | ▶ next |
| A | A5 UI bridge | ○ |
| A | A6 Scheduler | ○ |
| A | A7 Security audit | ○ |
| A | A8 Coding on the gate | ○ |
| B | B1–B6 Second brain | ○ |
| C | C1–C8 Reach | ○ |
| D | D1–D3 Voice | ○ |
| E | E1–E4 Making | ○ |

**Tests at last commit:** 1115 passed, 2 skipped, 0 failed; `verify_offline.py`
passes. Update this line when it changes.

---

## 7. Working agreement

- **Timeline is months, not a month.** Extending is explicitly fine. Rushing a
  phase to reach the next one is not.
- **Each item ships tested.** A capability without adversarial tests is not
  done, because the interesting cases are all adversarial.
- **Findings go in REBUILD.md** §"Findings worth not rediscovering" the moment
  they cost more than ten minutes.
- **Handoffs stay current.** Refresh the Codex handoff at 90% session usage or
  on request.
- **Open source where it fits** — Hermes for tool calling, Whisper, Piper,
  Playwright, and other open agents rather than bespoke reimplementation.
