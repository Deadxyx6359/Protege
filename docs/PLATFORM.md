# Protégé — the platform

The assistant becomes a place where agents work: teams that research, build,
watch and automate, with real reach into the machine and the network, and a
second brain that keeps itself current.

**[PROJECT.md](PROJECT.md) is the canonical description and work order** —
start there. This file carries the argument behind it: scope honesty, the
security inversion, and where the lines are drawn. [REBUILD.md](REBUILD.md)
covers the interface and the model layer it sits on.

---

## Scope, honestly

The full list — second brain, research and software teams, workflow automation,
private RAG, monitoring, content pipeline, local training, web search, email,
screenshots, voice calls, image/2D/3D generation, scheduling, banking, Canvas,
computer use, job applications, purchasing — is **twelve to eighteen months of
work for a small team**. It is not a month.

What a month buys is the *platform* — the agent loop, the tool protocol, the
permission model, the scheduler, the activity view — plus three or four
capabilities built properly on top of it. The rest become tools that plug into
a system already shaped to hold them, which is the difference between a month
well spent and a pile of half-features.

Ordering is therefore: **the spine first, then organs**. A tool written before
the permission model exists has to be rewritten once it does.

### What this machine can and cannot do

| Want | Verdict |
|---|---|
| Agent teams, tool calling, orchestration | Fine. Hermes-3-8B is built for tool calling and fits the card. |
| Obsidian second brain, private RAG | Fine. Local embeddings, no network. |
| Web search, scraping, computer use | Fine. Playwright drives a real browser. |
| Screenshots, monitoring, scheduling | Fine. |
| Speech in and out, live calls | Fine. Whisper for hearing, Piper or Kokoro for speaking — both local, both real-time on this CPU. |
| Image generation | Workable. SDXL-Turbo or SD 1.5 fits 6 GB. Slow but usable. |
| **3D model generation** | **Not locally.** Nothing that produces usable 3D fits 6 GB. Cloud API, or not at all. |
| **Local model training** | **LoRA only.** QLoRA on a 7–8B in 4-bit fits, at hours per run. Full fine-tuning does not fit, and no amount of patience changes that. |
| 2D/vector generation | Fine — that is a code-generation problem (SVG), not a diffusion one. |

---

## The security model has inverted, and this needs saying plainly

The original Protégé opened no socket, ever. `verify_offline.py` proved it, and
the README called it a hard constraint.

**Web search, email, banking and computer use end that.** There is no version of
those features that does not talk to the network. The founding guarantee is
gone, and pretending otherwise would be worse than losing it.

What replaces it is not a weaker version of the same promise. It is a different
promise:

1. **Deny by default.** No capability is on until it is granted. There is no
   "allow all".
2. **Permission is per capability, per scope, per direction.** Read, write, or
   both — chosen separately for every connector. Read-only email is a real,
   enforced state, not a setting the model can talk its way past.
3. **Enforcement is structural, not prompted.** A tool the agent lacks
   permission for is absent from its tool list. It cannot ask for something it
   cannot see, and a jailbreak cannot conjure a capability that was never
   registered.
4. **Every call is logged** — which agent, which tool, which arguments, what
   came back, how long it took. Locally, and the log is inspectable in the app.
5. **Irreversible actions always confirm.** Sending, posting, buying,
   submitting, deleting. Every time, with the actual content shown. This is not
   configurable, and it does not learn to stop asking.
6. **Credentials never reach a model.** They live in the OS credential store,
   are injected at the transport layer, and are never placed in a prompt, a
   log, or a tool argument.
7. **A scheduled security audit** runs over granted permissions, stored
   credentials, tool definitions and their digests, and reports drift.

### Where I am drawing a line

Some of the list is genuinely dangerous, and being asked for it is not the same
as it being wise. These are built with a hard confirmation step and no autonomous
mode:

- **Money.** Purchases, transfers, anything that moves funds. The agent may fill
  a basket and reach a checkout page; a person presses the button, every time.
- **Banking.** Read-only. Balance and transaction *reading* is a reasonable
  thing to automate. Payment initiation is not, and will not be built.
- **Job applications.** Drafted and staged, never submitted unattended. A bot
  applying to jobs while you sleep is how people get blacklisted by
  applicant-tracking systems, and the résumé it sends is one you have not read.
- **Anything posted publicly** under your name.

Everything else — reading, watching, gathering, drafting, building, scheduling —
runs unattended once permitted.

---

## Architecture

```
protege/
  core/
    agents/
      loop.py         one agent: perceive, decide, call a tool, repeat
      team.py         several agents with a shared goal and a coordinator
      roles.py        researcher, builder, reviewer, watcher
      trace.py        the event stream the activity view renders
    tools/
      registry.py     declaration, discovery, digest-pinned approval
      schema.py       a tool's contract: arguments, permissions, reversibility
      builtin/        files, shell, http, browser, screenshot, vault, docs
    permissions/
      model.py        capability grants: scope, direction, expiry
      audit.py        the log, and the scheduled review of it
      secrets.py      OS credential store; never touches a prompt
    knowledge/
      vault.py        Obsidian, read and written without opening Obsidian
      index.py        embeddings + BM25 over vault, documents, transcripts
      recall.py       what gets pulled into context, and why
      distil.py       turning conversations into durable notes
    schedule/
      cron.py         time-based: daily, weekly, monthly, custom
      watch.py        event-based: a file changed, a page changed, mail arrived
    voice/
      listen.py       Whisper
      speak.py        Piper/Kokoro, six voices
      call.py         full-duplex session, survives the window closing
    connectors/       email, calendar, Canvas, banking (read), messaging
  ui/
    qml/Protege/
      scenes/         the animated backdrops
      agents/         team view, live activity graph
      voice/          the call widget
```

---

## Agent teams

Two to start, because two is enough to prove the shape and four is enough to
prove nothing:

**Research team** — a lead that decomposes the question, two or three gatherers
that search and read in parallel, a synthesiser that writes the answer and
keeps its citations.

**Software team** — an architect that plans, a builder that writes, a reviewer
that reads the diff before it lands. The reviewer is not optional and does not
share the builder's context, because a reviewer that already believes the code
is right is not a reviewer.

Both run on the same loop. A "team" is a coordinator, a shared scratchpad, and a
rule for when to stop.

### Seeing it happen

Agents are rendered as a live graph: nodes for agents, edges that light as
messages pass, a badge on each node for which model it is running and what tool
it is in the middle of calling. Idle agents fade back. A run can be scrubbed
after the fact from the same trace.

This is a debugging tool that happens to be pleasant to watch, not a decoration.
When a team gets stuck it is almost always visible — two agents handing the same
subtask back and forth, or one waiting on a tool that never returns.

---

## Interface

Everyday and code work get different worlds, both 8-bit, both alive.

**Everyday — botanica.** A landscape that knows the time, the season and the
weather. Dawn through night in the sky, four seasons in the planting, and
whatever it is actually doing outside. Time and season come from the clock and
need no network; weather is a capability like any other and the scene is
complete without it.

**Code — space.** Near-monochrome, a slow star field, almost nothing moving.
The everyday scene is meant to be looked at; this one is meant to be worked in
front of.

**Research — sea. Automation — city.** Same construction, when those views exist.

The Apple-grade chrome does not change. The scene is the backdrop; panels,
type and controls stay exactly as they are, and the scene dims and blurs behind
active content so nothing competes with text.

---

## Phases

**A · The spine.** Permission model, tool protocol, agent loop, teams, trace,
activity view. Nothing user-visible works better at the end of this, and
everything after it is possible.

**B · The second brain.** Obsidian vault read and written automatically, local
index, RAG, memory distillation. You never open Obsidian.

**C · Reach.** Browser and computer use, web search, screenshots, scheduler,
monitoring, connectors with per-connector permissions.

**D · Voice.** Whisper in, Piper out, six voices, a call that survives the
window closing and lives in its own widget.

**E · Making.** Image generation, content pipeline, LoRA training.

**Throughout · The scenes**, because they are self-contained and they are what
makes the thing pleasant to open.
