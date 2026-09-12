# The interface while you were away

Claude → Codex, 2026-09-11. Follows
[12](2026-09-11-12-claude-to-codex-the-weather.md). You hit your weekly limit,
and the person asked me to take over the interface until you are back. This is
every QML change I made in that time, so you can review it before building on
it. None of it is meant to set a direction you did not choose: where your
design and mine differ, yours should win, and I would rather you rework these
than work around them.

## First: the project is renamed

The package is `akira` and the QML module is `Akira` (`import Akira`, and
`akira/ui/qml/Akira/qmldir` says `module Akira`). The window, sidebar and
taskbar say Akira. Your old paths under `protege/ui/qml/Protege/` are now
`akira/ui/qml/Akira/`; `git mv` was used throughout, so history follows. The
settings folder moves from `%LOCALAPPDATA%\Protege` to `%LOCALAPPDATA%\Akira`
at the first start. Your uncommitted branding files in `docs/branding/`, your
handoff 06 and `docs/handoffs/README.md` were left exactly as they were.

## Why the interface work was urgent

Nothing in the window used the backend bridges except `Chat` and `Settings`.
So every irreversible action (a file write, a run, a commit, a document edit)
waited five minutes for a confirmation dialog that did not exist and was
refused, and nothing could be granted. Every tool and watch built since A1 was
unreachable from the app. The first two views below fix that.

## What I added or changed

**Plain text everywhere** (commit `b124d3e`). Every `Text` or `Label` whose
text is not a literal now sets `textFormat: Text.PlainText`: the person's own
message in `ChatView`, sidebar titles and times in `NavRow`, tab titles, model
names and the models folder in `SettingsSheet`, the code block's language tag,
sheet titles, select options, `SectionLabel`. The reason is rule 5 in
QML_BRIDGES.md (handoff 10). `tests/test_qml_text_formats.py` now enforces it
on every QML file: a data-bound `Text` or `Label` without `textFormat` fails
the suite, and rich text is allowed only in `MessageBody.qml`. The welcome line
now says "Your conversations stay on this machine."

**`ActionButton.qml`** (`0a941d7`). A text button: `primary`, `secondary` or
`danger`, a focus ring, Enter and Space. There was no text button in the module;
both new sheets needed one. If you have a button design in mind, replace it.

**`ConfirmDialog.qml`** (`0a941d7`), in `Main.qml` above every sheet. It queues
`Confirm.requested`, shows one at a time with the summary verbatim, starts with
focus on "Don't allow", treats Escape as no, answers nothing on a click outside,
and has no "don't ask again". Treat those behaviours as requirements; the look
is yours.

**`PermissionsSheet.qml`** (`0a941d7`). Every capability grouped (files and
programs, notes and memory, this computer, the internet, accounts, cloud
models), with badges for high risk, leaves this computer and asks each time.
Unscoped capabilities get a `Toggle`; scoped ones get a folder picker
(`FolderDialog`) or a text field, one removable chip per scope. The bridge's
refusal is shown as it comes. At the top is what may send anything off this
computer; at the bottom, recent activity including refusals, and "Take
everything away", which asks twice. It opens from a shield in the toolbar and
from a new first section in `SettingsSheet`.

**`icons.js`**: `shield`, `eye`, `globe`, `team`.

**`AgentsView.qml`** (`10c7151`) and an **Agents** entry in the sidebar. The
person asked to be able to see the agents and teams. A team is drawn as its
members in working order with the hand-offs between them. The one working now
glows, a finished one is ticked, a failed one is marked, and an arrow lights
when work is handed on. Each member's purpose and tools are listed under the
line. From the same page a task is given to a team or a single agent, with an
optional folder, and it can be stopped. The answer is shown through
`MessageBody`, and every step appears in a record beneath. It redraws from the
new `AgentTrace.recent(limit)`. In `Main.qml` the agents view uses the code
scene, kept quiet, and hides the composer.

**`PlaceSheet.qml`**, "Where you are", landed with this handoff: look a place
up, choose one, see the season and the weather, and allow the two permissions
the weather needs beside what they are for. It opens from a new "Where you are"
section in `SettingsSheet`. It reads the grants fresh whenever it changes one,
never from its cached copy, so allowing the weather's site cannot drop a site
allowed elsewhere since the sheet last looked. `Main.qml` now binds
`SceneHost.weather: Place.weather || "clear"` and
`SceneHost.southernHemisphere: Place.southernHemisphere`, the line handoff 12
asked for.

## Tests that now drive your views

`tests/test_qml_views.py` runs the real window offscreen in its own process. It
checks that an agent's request raises the dialog with its exact summary and
that Allow and Don't allow reach the worker. It checks that the permission
sheet's switch and site entry land in the real policy, refusing a full address
as a site. It opens the Agents view, feeds it a trace and checks the drawing.
It fails on any script error. If you rename an `objectName` it relies on
(`confirmDialog`, `confirmSummary`, `permissionsSheet`, `agentsView`,
`agentPipeline`, `placeSheet`), change the test with it. It also checks that the
place sheet's buttons grant exactly the weather's site and keep every other.

## Still yours, untouched

- The sidebar's **Projects** list is still the sample array in `Main.qml`, not
  `Projects.projects`.
- There are no views yet for **Monitor** (watches and notices), **Memory**
  (proposals to accept) or **Schedule** (jobs and the security review).
- `ResearchView` still says web search is not connected. Search now exists
  (`web_search`, for agents); the research chat itself does not call tools.
- The scenes, the design system and the gallery are as you left them, apart
  from `textFormat` lines in the gallery.

## Backend since handoff 12, briefly

- C4 screenshots, for agents: `look_at_screen` reads the words on screen,
  `save_screenshot` writes a PNG.
- C2 web search on DuckDuckGo: `web_search`, under `web.search`, which reaches
  DuckDuckGo and nothing else.
- `git push`: the person's own git login, never forced, asked each time.

No bridge changed except `AgentTrace.recent`, documented in QML_BRIDGES.md.

The index row for this handoff is **19**, after 16–18 from handoffs 10–12.
