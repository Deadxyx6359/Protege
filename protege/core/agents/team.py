"""Several agents working one task, in order, handing off as they go.

**Why a pipeline and not a coordinator that decides.** The obvious design is a
lead agent that reads the task and picks who should act next. On a hosted
frontier model that works. On a 4-bit 8B running on a 6 GB card it does not:
the lead invents a teammate who does not exist, or picks the same one four
times, and either way the step budget is gone before any work happened. A fixed
order per team is dull and it runs. `Team.run` is therefore deterministic in
*who* acts; the model decides only what to say when its turn comes.

Three properties this file owes the rest of the system:

  * **A member cannot exceed the team's permissions.** Every member is run
    against the one `ToolContext` the team was given, and a role's tool list can
    only narrow what the policy already allows. There is no path by which
    joining a team grants anything.
  * **A member that fails does not take the team with it.** Its failure is
    recorded, the next member is told the step was lost, and the run continues.
    A research answer missing its critic is worth more than no answer.
  * **The hand-off is visible.** Each transition emits a `MESSAGE` event with
    `to` set, which is the edge the interface draws between agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from protege.core.models import ModelRouter
from protege.core.tools import ToolContext, ToolRegistry

from .loop import Agent, AgentSpec, Outcome
from .trace import Kind, Trace

#: A member's contribution is trimmed to this before it is shown to the next
#: one. Four members each handing on 6000 characters would put a 24k-character
#: brief in front of the last one, which on an 8k context means the task itself
#: falls out of the window.
MAX_CONTRIBUTION_CHARS = 2000


@dataclass(frozen=True, slots=True)
class TeamSpec:
    """A team: who is on it, in what order, and what it is for."""

    name: str
    purpose: str
    members: tuple[AgentSpec, ...]

    def __post_init__(self) -> None:
        if not self.members:
            raise ValueError(f"team {self.name!r} has no members")
        names = [m.name for m in self.members]
        if len(set(names)) != len(names):
            raise ValueError(f"team {self.name!r} has two members with one name")


@dataclass(frozen=True, slots=True)
class Handoff:
    """One member passing work to the next."""

    sender: str
    recipient: str
    summary: str


@dataclass(slots=True)
class TeamOutcome:
    """What a team run produced."""

    answer: str = ""
    ok: bool = True
    stopped: str = ""
    """`answered`, `cancelled`, or `failed` — the last only when nobody
    produced anything at all."""

    contributions: dict[str, str] = field(default_factory=dict)
    failures: list[tuple[str, str]] = field(default_factory=list)
    """(member, why) for each one that did not finish."""

    handoffs: list[Handoff] = field(default_factory=list)
    outcomes: dict[str, Outcome] = field(default_factory=dict)


class Team:
    """A team of agents, run in order against one shared context."""

    def __init__(self, spec: TeamSpec, *, router: ModelRouter,
                 registry: ToolRegistry, context: ToolContext,
                 trace: Trace | None = None) -> None:
        self.spec = spec
        self._router = router
        self._registry = registry
        self._context = context
        self._trace = trace or Trace()

    @property
    def trace(self) -> Trace:
        return self._trace

    def member(self, name: str) -> AgentSpec:
        for spec in self.spec.members:
            if spec.name == name:
                return spec
        raise KeyError(f"no member named {name!r} on team {self.spec.name!r}")

    # -- the brief ------------------------------------------------------------

    def _brief(self, task: str, outcome: TeamOutcome, spec: AgentSpec) -> str:
        """What this member is told: the task, then what came before it."""
        parts = [f"The team was asked: {task}"]

        for previous in self.spec.members:
            if previous.name == spec.name:
                break
            if previous.name in outcome.contributions:
                text = outcome.contributions[previous.name]
                parts.append(f"\n--- from {previous.name} ---\n{text}")
            elif any(name == previous.name for name, _ in outcome.failures):
                # Said plainly. A member that silently receives less than it
                # expected will invent the missing part rather than work
                # around it.
                parts.append(
                    f"\n--- from {previous.name} ---\n"
                    f"({previous.name} could not finish. Work without it.)")

        parts.append(f"\nYou are {spec.name}. Do your part now.")
        return "\n".join(parts)

    # -- the run --------------------------------------------------------------

    def run(self, task: str, *,
            on_token: Callable[[str], None] | None = None,
            is_cancelled: Callable[[], bool] | None = None) -> TeamOutcome:
        """Work \a task through every member in order."""
        outcome = TeamOutcome()
        self._trace.emit(Kind.STARTED, self.spec.name, text=task)

        previous_name = ""
        for spec in self.spec.members:
            if is_cancelled is not None and is_cancelled():
                outcome.ok, outcome.stopped = False, "cancelled"
                self._trace.emit(Kind.FAILED, self.spec.name, text="cancelled")
                return outcome

            brief = self._brief(task, outcome, spec)

            if previous_name:
                summary = outcome.contributions.get(previous_name, "")
                handoff = Handoff(previous_name, spec.name,
                                  summary[:200])
                outcome.handoffs.append(handoff)
                # The edge the interface draws between two agents.
                self._trace.emit(Kind.MESSAGE, previous_name, to=spec.name,
                                 text=handoff.summary)

            agent = Agent(spec, router=self._router, registry=self._registry,
                          context=self._context, trace=self._trace)
            result = agent.run(brief, on_token=on_token,
                               is_cancelled=is_cancelled)
            outcome.outcomes[spec.name] = result

            if result.stopped == "cancelled":
                outcome.ok, outcome.stopped = False, "cancelled"
                return outcome

            if result.ok and result.answer.strip():
                outcome.contributions[spec.name] = \
                    result.answer[:MAX_CONTRIBUTION_CHARS]
                previous_name = spec.name
            else:
                why = result.answer or result.stopped or "produced nothing"
                outcome.failures.append((spec.name, why))
                self._trace.emit(Kind.NOTE, self.spec.name,
                                 text=f"{spec.name} did not finish: {why}")
                # previous_name is left alone on purpose: the next member hands
                # off from the last one that actually produced something.

        return self._finish(outcome)

    def _finish(self, outcome: TeamOutcome) -> TeamOutcome:
        """The team's answer is the last contribution anybody managed."""
        for spec in reversed(self.spec.members):
            if spec.name in outcome.contributions:
                outcome.answer = outcome.contributions[spec.name]
                outcome.stopped = "answered"
                outcome.ok = not outcome.failures
                self._trace.emit(Kind.ANSWER, self.spec.name,
                                 text=outcome.answer, ok=outcome.ok)
                return outcome

        outcome.ok, outcome.stopped = False, "failed"
        outcome.answer = (
            f"Nobody on {self.spec.name} was able to finish. "
            + "; ".join(f"{who}: {why}" for who, why in outcome.failures)
        )
        self._trace.emit(Kind.FAILED, self.spec.name, text=outcome.answer)
        return outcome


# -- the teams that exist ----------------------------------------------------


def research_team() -> TeamSpec:
    from .roles import RESEARCH

    return TeamSpec(
        name="research",
        purpose="Find out what is true about something and say so with sources.",
        members=RESEARCH,
    )


def software_team() -> TeamSpec:
    from .roles import SOFTWARE

    return TeamSpec(
        name="software",
        purpose="Plan a change, make it, and review what was made.",
        members=SOFTWARE,
    )
