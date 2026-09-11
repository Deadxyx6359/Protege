# Protégé — Rebuild

**[PROJECT.md](PROJECT.md) is the canonical description and work order.**
This file covers the interface and model layer, and the findings that cost
real time to learn.

The knowledge-lock study aid becomes a general assistant: everyday chat, coding,
document work, projects, and a memory that keeps itself current — behind a UI
built to be lived in.

This document is the plan of record for the rebuild. It is written to be picked
up cold, weeks later, by someone who has forgotten the reasoning.

---

## The three decisions everything else follows from

**1. The knowledge lock is retired.** Layers 1–5, the unlock/review flow, the
knowledge web, tripwires and the auditor all come out. The lock made every turn
cost an extra model pass and could refuse to answer; neither is survivable in a
tool you use all day. It survives only in git history on `main`.

*What that costs, stated plainly:* roughly 40% of the existing test suite goes
with it, and the project loses its most distinctive idea. That was a deliberate
call, not an oversight.

**2. Local-first inference, with an opt-in cloud escape hatch.** Fast local
models carry everyday work. Frontier APIs are available per project, off by
default, never silently. See *Inference* below for why the current setup is
unusable and what replaces it.

**3. Qt Quick / QML via PySide6 is the UI.** Tkinter has no GPU compositing, no
real animation and no blur; it cannot reach the bar. Qt Quick runs in-process,
so the egress guard still covers the whole application, and it renders on the
Iris Xe — leaving the RTX 3060 entirely to inference.

Verified on this machine before committing to it: Qt 6.11.2, hardware
Direct3D11, real gaussian blur, antialiased vector shapes, correct 1.25 DPI
scaling, crisp text.

---

## This machine is the design constraint

| | |
|---|---|
| CPU | i7-12700H — 14 cores / 20 threads |
| RAM | **15.7 GB — the binding constraint** |
| dGPU | RTX 3060 Laptop, **6144 MiB**, idle at 0 MiB (not driving the display) |
| iGPU | Intel Iris Xe — drives the display, and will drive the UI |
| Python | 3.12.10 |
| Installed | VS Code (+ `code` on PATH), git 2.50.1, Microsoft Office |

Two consequences worth internalising:

- **The UI and inference do not compete.** The UI renders on the Iris Xe; the
  3060 is reserved for model weights. A GPU-accelerated interface costs nothing
  that inference wanted.
- **RAM, not VRAM, sets the model ceiling.** 15.7 GB total means a ~13 GB model
  leaves Windows nothing and page-thrashes.

---

## Inference

### What is wrong today

`Mistral-Small-24B-Q4_K_M.gguf` (13.3 GB) runs at **~2.2 tok/s**. A 700-token
answer is roughly five minutes. That is not slow, it is unusable — and it is
the single biggest reason the app does not feel good to work in.

### What replaces it

Two small specialists behind a task router, instead of one large generalist.
Both fit **entirely** in the 6 GB card, which is the whole game: a model that
spills into host memory runs at a fraction of the speed, and on this machine
that is the difference between 34 tok/s and 2.

| Route | Model | Size | Context | Why |
|---|---|---|---|---|
| `chat` | Qwen3-8B Q4_K_M | 4.68 GB | 8192 | Largest general model that still fits whole |
| `code` | Qwen2.5-Coder-7B-Instruct Q4_K_M | 4.36 GB | 16384 | Code-tuned, and cheap enough per token to hold 16K |
| `fast` | — | | | Nothing consumes it yet |
| `deep` | — | | | Falls back to `chat` |

Fetch them with `tools/fetch_model.py`, which downloads to a `.part` name and
renames on completion — otherwise the application discovers a half-written file,
assigns it to a route, and fails to load it later in a way that looks unrelated.

### Measured on this machine

Full offload (`n_gpu_layers=-1`), card otherwise idle at 0 MiB:

| Model | Context | VRAM | tok/s |
|---|---|---|---|
| Qwen3-8B | 4096 | 5435 MiB | 30.5 |
| **Qwen3-8B** | **8192** | **5800 MiB** | **32.0** |
| Qwen2.5-Coder-7B | 8192 | 5211 MiB | 34.5 |
| **Qwen2.5-Coder-7B** | **16384** | **5700 MiB** | **36.9** |

12288 for the chat model would land around 6165 MiB against a 6144 MiB card, so
8192 is its ceiling. The coder is 2.6× cheaper per token of context — fewer
layers and fewer KV heads — which is why it gets twice the window on less VRAM.

End to end, through the real router and responder:

| | |
|---|---|
| cold first message (loads the model) | 6.3 s to first token |
| warm | **0.14 s to first token, 34–38 tok/s** |

That cold start is why `preload` defaults on: the default model loads on a
background thread once the window is up, so the first message is already warm.

Against the 24B it replaces — 2.2 tok/s, tens of seconds before anything
appears — this is roughly **15× faster**, and the difference between an
application you wait for and one you work in.

The 24B stays on disk and stays selectable in Settings. Nothing was deleted.

### The honest ceiling

No local model on 15.7 GB is frontier-class, and the app should never imply
otherwise. What closes most of the perceived gap is not raw model quality:

- **speed** — a fast answer that needs one follow-up beats a slow perfect one
- **tools** — reading the actual file beats recalling it
- **memory** — knowing your project beats inferring it
- **the cloud route** — for the genuinely hard 5%

A 7–8B will write a plausible function that is subtly wrong, and will do it
confidently. That is the ceiling, and no amount of routing changes it. What
routing does change is that you find out in seconds instead of minutes.

---

## Architecture

```
protege/
  design/       design tokens; the ThemeController QML sees
  core/
    workspace/    projects, notes, files
    memory/       journal → facts → recall, updated continuously
    models/       backend protocol, llama.cpp, cloud, router
    agents/       tool-calling loop, tool surface, per-project policy
    skills/       authored tools, including agent-authored ones
    documents/    docx · xlsx · pptx · pdf, read and write
    coding/       repo index, VS Code bridge, run & test
    security/     paths, PIN, egress policy, secrets, audit
    plugins/      git, Office, and third-party extensions
  ui/
    app.py        QGuiApplication + QML engine bootstrap
    bridge/       QObject models exposed to QML
    qml/Protege/  components and views
```

Kept from the old codebase, largely intact: `store.py` (atomic I/O),
`security/paths.py` (path validation), `security/pin.py`, `pdftext.py`
(dependency-free PDF extraction), `models/llama_backend.py`,
`models/think_filter.py`, `skills/` (authoring + subprocess runner).

---

## Where it stands

Branch `rebuild`. `main` is untouched and the Tkinter application still runs
from `run.py`; the new one runs from `shell.py`. Two entry points is the
deliberate state of the rebuild — taking away the working application on day
one would leave nothing to use in the meantime.

**Done — phase 1, the design system.**

- `protege/design/` — the appearance decision (which palette, whether motion is
  damped). Deliberately thin: Python owns only what is a platform question.
- `protege/ui/qml/Protege/Theme.qml` — every visual constant. Palettes,
  optically-sized type, the 4pt space scale, radii, Apple's asymmetric easing
  curves, elevation.
- `Squircle.qml` + `squircle.js` — continuous-curvature corners, the real
  construction rather than a rounded rect.
- `Icon.qml` + `icons.js` — 28 stroke-and-fill vector icons on a 24px grid.
- `tools/preview.py` — renders any QML root to PNG in both appearances, with
  motion collapsed so output is deterministic.

**Done — phase 2, the shell.** Sidebar, tab strip, chat view, composer, and a
window that assembles them.

**Done — the chat actually works.** Not a mockup any more:

- `protege/core/` — config, task router, conversations, persistence. No Qt
  anywhere in it, so all of it is testable without a running application.
- `protege/ui/bridge/` — the QObject adapters. A turn runs on a worker thread
  and reports back through queued signals; nothing touches a QML property from
  the worker.
- Streaming into the view, Stop that keeps the partial answer, errors shown as
  errors rather than dressed as replies.
- Markdown and fenced code blocks, each with a language label and a copy
  button, split so code never inherits a proportional font or a wrap.
- Conversations saved atomically to `%LOCALAPPDATA%/Protege/conversations/`,
  listed in the sidebar, reopenable.
- Models discovered from `models/` on launch. Drop a GGUF in and it is used.

**Tests.** Up from 908. The new ones cover streaming, the reasoning-block
filter, cancellation, context truncation, route planning and fallback, atomic
writes, id validation against path traversal, and corrupt-file recovery. All run
against a fake backend — exercising a real GGUF would measure llama.cpp rather
than this code, and take minutes.

**Done — phase 3, the model layer.** Two models acquired, measured and
configured; a settings sheet to change them without editing JSON; preloading so
the first message is warm. See *Inference* above for the numbers.

**Next.** Phase 4 — agents and tools. That is where a 7B stops being a chatbot
that guesses and starts being one that reads the file.

### Findings worth not rediscovering

**Do not register a PySide6 `QObject` subclass as a QML singleton type.**
PySide6 registers Python subclasses against the plain `QObject` metatype, and
that registration shadows QML's built-in `QtObject` — after which every grouped
property in the design system fails with *"Cannot assign object of type
QtObject to property of type QObject\*"*. The theme reaches QML as a context
property instead, bridged into the singleton by `ThemeLink.qml`, because
context properties are invisible inside QML singletons.

**Do not put `Behavior` on a singleton's properties.** A singleton is in no
window's item tree, so nothing drives its animations; they stall and hold the
old value forever, which presents as a theme switch that half-applies. Colour
animation belongs to the components, which are in the scene.

**Import `llama_cpp` lazily.** `protege.models.llama_backend` imports it at
module scope, which maps llama.dll and the CUDA 12 runtime into the process —
hundreds of megabytes before a single model is loaded. Importing it from the
core layer made the whole test suite heavy enough that Tk could no longer
initialise, which surfaced as seven unrelated UI tests failing with "tk wasn't
installed properly". `ModelRouter` now imports it at first load.

**Run pytest with `--capture=sys`.** It is now in `pyproject.toml`. The default
fd-level capture redirects real file descriptors, which breaks Tcl/Tk
initialisation partway through a run — a later `tk.Tk()` fails with "tk wasn't
installed properly" about files that plainly exist. Harmless while the suite was
pure Tkinter; unavoidable once Qt tests shared the process. Without it the suite
loses ~19 tests to spurious errors and takes minutes instead of 27 seconds.

**Claim Tkinter's `_default_root` before the tests do.** Tkinter parents any
widget built without an explicit master to the first `tk.Tk()` created in the
process. `ProtegeWindow` is its own `tk.Tk`, so whichever test touched Tk first
silently decided who the default root was — and when that test destroyed its
window, `_default_root` was left pointing at a torn-down interpreter. Later
tests then failed with *"application has been destroyed"*, but only under some
orderings, so the suite was green on a fixed seed and red roughly one run in
three under `pytest-randomly`. A session-scoped autouse fixture in
`tests/conftest.py` now builds the shared root up front and never destroys it.
The matching real defect: `_drain_events` rescheduled itself unconditionally,
so the 50 ms poll timer outlived `destroy()` — in the application that leaks a
timer, in the suite it fires into whichever test is pumping the event loop next.
`destroy()` now cancels it.

**Read-only git is not read-only.** A repository's own configuration can make
`git status` run a program — `core.fsmonitor` names a command git executes on
every status — and hooks, credential helpers and signing programs are more
commands a repository can name. A partial clone even fetches over the network
on demand. `coding.py` overrides all of these on every call. The tests carry
*controls*: each first shows plain git running the planted command, and skips
if it does not, so a pass means the defence did something rather than that the
attack was inert. What cannot be switched off generically is a clean/smudge
filter in a repository's own `.git/config`.

**Never pass model-supplied text through a batch file.** VS Code's `code`
command is `code.cmd`, and cmd.exe re-parses a batch file's arguments, so a
filename containing `&` can become a second command. `open_in_editor` starts
`Code.exe` with its `cli.js` directly — exactly what the batch file does — and
refuses rather than falling back to it. The CLI script sits under a
commit-hash folder in current installs, not under `resources/` directly.

**A bridge that is not registered with the engine does not exist.** A5 shipped
three bridges, fully tested, that QML could not reach, because `shell.py` only
exposed `Chat` and `Settings`. A test now asserts every context name the
application exposes.

**Hold the model for the whole generation, not just the load.** The router
held its lock only while loading, then handed the model out unguarded. That
was fine while the chat turn was the only thing generating. Once the
scheduler could run an agent while a turn streamed, two threads could
generate on one llama.cpp model at once, and a thread loading a second large
model would evict the first mid-generation: freed memory being read, a
native crash rather than an exception. A settings change from the UI thread
could do the same. `acquire` now holds a process-wide inference lock for the
whole block. `update` only marks changed models stale, so the UI thread never
waits out a generation. `unload_all` waits, and declines rather than crash.
The tests drive the real `acquire` through a fake llama module; the older
chat tests replace `acquire` outright, which is why none of them caught it.

**An unanchored ignore rule can swallow source.** `.gitignore` said `models/`,
meaning the folder of GGUF weights, but a pattern without a leading slash
matches that name anywhere, and it silently excluded the `protege/models`
package: the model manager, the llama backend and the rest were never
committed. The application ran because the files were on disk. It surfaced
only when the suite ran in a clean worktree of HEAD and failed at collection.
Anchor ignore rules, and occasionally run the suite from a clean checkout.

**The offline proof stops at the standard library; the runtime guard covers
the rest.** `verify_offline.py` deliberately does not descend into the stdlib,
which imports `socket` and `urllib` for its own reasons in many innocuous
places. Even `pathlib` imports `urllib.parse`. So an innocent-looking import
can bring a networking module along, and `xml.sax.saxutils` pulls in
`urllib.request`. The static check will not see it, by design, which makes
`netguard` in the launcher load-bearing. The Qt launcher, `shell.py`, never
installed it, and was not an entry point the proof walked either. Both are
fixed and tested. The document code escapes with `html`, not `saxutils`.

**Never round-trip an Office part through ElementTree.** It renames namespace
prefixes and drops declarations no element uses, including those named only
in `mc:Ignorable`, and Word then calls the file unreadable. Parse to read;
to write, splice into the original string. `core/documents/ooxml.py` does
that, and its tests compare bytes.

**Never let a test write a realistically-sized model file.** The route planner
decides on file size, so the obvious test writes a 4.7 GB placeholder. On NTFS
`truncate` allocates rather than sparsifying, and pytest keeps the last few temp
directories — which put **109 GB** of fake models on disk and took the suite from
27 seconds to over five minutes. The thresholds are monkeypatched down to bytes
instead; every rule in the planner is relative, so the decisions are unchanged.

**Never use `uuid` for ids.** `verify_offline.py` classifies it as a networking
module — correctly, since `uuid.getnode()` and `uuid1()` read network
interfaces, and a static scan cannot tell which function will be called.
`secrets.token_hex` does the same job with no such path.

## Phases

Each phase ends with something runnable. No phase leaves the app in a state
where it cannot start.

**1 · Foundation and design system** ✓ — tokens, `ThemeController`, squircles,
motion curves, the component kit. Nothing product-specific.

**2 · The shell** ✓ — window, sidebar, tabs, chat view, composer.
Streaming arrives with the model layer.

**3 · Model layer** ✓ — router, model acquisition, resident-model management,
per-route settings. Cloud backends behind explicit consent are still to do.

**4 · Agents and tools** — the tool-calling loop, the tool surface, per-project
policy, approval UI, and agent-authored skills.

**5 · Documents** — read and write `.docx`, `.xlsx`, `.pptx`, `.pdf`.

**6 · Code mode** — a coding environment in the Claude Code mould: repo index,
run and test, diffs, and a VS Code bridge that reads, writes and runs.

**7 · Memory** — the rolling journal, distilled facts, recall into context, and
scheduled consolidation.

**8 · Projects, plugins, hardening, polish** — project management, the git and
Office plugins, egress policy, secret storage, audit, and the pass over motion
and detail that makes it feel finished.

---

## Non-negotiables carried over from the original

1. **Fail closed.** Errors never produce a permissive outcome.
2. **Nothing executes without approval.** Skills, plugins and agent tool calls
   are approved explicitly, and approval is bound to a SHA-256 digest.
3. **Every path is validated** against permitted roots before any operation —
   traversal, escaping symlinks, alternate data streams, reserved device names.
4. **Every dependency is justified** in a comment in `requirements.txt`.
5. **No telemetry, ever.** Not in any mode, cloud route included.

### What changed, and why

`netguard` blocked *all* egress unconditionally. With an opt-in cloud route,
git push, and extension installs, that becomes an **egress policy**: deny by
default, allow only specific hosts the user has enabled, log every call.
Strictly weaker than the old guarantee — recorded here so the change is not
mistaken for an accident.

The strongest control remains what it always was: an OS firewall rule. The
README's instructions for one still stand.
