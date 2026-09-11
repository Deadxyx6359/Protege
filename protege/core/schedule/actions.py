"""Actions a scheduled job can name: one agent, or a whole team.

Both run against the job's *narrowed* tool context, so a nightly research job
granted one folder reaches that folder and nothing else, whatever the user has
granted elsewhere.

When an event started the run, its payload is appended to the task. Treat it
as data: it can come from a file name or a web page, and a file name can be
written to look like an instruction. The permissions on the job are what bound
the damage, not the wording of the prompt.
"""

from __future__ import annotations

import json

from protege.core.agents import Agent, research_team, software_team
from protege.core.agents.roles import ALL_ROLES
from protege.core.agents.team import Team
from protege.core.models import ModelRouter
from protege.core.tools import ToolRegistry

from .scheduler import ActionRegistry, ActionResult, JobContext

SUMMARY_CHARS = 800

TEAMS = {"research": research_team, "software": software_team}


def _result(ok: bool, stopped: str, answer: str) -> ActionResult:
    if stopped == "cancelled":
        return ActionResult(False, "Stopped because Protégé was closing.",
                            cancelled=True)
    return ActionResult(ok, answer[:SUMMARY_CHARS])


def _task(context: JobContext) -> str:
    task = str(context.arguments.get("task", "")).strip()
    if context.event is None:
        return task
    detail = json.dumps(context.event, ensure_ascii=False)[:1000]
    return (f"{task}\n\nThis run was started by the event "
            f"{context.event_name!r}, which carried: {detail}")


def check_arguments(action: str, arguments: dict) -> str:
    """Why a job with these arguments could not run, or "" if it could.

    Checked when the job is created, so a typo is refused at the moment it is
    made rather than surfacing as a failed run at three in the morning.
    """
    if action == "security_review":
        return "The security review schedules itself; it runs every day."
    if action == "distil_memory":
        return "Memory sets itself up when a vault is chosen for it."
    if action == "notify":
        if not str(arguments.get("text", "")).strip():
            return "A notice needs something to say."
        return ""
    if action == "agent":
        role = str(arguments.get("role", ""))
        if role not in ALL_ROLES:
            return f"There is no role named {role!r}."
        who = "agent"
    elif action == "team":
        team = str(arguments.get("team", ""))
        if team not in TEAMS:
            return f"There is no team named {team!r}."
        who = "team"
    else:
        return ""
    if not str(arguments.get("task", "")).strip():
        return f"The job needs a task to give the {who}."
    return ""


def register_agent_actions(actions: ActionRegistry, *, router: ModelRouter,
                           registry: ToolRegistry) -> None:
    """Add `agent` and `team` to \a actions."""

    def run_agent(context: JobContext) -> ActionResult:
        role = str(context.arguments.get("role", ""))
        spec = ALL_ROLES.get(role)
        if spec is None:
            return ActionResult(False, f"There is no role named {role!r}.")
        task = _task(context)
        if not task:
            return ActionResult(False, "The job has no task to give the agent.")
        outcome = Agent(spec, router=router, registry=registry,
                        context=context.tools, trace=context.trace,
                        ).run(task, is_cancelled=context.cancelled)
        return _result(outcome.ok, outcome.stopped, outcome.answer)

    def run_team(context: JobContext) -> ActionResult:
        name = str(context.arguments.get("team", ""))
        build = TEAMS.get(name)
        if build is None:
            return ActionResult(False, f"There is no team named {name!r}.")
        task = _task(context)
        if not task:
            return ActionResult(False, "The job has no task to give the team.")
        outcome = Team(build(), router=router, registry=registry,
                       context=context.tools, trace=context.trace,
                       ).run(task, is_cancelled=context.cancelled)
        return _result(outcome.ok, outcome.stopped, outcome.answer)

    actions.register("agent", run_agent, "Give one agent a task")
    actions.register("team", run_team, "Give a team a task")
