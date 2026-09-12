"""Time- and event-based jobs, each run under its own narrowed permissions.

See `scheduler` for the guarantees: durable across restarts, missed runs
resolved explicitly, failures contained, and unattended runs unable to approve
anything irreversible.
"""

from .cron import CronError, CronExpr
from .scheduler import (
    ActionRegistry,
    ActionResult,
    Job,
    JobContext,
    JobGrant,
    JobPolicy,
    JobStore,
    Missed,
    RunRecord,
    Scheduler,
    SchedulerService,
    narrow_policy,
)
from .triggers import (
    Cron,
    Daily,
    Every,
    Monthly,
    OnEvent,
    Once,
    Trigger,
    TriggerError,
    Weekly,
    trigger_from_json,
)

__all__ = [
    "CronError", "CronExpr",
    "ActionRegistry", "ActionResult", "Job", "JobContext", "JobGrant",
    "JobPolicy", "JobStore", "Missed", "RunRecord", "Scheduler",
    "SchedulerService", "narrow_policy",
    "Cron", "Daily", "Every", "Monthly", "OnEvent", "Once", "Trigger",
    "TriggerError", "Weekly", "trigger_from_json",
]
