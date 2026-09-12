"""Starting agents and teams from the interface.

Before this, a team could only run as a scheduled job created in code, and the
Research workspace had nothing to call. `Agents` is the button behind it.

**One run at a time from here.** The router already queues work at the model,
since only one generation runs at a time across the process, so a second
request would just wait behind the first with no way to see why. Refusing it,
and naming what is already running, is clearer.

**Starting a run grants nothing.** A run uses the permissions the person holds,
read from the live policy the permission screen edits. Naming a folder tells
the agents where to work; it does not let them read it.

**The run is visible and can be stopped.** It shares the trace `AgentTrace`
shows, asks through the real confirmation prompt, and stops at its next token
when asked. As with every bridge, the worker touches no Qt property: the result
crosses back on a queued signal.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from akira.core.agents import Agent, Trace, research_team, software_team
from akira.core.agents.roles import ALL_ROLES
from akira.core.agents.team import Team
from akira.core.models import ModelRouter
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import ToolContext, ToolRegistry
from akira.security.qtguard import inert_markdown

#: A task longer than this belongs in a file the agent is pointed at.
MAX_TASK_CHARS = 4000

_TEAMS = {"research": research_team, "software": software_team}


def _first_sentence(text: str) -> str:
    head = text.strip().split(". ", 1)[0]
    return head if head.endswith(".") else head + "."


class AgentsBridge(QObject):
    """Run one agent or a whole team on a task, and report back."""

    busyChanged = Signal()
    resultChanged = Signal()

    #: ok, answer — once per run, however it ended.
    finished = Signal(bool, str)

    #: Private: carries a run's result from the worker thread to this one.
    _done = Signal(object)

    def __init__(self, router: ModelRouter, registry: ToolRegistry, *,
                 policy: Callable[[], Policy], audit: AuditLog,
                 secret_store: SecretStore, trace: Trace,
                 confirm: Callable[[str], bool] | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._router = router
        self._registry = registry
        self._policy = policy
        self._audit = audit
        self._secret_store = secret_store
        self._trace = trace
        self._confirm = confirm or (lambda summary: False)
        self._cancel = threading.Event()
        self._busy = False
        self._running = ""
        self._answer = ""
        self._ok = True
        self._stopped = ""
        self._done.connect(self._on_done)

    # -- what exists ------------------------------------------------------------

    @Property("QVariantList", constant=True)
    def teams(self) -> list:
        """Each team: `name`, `purpose`, and `members` in the order they work."""
        teams = []
        for build in _TEAMS.values():
            spec = build()
            teams.append({"name": spec.name, "purpose": spec.purpose,
                          "members": [m.name for m in spec.members]})
        return teams

    @Property("QVariantList", constant=True)
    def roles(self) -> list:
        """Each role: `name`, a one-line `summary`, its model `route`, and the
        `tools` it may use at most — the policy can still withhold them."""
        return [{"name": spec.name, "summary": _first_sentence(spec.role),
                 "route": spec.route.value, "tools": list(spec.tools)}
                for spec in ALL_ROLES.values()]

    # -- state ------------------------------------------------------------------

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=busyChanged)
    def running(self) -> str:
        """What is working now, e.g. "The research team". Empty when idle."""
        return self._running

    @Property(str, notify=resultChanged)
    def answer(self) -> str:
        return self._answer

    @Property(bool, notify=resultChanged)
    def ok(self) -> bool:
        return self._ok

    @Property(str, notify=resultChanged)
    def stopped(self) -> str:
        """Why the last run ended: `answered`, `budget`, `cancelled` or `failed`."""
        return self._stopped

    # -- starting and stopping ----------------------------------------------------

    @Slot(str, str, str, result=str)
    def runTeam(self, team: str, task: str, folder: str = "") -> str:
        """Start a team. Returns "" once started, or why it was not."""
        build = _TEAMS.get(team)
        if build is None:
            return f"There is no team called {team!r}."
        spec = build()

        def work(context: ToolContext, cancelled: Callable[[], bool]):
            return Team(spec, router=self._router, registry=self._registry,
                        context=context, trace=self._trace,
                        ).run(task.strip(), is_cancelled=cancelled)

        return self._start(f"The {spec.name} team", spec.name, work, task, folder)

    @Slot(str, str, str, result=str)
    def runAgent(self, role: str, task: str, folder: str = "") -> str:
        """Start one agent. Returns "" once started, or why it was not."""
        spec = ALL_ROLES.get(role)
        if spec is None:
            return f"There is no role called {role!r}."

        def work(context: ToolContext, cancelled: Callable[[], bool]):
            return Agent(spec, router=self._router, registry=self._registry,
                         context=context, trace=self._trace,
                         ).run(task.strip(), is_cancelled=cancelled)

        return self._start(f"The {spec.name}", spec.name, work, task, folder)

    @Slot()
    def stop(self) -> None:
        """Ask the running work to stop at its next token."""
        if self._busy:
            self._cancel.set()

    def _start(self, label: str, actor: str, work, task: str, folder: str) -> str:
        text = task.strip()
        if not text:
            return "Give it something to do first."
        if len(text) > MAX_TASK_CHARS:
            return (f"That task is over {MAX_TASK_CHARS} characters. Put the detail "
                    "in a file and point to it instead.")
        if self._busy:
            return f"{self._running} is still working. Stop it, or wait for it to finish."

        workspace = ""
        if folder.strip():
            try:
                path = Path(folder.strip()).expanduser().resolve()
            except (OSError, RuntimeError):
                return f"{folder} is not a folder."
            if not path.is_dir():
                return f"{folder} is not a folder."
            # Where to work, not what may be read: the policy still decides.
            workspace = str(path)

        context = ToolContext(policy=self._policy(), audit=self._audit,
                              secrets=self._secret_store, actor=actor,
                              confirm=self._confirm, workspace=workspace)
        self._cancel.clear()
        self._busy, self._running = True, label
        self.busyChanged.emit()
        threading.Thread(target=self._work, args=(work, context),
                         name="agents", daemon=True).start()
        return ""

    def _work(self, work, context: ToolContext) -> None:
        """Worker thread. Emits a signal; touches no Qt property."""
        try:
            outcome = work(context, self._cancel.is_set)
            self._done.emit((bool(outcome.ok), outcome.answer, outcome.stopped))
        except Exception as exc:  # noqa: BLE001 - a crashed run must still report back
            self._done.emit((False, f"{type(exc).__name__}: {exc}", "failed"))

    def _on_done(self, result) -> None:
        ok, answer, stopped = result
        # An answer is Markdown, and may be shown as such: a picture in it is
        # served as a link, never loaded, since its address could name a
        # server (see akira/security/qtguard.py).
        answer = inert_markdown(answer)
        self._ok, self._answer, self._stopped = ok, answer, stopped
        self._busy, self._running = False, ""
        self.busyChanged.emit()
        self.resultChanged.emit()
        self.finished.emit(ok, answer)
