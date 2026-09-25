"""Scheduled jobs and the security review, as QML sees them.

The scheduler runs on its own thread and announces changes from there. As with
the trace, those cross to the UI thread through a private signal before any
property QML is bound to changes.

Running a job by hand, or asking for a review, starts a worker thread and
returns at once. A review reads the whole activity log and a job can be an
agent working for minutes; doing either on the UI thread would freeze the
window. Worse, a job that reached an irreversible step would ask for
confirmation *from the UI thread* — which `ConfirmBridge` refuses outright,
precisely because waiting there would deadlock.

A critical finding is announced with its own signal rather than left to sit in
a list. "Surfaced, not logged quietly" is the whole point of the review.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Property, QObject, Signal, Slot

from akira.core.review import REVIEW_ACTION, Review, ReviewStore
from akira.core.schedule import Missed, Scheduler, trigger_from_json
from akira.core.schedule.actions import check_arguments


class ScheduleBridge(QObject):
    """The job table, its history, and the latest review."""

    jobsChanged = Signal()
    reviewChanged = Signal()

    #: The number of critical findings, emitted whenever a review has any.
    #: The shell should raise this, not just repaint a list.
    criticalFound = Signal(int)

    #: Private: carry a change or a review from a worker thread to this one.
    _changed = Signal()
    _reviewed = Signal(object)

    def __init__(self, scheduler: Scheduler, reviews: ReviewStore | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._scheduler = scheduler
        self._reviews = reviews if reviews is not None else ReviewStore()
        self._jobs: list = scheduler.snapshot()
        self._review: Review | None = self._reviews.latest()

        # No connection type given: direct within a thread, queued across.
        self._changed.connect(self._refresh)
        self._reviewed.connect(self._on_review)
        scheduler.set_on_change(self._changed.emit)

    # -- jobs -----------------------------------------------------------------

    @Property("QVariantList", notify=jobsChanged)
    def jobs(self) -> list:
        """Each job as a map: id, name, action, when, nextRun, lastRun,
        lastStatus, enabled, done, pausedReason, missed, running."""
        return list(self._jobs)

    @Property("QVariantList", notify=jobsChanged)
    def warnings(self) -> list:
        """Plain-language problems found loading or saving the schedule."""
        return list(self._scheduler.warnings)

    @Slot(str, result="QVariantList")
    def history(self, job_id: str) -> list:
        """A job's runs, newest first."""
        return self._scheduler.history(job_id)

    @Slot(str)
    def pause(self, job_id: str) -> None:
        self._scheduler.pause(job_id)

    @Slot(str)
    def resume(self, job_id: str) -> None:
        self._scheduler.resume(job_id)

    @Slot(str)
    def remove(self, job_id: str) -> None:
        self._scheduler.remove(job_id)

    @Slot("QVariantMap", result=str)
    def addJob(self, spec: dict) -> str:
        """Create a job. Returns "" on success, or why it was refused.

        `spec` holds `name`; `action` (`agent`, `team`, `pipeline` or `notify`);
        `trigger`, a map such as `{"kind": "daily", "time": "07:30"}`; `arguments`
        (`role` or `team`, and `task`; for a pipeline, `brief` and `publish`);
        `grants`, a list of `{"capability", "scopes"}`; and `missed`, either
        `run_late` or `skip`.
        """
        spec = dict(spec or {})
        action = str(spec.get("action") or "")
        arguments = spec.get("arguments") or {}
        missed = str(spec.get("missed") or Missed.RUN_LATE.value)
        if not isinstance(arguments, dict):
            return "A job's arguments must be a set of named values."
        if missed not in {m.value for m in Missed}:
            return "A missed run can either run late or be skipped."
        problem = check_arguments(action, arguments)
        if problem:
            return problem
        try:
            trigger = trigger_from_json(spec.get("trigger"))
            self._scheduler.add(str(spec.get("name") or ""), action, trigger,
                                arguments=arguments,
                                grants=list(spec.get("grants") or ()),
                                missed=missed)
        except (KeyError, ValueError, TypeError) as exc:
            return str(exc.args[0]) if exc.args else type(exc).__name__
        return ""

    @Slot(str)
    def runNow(self, job_id: str) -> None:
        """Run a job by hand, on a worker thread. Returns immediately."""
        threading.Thread(target=self._scheduler.run_now, args=(job_id,),
                         name="schedule-run", daemon=True).start()

    # -- the review -------------------------------------------------------------

    @Property("QVariantList", notify=reviewChanged)
    def findings(self) -> list:
        """The latest review's findings, worst first. Each is a map: severity,
        code, title, detail, suggestion, capability."""
        return [f.to_json() for f in self._review.findings] if self._review else []

    @Property(float, notify=reviewChanged)
    def lastReviewAt(self) -> float:
        return self._review.at if self._review else 0.0

    @Property(str, notify=reviewChanged)
    def reviewSummary(self) -> str:
        return self._review.summary() if self._review else "Not reviewed yet"

    @Property(int, notify=reviewChanged)
    def criticalCount(self) -> int:
        return self._review.counts["critical"] if self._review else 0

    @Slot()
    def runReview(self) -> None:
        """Run the security review now, on a worker thread."""
        jobs = self._scheduler.find(REVIEW_ACTION)
        if jobs:
            self.runNow(jobs[0].id)

    def on_review(self, review: Review) -> None:
        """Hand to `register_review_action`. Safe to call from any thread."""
        self._reviewed.emit(review)

    # -- on the UI thread ---------------------------------------------------------

    def _refresh(self) -> None:
        self._jobs = self._scheduler.snapshot()
        self.jobsChanged.emit()

    def _on_review(self, review: Review) -> None:
        self._review = review
        self.reviewChanged.emit()
        critical = review.counts["critical"]
        if critical:
            self.criticalFound.emit(critical)
