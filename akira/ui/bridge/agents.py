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
import time
from copy import deepcopy
from pathlib import Path
from typing import Callable
import secrets

from PySide6.QtCore import Property, QObject, Signal, Slot, QTimer

from akira.core.agents import Agent, Trace, research_team, software_team
from akira.core.agents.roles import ALL_ROLES
from akira.core.agents.team import Team
from akira.core.models import ModelRouter
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import ToolContext, ToolRegistry
from akira.security.qtguard import inert_markdown
from akira.ui.run_archive import RunArchive, MAX_RUNS, clean_record
from akira.ui.run_sources import ObservedRegistry

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
    runsChanged = Signal()
    previewChanged = Signal()

    #: ok, answer — once per run, however it ended.
    finished = Signal(bool, str)

    #: Private: carries a run's result from the worker thread to this one.
    _done = Signal(object)
    _progress = Signal(object)
    _source = Signal(object)
    _removed = Signal(str, str)

    def __init__(self, router: ModelRouter, registry: ToolRegistry, *,
                 policy: Callable[[], Policy], audit: AuditLog,
                 secret_store: SecretStore, trace: Trace,
                 confirm: Callable[[str], bool] | None = None,
                 project: Callable[[], dict] | None = None,
                 model_for: Callable[[str], dict] | None = None,
                 archive: RunArchive | None = None,
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
        self._project = project or (lambda: {})
        self._model_for = model_for or (lambda route: {"route": route, "label": "Unavailable"})
        self._archive = archive or RunArchive()
        self._records = {r["id"]: r for r in self._archive.records()}
        self._current_id = ""
        self._history_error = self._archive.error
        self._archive_busy = False
        self._source_cache = {}
        self._source_epoch = 0
        self._preview = {}
        self._done.connect(self._on_done)
        self._progress.connect(self._on_progress)
        self._source.connect(self._on_source)
        self._removed.connect(self._on_removed)
        self._expiry = QTimer(self)
        self._expiry.setInterval(1000)
        self._expiry.timeout.connect(self._check_preview)
        self._expiry.start()

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

    @Property("QVariantList", notify=runsChanged)
    def runs(self) -> list:
        keys = ("id", "name", "kind", "task", "projectId", "projectName", "status", "started")
        return [{k: r[k] for k in keys} for r in sorted(
            self._records.values(), key=lambda r: r["started"], reverse=True)]

    @Property("QVariantMap", notify=runsChanged)
    def currentRun(self) -> dict:
        return self.record(self._current_id)

    @Property(str, notify=runsChanged)
    def historyError(self) -> str:
        return self._history_error

    @Property(bool, notify=runsChanged)
    def archiveBusy(self) -> bool:
        return self._archive_busy

    @Property("QVariantMap", notify=previewChanged)
    def sourcePreview(self) -> dict:
        return {k: v for k, v in self._preview.items() if k != "checks"}

    @Slot(str, result="QVariantMap")
    def record(self, ident: str) -> dict:
        row = deepcopy(self._records.get(ident, {}))
        if row:
            row["answer"] = inert_markdown(row["answer"])
        return row

    @Slot(str, str, result=str)
    def previewSource(self, ident: str, source_id: str) -> str:
        self.clearSource()
        source = self._source_cache.get((ident, source_id))
        row = self._records.get(ident)
        if not source:
            return "This preview is no longer in memory. Saved investigations retain source references, not page or file contents."
        if not row or row["projectId"] != str(self._project().get("id", "")):
            return "Open the investigation's original project to view its sources."
        if not self._allowed(source):
            return "Your current permissions no longer allow this source preview."
        self._preview = deepcopy(source)
        self.previewChanged.emit()
        return ""

    def _allowed(self, source) -> bool:
        return all(self._policy().allows(cap, scope) for cap, scope in source["checks"])

    @Slot()
    def clearSource(self) -> None:
        self._preview = {}
        self.previewChanged.emit()

    @Slot()
    def invalidateSources(self) -> None:
        self._source_epoch += 1
        self._source_cache.clear()
        self.clearSource()

    def _check_preview(self) -> None:
        if self._preview and not self._allowed(self._preview):
            self.invalidateSources()

    @Slot(str, result=str)
    def deleteRun(self, ident: str) -> str:
        if ident == self._current_id and self._busy:
            return "Stop this investigation before deleting it."
        if ident not in self._records:
            return "That investigation is no longer saved."
        if self._archive_busy:
            return "A saved investigation is still being removed."
        self._archive_busy = True
        self.runsChanged.emit()
        def remove():
            error = ""
            try:
                self._archive.delete(ident)
            except OSError as exc:
                error = f"The investigation could not be deleted: {exc}"
            self._removed.emit(ident, error)
        threading.Thread(target=remove, name="remove-investigation", daemon=True).start()
        return ""

    def _on_removed(self, ident, error):
        self._archive_busy = False
        self._history_error = error
        if not error:
            self._records.pop(ident, None)
            self._source_cache = {k: v for k, v in self._source_cache.items() if k[0] != ident}
            self.clearSource()
        self.runsChanged.emit()

    # -- starting and stopping ----------------------------------------------------

    @Slot(str, str, str, result=str)
    def runTeam(self, team: str, task: str, folder: str = "") -> str:
        """Start a team. Returns "" once started, or why it was not."""
        build = _TEAMS.get(team)
        if build is None:
            return f"There is no team called {team!r}."
        spec = build()

        def work(context, cancelled, trace, registry):
            return Team(spec, router=self._router, registry=registry,
                        context=context, trace=trace,
                        ).run(task.strip(), is_cancelled=cancelled)

        return self._start(f"The {spec.name} team", spec.name, work, task, folder,
                           "team", [m.name for m in spec.members])

    @Slot(str, str, str, result=str)
    def runAgent(self, role: str, task: str, folder: str = "") -> str:
        """Start one agent. Returns "" once started, or why it was not."""
        spec = ALL_ROLES.get(role)
        if spec is None:
            return f"There is no role called {role!r}."

        def work(context, cancelled, trace, registry):
            return Agent(spec, router=self._router, registry=registry,
                         context=context, trace=trace,
                         ).run(task.strip(), is_cancelled=cancelled)

        return self._start(f"The {spec.name}", spec.name, work, task, folder, "agent", [spec.name])

    @Slot()
    def stop(self) -> None:
        """Ask the running work to stop at its next token."""
        if self._busy:
            self._cancel.set()

    def _start(self, label, actor, work, task, folder, kind, members) -> str:
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
        project = self._project()
        record = clean_record({"id": secrets.token_hex(16), "kind": kind, "name": actor,
            "task": text, "folder": workspace, "projectId": project.get("id", ""),
            "projectName": project.get("name", "") or "Personal workspace",
            "started": time.time(), "status": "running", "members": members,
            "states": {m: "Waiting" for m in members},
            "models": {m: self._model_for(ALL_ROLES[m].route.value) for m in members}})
        self._current_id = record["id"]
        self._records[self._current_id] = deepcopy(record)
        keep = sorted(self._records, key=lambda i: self._records[i]["started"], reverse=True)[:MAX_RUNS]
        self._records = {i: self._records[i] for i in keep}
        # Retain at most four runs of bounded, transient source bodies.
        self._source_cache = {k: v for k, v in self._source_cache.items() if k[0] in keep[:4]}
        self._busy, self._running = True, label
        self.runsChanged.emit()
        self.busyChanged.emit()
        threading.Thread(target=self._work, args=(work, context, record, self._source_epoch),
                         name="agents", daemon=True).start()
        return ""

    def _work(self, work, context: ToolContext, record, epoch) -> None:
        """Worker thread. Emits a signal; touches no Qt property."""
        error = ""
        def save():
            nonlocal error
            try:
                self._archive.save(record)
                error = ""
            except (OSError, ValueError) as exc:
                error = f"This result is available in this session but could not be saved: {exc}"
        save()
        trace = Trace()
        def event(e):
            fields = e.to_json()
            fields.pop("at"); fields.pop("kind"); fields.pop("agent")
            self._trace.emit(e.kind, e.agent, **fields)
            kind = e.kind.value
            if e.agent in record["states"]:
                state = {"started": "Starting", "thinking": "Thinking", "answer": "Done", "failed": "Failed",
                         "tool_call": "Using " + e.tool, "tool_result": "Reading result" if e.ok else "Tool declined"}.get(kind)
                if state: record["states"][e.agent] = state
            if kind in ("message", "tool_call", "tool_result", "failed"):
                record["events"].append({"kind": kind, "agent": e.agent, "tool": e.tool, "to": e.to, "ok": e.ok})
                record["events"] = record["events"][-80:]
            self._progress.emit(deepcopy(record))
        trace.listen(event)
        def source(s):
            existing = next((v for v in record["sources"] if v["id"] == s["id"]), None)
            if existing is None and len(record["sources"]) < 32:
                record["sources"].append({k: s[k] for k in ("id", "title", "locator", "kind", "tool")})
            if existing is not None or any(v["id"] == s["id"] for v in record["sources"]):
                self._source.emit((record["id"], epoch, deepcopy(s)))
                self._progress.emit(deepcopy(record))
        def artifact(item):
            existing = next((v for v in record["artifacts"] if v['id'] == item['id']), None)
            if existing:
                existing.update(item)
            elif len(record["artifacts"]) < 24:
                record["artifacts"].append(item)
            self._progress.emit(deepcopy(record))
        try:
            outcome = work(context, self._cancel.is_set, trace, ObservedRegistry(self._registry, source, artifact))
            result = (bool(outcome.ok), outcome.answer, outcome.stopped)
        except Exception as exc:  # noqa: BLE001 - a crashed run must still report back
            result = (False, f"{type(exc).__name__}: {exc}", "failed")
        ok, answer, stopped = result
        record.update(answer=answer[:60000], ended=time.time(), stopped=stopped,
                      status="complete" if ok else "stopped" if stopped == "cancelled" else "incomplete")
        for member, state in record["states"].items():
            if state not in ("Done", "Failed", "Waiting"):
                record["states"][member] = "Stopped" if stopped == "cancelled" else "Incomplete"
        save()
        self._done.emit((result, record, error))

    def _on_progress(self, record):
        self._records[record["id"]] = record
        self.runsChanged.emit()

    def _on_source(self, result):
        ident, epoch, source = result
        if epoch == self._source_epoch and self._allowed(source):
            self._source_cache[(ident, source["id"])] = source

    def _on_done(self, result) -> None:
        outcome, record, error = result
        ok, answer, stopped = outcome
        # An answer is Markdown, and may be shown as such: a picture in it is
        # served as a link, never loaded, since its address could name a
        # server (see akira/security/qtguard.py).
        answer = inert_markdown(answer)
        self._ok, self._answer, self._stopped = ok, answer, stopped
        self._busy, self._running = False, ""
        self._records[record["id"]] = record
        self._history_error = error
        self.runsChanged.emit()
        self.busyChanged.emit()
        self.resultChanged.emit()
        self.finished.emit(ok, answer)
