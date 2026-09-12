"""Jobs that run on a clock, or in answer to something happening.

**Durable.** Jobs live in `schedule.json` in the config directory and survive
restarts. A job's *action* is stored by name, never as code: a pickled callable
would be a way to smuggle arbitrary execution into a settings file, and it
would break the first time the function it pointed at was renamed. Actions are
registered at startup. A job naming one that is not registered fails visibly
and is kept, because whatever provides it may simply not be loaded yet.

**Each run gets its own narrowed policy.** A job declares the grants it needs,
and every run intersects them with the user's *live* policy at that moment. A
job can never hold more than the person does, revoking something in Settings
takes effect on the very next run, and scheduling a job grants nothing. The
narrowed policy refuses to be saved: writing it would silently replace the
user's permissions with one job's subset.

**Missed runs are resolved, never ignored.** If the machine was asleep or
Akira was closed when a job was due, the next tick finds it overdue and does
what the job says — run once now, or skip to the next occurrence — and the
history says which. Several missed occurrences coalesce into one late run; an
hourly job does not fire twenty times after a night off.

**Contained.** A job that raises is recorded as failed and the scheduler moves
on. Several consecutive failures pause the job with the reason attached,
rather than letting it fail every minute for a week. A job whose previous run
is still going is not started again on top of itself.

**Unattended means no.** A scheduled run has no person watching by default, so
its `confirm` refuses — nothing irreversible happens because a clock said so.
When the interface is open it can hand in a real prompt, and then a person is
asked; if nobody answers, the prompt times out to no.

The scheduler is driven by `tick(now)`, so tests move time by hand.
`SchedulerService` is only the thread that calls it.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from akira.core.agents import Kind, Trace
from akira.core.config import config_dir
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.permissions.audit import Event as AuditEvent
from akira.core.permissions.audit import redact
from akira.core.permissions.capabilities import ScopeKind, get
from akira.core.tools import ToolContext

from .triggers import Every, Once, Trigger, trigger_from_json

#: An overdue job within this many seconds of its time is simply on time — the
#: service ticks every half minute, so a few seconds late is not "missed".
GRACE_S = 180

#: Consecutive failures before a job is paused.
MAX_CONSECUTIVE_FAILURES = 5

#: Run records kept per job.
MAX_HISTORY = 20

#: Events waiting for the next tick. Beyond this the oldest are dropped and
#: counted, so a runaway publisher cannot grow memory without bound.
MAX_QUEUED_EVENTS = 1000

#: Missed occurrences counted before giving up and saying "at least".
MAX_COUNTED_MISSES = 1000

MAX_SUMMARY_CHARS = 1000

_ACTION_NAME = re.compile(r"\A[a-z][a-z0-9_.-]{0,63}\Z")


class Missed(str, Enum):
    """What to do about a run that came due while nothing was running."""

    RUN_LATE = "run_late"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class JobGrant:
    """A capability a job needs, narrowed to specific scopes."""

    capability: str
    scopes: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {"capability": self.capability, "scopes": list(self.scopes)}

    @classmethod
    def coerce(cls, raw: Any) -> "JobGrant":
        if isinstance(raw, JobGrant):
            grant = raw
        elif isinstance(raw, dict):
            grant = cls(str(raw["capability"]),
                        tuple(str(s) for s in raw.get("scopes") or ()))
        else:
            capability, scopes = raw
            grant = cls(str(capability), tuple(str(s) for s in scopes))
        capability = get(grant.capability)          # KeyError if invented
        if capability.scope is not ScopeKind.NONE and not grant.scopes:
            raise ValueError(
                f"{capability.title} must be limited to at least one "
                f"{capability.scope.value} for a scheduled job")
        return grant


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One thing that happened to one job."""

    job_id: str
    started: float
    finished: float
    status: str
    """`ok`, `failed`, `skipped`, `overlap`, or `cancelled`."""
    summary: str = ""
    late: bool = False
    trigger: str = "time"
    """`time`, `event`, or `manual`."""

    def to_json(self) -> dict:
        return {"job_id": self.job_id, "started": self.started,
                "finished": self.finished, "status": self.status,
                "summary": self.summary, "late": self.late,
                "trigger": self.trigger}

    @classmethod
    def from_json(cls, raw: dict) -> "RunRecord":
        return cls(str(raw["job_id"]), float(raw["started"]),
                   float(raw["finished"]), str(raw["status"]),
                   str(raw.get("summary", "")), bool(raw.get("late", False)),
                   str(raw.get("trigger", "time")))


@dataclass(slots=True)
class Job:
    """A named action, a trigger, and what it may touch."""

    id: str
    name: str
    action: str
    trigger: Trigger
    arguments: dict = field(default_factory=dict)
    grants: tuple[JobGrant, ...] = ()
    missed: Missed = Missed.RUN_LATE
    enabled: bool = True
    created: float = 0.0
    next_run: float | None = None
    last_run: float | None = None
    failures: int = 0
    paused_reason: str = ""
    done: bool = False
    """A one-off job that has run, or a trigger with no further dates."""
    suppressed: int = 0
    """Events swallowed by the cooldown since the last run."""
    history: list[RunRecord] = field(default_factory=list)

    @property
    def last_status(self) -> str:
        return self.history[-1].status if self.history else ""

    def to_json(self) -> dict:
        return {
            "id": self.id, "name": self.name, "action": self.action,
            "trigger": self.trigger.to_json(), "arguments": self.arguments,
            "grants": [g.to_json() for g in self.grants],
            "missed": self.missed.value, "enabled": self.enabled,
            "created": self.created, "next_run": self.next_run,
            "last_run": self.last_run, "failures": self.failures,
            "paused_reason": self.paused_reason, "done": self.done,
            "history": [r.to_json() for r in self.history],
        }

    @classmethod
    def from_json(cls, raw: dict) -> "Job":
        if not isinstance(raw, dict):
            raise TypeError("a job must be an object")
        arguments = raw.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise TypeError("a job's arguments must be an object")
        next_run = raw.get("next_run")
        last_run = raw.get("last_run")
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            action=str(raw["action"]),
            trigger=trigger_from_json(raw["trigger"]),
            arguments=dict(arguments),
            grants=tuple(JobGrant.coerce(g) for g in raw.get("grants") or ()),
            missed=Missed(raw.get("missed", Missed.RUN_LATE.value)),
            enabled=bool(raw.get("enabled", True)),
            created=float(raw.get("created", 0.0)),
            next_run=None if next_run is None else float(next_run),
            last_run=None if last_run is None else float(last_run),
            failures=int(raw.get("failures", 0)),
            paused_reason=str(raw.get("paused_reason", "")),
            done=bool(raw.get("done", False)),
            history=[RunRecord.from_json(r) for r in raw.get("history") or ()],
        )


# -- actions -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionResult:
    ok: bool
    summary: str = ""
    cancelled: bool = False
    """Stopped because Akira was closing. Recorded as such and not counted
    as a failure: a job must not be paused for having been interrupted."""


@dataclass(slots=True)
class JobContext:
    """What an action is handed for one run."""

    job: Job
    arguments: dict
    tools: ToolContext
    """Carries the run's narrowed policy. Anything an action does through a
    tool is gated against this, not against the user's full policy."""
    trace: Trace
    event: dict | None = None
    event_name: str = ""
    cancelled: Callable[[], bool] = lambda: False
    """True once Akira is closing. Long actions pass it on as
    `is_cancelled`, so an agent stops at its next token rather than holding
    shutdown up."""


Action = Callable[[JobContext], ActionResult]


class ActionRegistry:
    """The things a job may name."""

    def __init__(self) -> None:
        self._actions: dict[str, tuple[Action, str]] = {}

    def register(self, name: str, handler: Action, description: str = "") -> None:
        if not _ACTION_NAME.match(name):
            raise ValueError(f"{name!r} is not a valid action name")
        if name in self._actions:
            raise ValueError(f"an action named {name!r} is already registered")
        self._actions[name] = (handler, description)

    def get(self, name: str) -> Action | None:
        entry = self._actions.get(name)
        return entry[0] if entry else None

    def describe(self, name: str) -> str:
        entry = self._actions.get(name)
        return entry[1] if entry else ""

    def names(self) -> list[str]:
        return sorted(self._actions)


# -- the narrowed policy -----------------------------------------------------


class JobPolicy(Policy):
    """One run's permissions: a subset of the user's, held only in memory."""

    def save(self) -> None:  # noqa: D401 - deliberately refuses
        raise RuntimeError(
            "a scheduled job's narrowed policy must never be saved — it would "
            "overwrite the user's permissions with one job's subset")


def narrow_policy(live: Policy, grants: tuple[JobGrant, ...]) -> JobPolicy:
    """The intersection of what a job asked for and what the user holds *now*.

    A scope the job lists but the user's grant does not cover is dropped, and
    a capability left with no scopes is dropped entirely. Expiry is carried
    across from the user's grant, so a permission that lapses mid-schedule
    lapses for the job too.
    """
    policy = JobPolicy()
    for wanted in grants:
        try:
            capability = get(wanted.capability)
        except KeyError:
            continue
        held = live.granted(wanted.capability)
        if held is None:
            continue
        if capability.scope is ScopeKind.NONE:
            if live.allows(wanted.capability):
                policy.grant(wanted.capability, (), expires=held.expires)
            continue
        kept = tuple(s for s in wanted.scopes if live.allows(wanted.capability, s))
        if kept:
            policy.grant(wanted.capability, kept, expires=held.expires)
    return policy


# -- storage -----------------------------------------------------------------


class JobStore:
    """`schedule.json`, written atomically, read defensively."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else config_dir() / "schedule.json"
        self._kept: list = []

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> tuple[list[Job], list[str]]:
        """Jobs, and plain-language warnings about anything that was not read.

        A job that cannot be read is **kept verbatim and not run**. Dropping it
        would destroy something the user set up because this version of the
        code did not understand it; running it would act on a guess.
        """
        self._kept = []
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return [], []
        except OSError as exc:
            return [], [f"The schedule could not be read ({exc}), so no jobs will run."]

        try:
            raw = json.loads(text)
            entries = raw["jobs"]
            if not isinstance(entries, list):
                raise ValueError("'jobs' is not a list")
        except (ValueError, KeyError, TypeError) as exc:
            moved = self._quarantine()
            return [], [f"The schedule file was damaged ({exc}). It was moved aside "
                        f"to {moved.name} and nothing in it will run."]

        jobs: list[Job] = []
        warnings: list[str] = []
        for entry in entries:
            try:
                jobs.append(Job.from_json(entry))
            except (KeyError, TypeError, ValueError) as exc:
                self._kept.append(entry)
                name = entry.get("name", "?") if isinstance(entry, dict) else "?"
                warnings.append(f"The job {name!r} could not be read ({exc}). "
                                "It has been kept, but it will not run.")
        return jobs, warnings

    def save(self, jobs: list[Job]) -> None:
        payload = {"version": 1, "jobs": [j.to_json() for j in jobs] + self._kept}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=".schedule-", suffix=".json", dir=self._path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=1)
            os.replace(temporary, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    def _quarantine(self) -> Path:
        target = self._path.with_name(f"{self._path.name}.damaged-{int(time.time())}")
        with contextlib.suppress(OSError):
            os.replace(self._path, target)
        return target


# -- the scheduler -----------------------------------------------------------


def _plural(count: int, word: str) -> str:
    shown = f"at least {MAX_COUNTED_MISSES}" if count >= MAX_COUNTED_MISSES else str(count)
    return f"{shown} {word}" + ("" if count == 1 else "s")


class Scheduler:
    """Owns the jobs and decides, each tick, what runs."""

    def __init__(
        self,
        actions: ActionRegistry,
        *,
        policy: Callable[[], Policy] | None = None,
        audit: AuditLog | None = None,
        secret_store: SecretStore | None = None,
        store: JobStore | None = None,
        trace: Trace | None = None,
        confirm: Callable[[str], bool] | None = None,
        clock: Callable[[], float] = time.time,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._actions = actions
        self._policy = policy or Policy.load
        self._audit = audit if audit is not None else AuditLog()
        self._secret_store = secret_store if secret_store is not None else SecretStore()
        self._store = store if store is not None else JobStore()
        self._trace = trace if trace is not None else Trace()
        self._confirm = confirm or (lambda summary: False)
        self._clock = clock
        self._on_change = on_change

        self._lock = threading.RLock()
        self._running: set[str] = set()
        self._events: deque[tuple[str, dict]] = deque()
        self.dropped_events = 0
        self.wake = threading.Event()
        self._interrupted = threading.Event()

        jobs, self.warnings = self._store.load()
        self._jobs: dict[str, Job] = {job.id: job for job in jobs}

    # -- configuration ------------------------------------------------------

    @property
    def trace(self) -> Trace:
        return self._trace

    @property
    def actions(self) -> ActionRegistry:
        return self._actions

    def set_confirm(self, confirm: Callable[[str], bool] | None) -> None:
        """Hand in a real prompt once an interface exists to show it."""
        self._confirm = confirm or (lambda summary: False)

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        self._on_change = callback

    def interrupt(self) -> None:
        """Ask running jobs to stop, and start no new ones. For shutdown."""
        self._interrupted.set()

    def clear_interrupt(self) -> None:
        self._interrupted.clear()

    # -- the job table ------------------------------------------------------

    def add(self, name: str, action: str, trigger: Trigger, *,
            arguments: dict | None = None, grants=(),
            missed: Missed | str = Missed.RUN_LATE,
            now: float | None = None) -> Job:
        """Create a job. Raises on anything that could not run as described."""
        now = self._clock() if now is None else now
        name = name.strip()
        if not name:
            raise ValueError("a job needs a name")
        if self._actions.get(action) is None:
            raise KeyError(f"no action named {action!r} is registered")
        checked = tuple(JobGrant.coerce(g) for g in grants)
        if isinstance(trigger, Every) and not trigger.anchor:
            trigger = Every(trigger.seconds, now)

        next_run = None
        if not trigger.is_event:
            upcoming = trigger.next_after(datetime.fromtimestamp(now))
            if upcoming is None:
                raise ValueError(
                    "that time has already passed" if isinstance(trigger, Once)
                    else "that schedule never comes round — no date matches it")
            next_run = upcoming.timestamp()

        job = Job(id=secrets.token_hex(6), name=name, action=action,
                  trigger=trigger, arguments=dict(arguments or {}),
                  grants=checked, missed=Missed(missed), created=now,
                  next_run=next_run)
        with self._lock:
            self._jobs[job.id] = job
        self._persist()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def jobs(self) -> list[Job]:
        """The live job objects, soonest first. Read them; do not mutate them."""
        with self._lock:
            return sorted(self._jobs.values(),
                          key=lambda j: (j.next_run is None, j.next_run or 0.0, j.name))

    def find(self, action: str) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.action == action]

    def remove(self, job_id: str) -> bool:
        with self._lock:
            removed = self._jobs.pop(job_id, None) is not None
        if removed:
            self._persist()
        return removed

    def pause(self, job_id: str, reason: str = "paused by you") -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job.enabled = False
            job.paused_reason = reason
        self._persist()
        return True

    def resume(self, job_id: str, now: float | None = None) -> bool:
        """Re-enable a job, counting forward from now.

        The occurrences that fell inside the pause are not "missed" — pausing
        was a decision not to run them — so there is no catch-up run.
        """
        now = self._clock() if now is None else now
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.done:
                return False
            job.enabled = True
            job.failures = 0
            job.paused_reason = ""
            if not job.trigger.is_event:
                upcoming = job.trigger.next_after(datetime.fromtimestamp(now))
                job.next_run = upcoming.timestamp() if upcoming else None
                if job.next_run is None:
                    job.done = True
        self._persist()
        return True

    # -- events -------------------------------------------------------------

    def publish(self, name: str, payload: dict | None = None) -> None:
        """Something happened. Safe from any thread; runs on the next tick."""
        with self._lock:
            if len(self._events) >= MAX_QUEUED_EVENTS:
                self._events.popleft()
                self.dropped_events += 1
            self._events.append((str(name), dict(payload or {})))
        self.wake.set()

    # -- running ------------------------------------------------------------

    def tick(self, now: float | None = None) -> list[RunRecord]:
        """Run whatever is due at \a now. Returns what happened."""
        now = self._clock() if now is None else now
        records: list[RunRecord] = []
        if self._interrupted.is_set():
            # Closing. Whatever is due stays due, and is resolved as missed
            # the next time Akira starts.
            return records

        for job, name, payload in self._claim_events(now):
            records.append(self._execute(job, now, trigger="event",
                                         event_name=name, event=payload))

        for job, mode, note in self._claim_due(now):
            if mode == "skip":
                records.append(self._record(
                    job, RunRecord(job.id, now, now, "skipped", note, True, "time")))
            else:
                records.append(self._execute(job, now, late=mode == "late", note=note))

        if records:
            self._persist()
        return records

    def run_now(self, job_id: str, now: float | None = None) -> RunRecord | None:
        """Run a job immediately, by hand. Its schedule is not moved."""
        now = self._clock() if now is None else now
        job = self.get(job_id)
        if job is None:
            return None
        record = self._execute(job, now, trigger="manual")
        self._persist()
        return record

    def _claim_events(self, now: float) -> list[tuple[Job, str, dict]]:
        claimed: list[tuple[Job, str, dict]] = []
        with self._lock:
            pending = list(self._events)
            self._events.clear()
            for name, payload in pending:
                for job in self._jobs.values():
                    trigger = job.trigger
                    if not (job.enabled and not job.done and trigger.is_event
                            and trigger.matches(name, payload)):
                        continue
                    if now - (job.last_run or 0.0) < trigger.cooldown_s:
                        job.suppressed += 1
                        continue
                    # Claim the cooldown now, so a burst inside one tick is one run.
                    job.last_run = now
                    claimed.append((job, name, payload))
        return claimed

    def _claim_due(self, now: float) -> list[tuple[Job, str, str]]:
        """Decide what runs this tick, moving each job's clock on first.

        The next occurrence is fixed *before* anything runs, so a second tick
        arriving while a long job is still going cannot start it twice.
        """
        claimed: list[tuple[Job, str, str]] = []
        with self._lock:
            for job in sorted(self._jobs.values(), key=lambda j: j.next_run or 0.0):
                if (not job.enabled or job.done or job.next_run is None
                        or job.next_run > now):
                    continue
                due = job.next_run
                late = now - due > GRACE_S
                missed = self._count_occurrences(job.trigger, due, now) if late else 0

                upcoming = job.trigger.next_after(datetime.fromtimestamp(now))
                job.next_run = upcoming.timestamp() if upcoming else None
                if job.next_run is None:
                    job.done = True

                if not late:
                    claimed.append((job, "run", ""))
                elif job.missed is Missed.SKIP:
                    claimed.append((job, "skip",
                                    f"Missed {_plural(missed, 'scheduled run')} while "
                                    "Akira was not running; skipped, as this job "
                                    "is set to do"))
                else:
                    claimed.append((job, "late",
                                    f"Missed {_plural(missed, 'scheduled run')} while "
                                    "Akira was not running; ran once on return"))
        return claimed

    @staticmethod
    def _count_occurrences(trigger: Trigger, due: float, now: float) -> int:
        count = 1
        cursor = datetime.fromtimestamp(due)
        while count < MAX_COUNTED_MISSES:
            upcoming = trigger.next_after(cursor)
            if upcoming is None or upcoming.timestamp() > now:
                break
            count += 1
            cursor = upcoming
        return count

    def _execute(self, job: Job, now: float, *, trigger: str = "time",
                 late: bool = False, note: str = "", event_name: str = "",
                 event: dict | None = None) -> RunRecord:
        with self._lock:
            if job.id in self._running:
                return self._record(job, RunRecord(
                    job.id, now, now, "overlap",
                    "The previous run was still going, so this one was not started.",
                    late, trigger))
            self._running.add(job.id)

        actor = f"schedule:{job.name}"
        started = self._clock()
        try:
            handler = self._actions.get(job.action)
            if handler is None:
                result = ActionResult(
                    False, f"No action named {job.action!r} is registered — whatever "
                    "provides it may not be loaded.")
            else:
                self._trace.emit(Kind.STARTED, actor, text=job.action)
                try:
                    tools = ToolContext(
                        policy=narrow_policy(self._policy(), job.grants),
                        audit=self._audit, secrets=self._secret_store,
                        actor=actor, confirm=self._confirm)
                    context = JobContext(job=job, arguments=dict(job.arguments),
                                         tools=tools, trace=self._trace,
                                         event=event, event_name=event_name,
                                         cancelled=self._interrupted.is_set)
                    result = handler(context)
                    if not isinstance(result, ActionResult):
                        result = ActionResult(True, "" if result is None else str(result))
                except Exception as exc:  # noqa: BLE001 - one job must not stop the rest
                    result = ActionResult(False, f"{type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                self._running.discard(job.id)

        summary = result.summary
        if note:
            summary = f"{note}. {summary}".strip()

        with self._lock:
            if job.suppressed:
                summary += (f" ({_plural(job.suppressed, 'further event')} "
                            "held back by the cooldown.)")
                job.suppressed = 0
            if result.ok:
                job.failures = 0
            elif result.cancelled:
                pass  # interrupted, not failed: the count is left alone
            else:
                job.failures += 1
                if job.failures >= MAX_CONSECUTIVE_FAILURES and job.enabled:
                    job.enabled = False
                    job.paused_reason = (
                        f"Paused after {job.failures} failures in a row. "
                        f"The last one: {result.summary[:200]}")

        status = "ok" if result.ok else "cancelled" if result.cancelled else "failed"
        record = RunRecord(job.id, started, self._clock(), status,
                           summary[:MAX_SUMMARY_CHARS], late, trigger)
        self._trace.emit(Kind.ANSWER if result.ok else Kind.FAILED, actor,
                         text=record.summary, ok=result.ok)
        return self._record(job, record)

    def _record(self, job: Job, record: RunRecord) -> RunRecord:
        with self._lock:
            job.history.append(record)
            del job.history[:-MAX_HISTORY]
            if record.status != "overlap":
                job.last_run = record.finished
        self._audit.record(AuditEvent(
            record.finished, "schedule", f"schedule:{job.name}", job.action,
            record.status in ("ok", "skipped"),
            {"status": record.status, "trigger": record.trigger,
             "late": record.late, "summary": redact(record.summary, key="summary")},
            int((record.finished - record.started) * 1000),
            "" if record.status in ("ok", "skipped") else record.summary[:400]))
        return record

    # -- persistence --------------------------------------------------------

    def _persist(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
            try:
                self._store.save(jobs)
            except OSError as exc:
                self.warnings.append(f"The schedule could not be saved: {exc}")
        callback = self._on_change
        if callback is not None:
            try:
                callback()
            except Exception:  # noqa: BLE001 - a broken view must not stop the scheduler
                pass

    def snapshot(self) -> list[dict]:
        """Plain data for the interface, safe to hand across threads."""
        with self._lock:
            return [{
                "id": job.id, "name": job.name, "action": job.action,
                "when": job.trigger.describe(), "nextRun": job.next_run or 0.0,
                "lastRun": job.last_run or 0.0, "lastStatus": job.last_status,
                "enabled": job.enabled, "done": job.done,
                "pausedReason": job.paused_reason, "missed": job.missed.value,
                "running": job.id in self._running,
            } for job in self.jobs()]

    def history(self, job_id: str) -> list[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return [r.to_json() for r in reversed(job.history)] if job else []


class SchedulerService:
    """The thread that ticks the scheduler.

    Runs jobs one after another, deliberately. On a 6 GB card two agent jobs at
    once is two models fighting for one GPU, which is slower than taking turns
    and sometimes fails outright.
    """

    def __init__(self, scheduler: Scheduler, *, interval_s: float = 30.0) -> None:
        self._scheduler = scheduler
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._scheduler.clear_interrupt()
        self._thread = threading.Thread(target=self._loop, name="scheduler",
                                        daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        wake = self._scheduler.wake
        while not self._stop.is_set():
            # Cleared before the tick, so an event published *during* it still
            # wakes the next one instead of waiting out the whole interval.
            wake.clear()
            try:
                self._scheduler.tick()
            except Exception:  # noqa: BLE001 - the thread must outlive any one tick
                pass
            wake.wait(self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        # A running agent stops at its next token instead of holding up
        # shutdown, and holding the model while the router waits to unload.
        self._scheduler.interrupt()
        self._scheduler.wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
