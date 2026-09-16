"""One agent: decide, use a tool, look at the result, repeat.

The loop is deliberately small. Most of what makes an agent useful is not in
here — it is in which tools it was given, which is a permission question, and
in how good the model is, which is a hardware question. What this file owes
everyone is that it always terminates, always reports what happened, and never
lets a tool failure end the run.

Three properties worth stating, because each was a decision:

  * **A refused tool is not retried.** The model is told why, once. Local models
    will otherwise loop on a permission error until the step budget runs out,
    which burns a minute and teaches the user nothing.
  * **Step budget is hard.** Running out is an outcome, reported as such, not a
    silent stop or an exception.
  * **Cancellation is cooperative.** A Python thread cannot be killed, so the
    token callback raises, unwinding llama.cpp's stream from inside.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from akira.core.context.place import now_line
from akira.core.conversation import NO_INVENTED_ADDRESSES, Cancelled
from akira.core.models import ModelRouter, Route
from akira.core.tools import ToolContext, ToolRegistry
from akira.models.base import ChatMessage
from akira.models.think_filter import ThinkFilter

from .protocol import Call, format_result, parse_calls, render_tools
from .trace import Kind, Trace

#: Enough for a real piece of work, few enough that a confused agent stops
#: before it has spent five minutes of a 30 tok/s model going in circles.
DEFAULT_MAX_STEPS = 8

#: A tool result longer than this is trimmed before going back to the model.
#: The tools cap their own output too; this is the backstop for the total.
MAX_RESULT_CHARS = 6000


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Who an agent is and what it may reach."""

    name: str
    role: str
    """Goes into the system prompt. Written as an instruction to the agent, in
    the second person — this is the whole of its personality and remit."""

    route: Route = Route.CHAT
    tools: tuple[str, ...] = ()
    """Tool names this agent may use. Empty means every permitted tool.

    Narrowing matters even when the permission is held: a reviewer that cannot
    write is a better reviewer, because it cannot quietly fix what it was
    supposed to report.
    """

    max_steps: int = DEFAULT_MAX_STEPS
    temperature: float = 0.4
    """Lower than chat. An agent choosing a tool is making a decision, not
    writing prose, and creativity there shows up as invented arguments."""


@dataclass(slots=True)
class Outcome:
    """What a run produced."""

    answer: str = ""
    ok: bool = True
    steps: int = 0
    stopped: str = ""
    """Why it ended: `answered`, `budget`, `cancelled`, or `failed`."""

    calls: list[Call] = field(default_factory=list)


class Agent:
    """One agent, bound to its tools, its model and its trace."""

    def __init__(self, spec: AgentSpec, *, router: ModelRouter,
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

    # -- prompt ---------------------------------------------------------------

    def _tools(self):
        return self._registry.available(self._context.policy, only=self.spec.tools)

    def system_prompt(self) -> str:
        parts = [self.spec.role.strip(), "", NO_INVENTED_ADDRESSES, "",
                 render_tools(self._tools())]
        if self._context.workspace:
            parts += ["", f"You are working in: {self._context.workspace}"]
        # A model has no clock. The place and time zone only with location.read.
        parts += ["", now_line(self._context.policy)]
        return "\n".join(parts)

    # -- the loop -------------------------------------------------------------

    def run(self, task: str, *,
            on_token: Callable[[str], None] | None = None,
            is_cancelled: Callable[[], bool] | None = None) -> Outcome:
        """Work on \a task until answered, out of steps, or cancelled."""
        name = self.spec.name
        self._trace.emit(Kind.STARTED, name, text=task)

        messages = [
            ChatMessage(role="system", content=self.system_prompt()),
            ChatMessage(role="user", content=task),
        ]
        outcome = Outcome()

        for step in range(1, self.spec.max_steps + 1):
            outcome.steps = step
            try:
                reply = self._generate(messages, on_token, is_cancelled, step)
            except Cancelled:
                outcome.ok, outcome.stopped = False, "cancelled"
                self._trace.emit(Kind.FAILED, name, text="cancelled", step=step)
                return outcome
            except Exception as exc:  # noqa: BLE001 - report, do not crash the caller
                outcome.ok, outcome.stopped = False, "failed"
                outcome.answer = f"{type(exc).__name__}: {exc}"
                self._trace.emit(Kind.FAILED, name, text=outcome.answer, step=step)
                return outcome

            calls, prose = parse_calls(reply)

            if not calls:
                outcome.answer = prose or reply.strip()
                outcome.stopped = "answered"
                self._trace.emit(Kind.ANSWER, name, text=outcome.answer, step=step)
                return outcome

            # Only the first call is honoured per step. Models sometimes emit
            # several at once, having guessed at results they have not seen;
            # running them all acts on those guesses.
            call = calls[0]
            outcome.calls.append(call)
            messages.append(ChatMessage(role="assistant", content=reply))

            self._trace.emit(Kind.TOOL_CALL, name, tool=call.name,
                             arguments=call.arguments, text=prose, step=step)

            result = self._registry.invoke(call.name, call.arguments, self._context)
            content = result.content[:MAX_RESULT_CHARS]

            self._trace.emit(Kind.TOOL_RESULT, name, tool=call.name,
                             text=content, ok=result.ok, step=step)

            if not result.ok and content.startswith("Not permitted"):
                # Hand back the refusal and stop. A local model told "no" will
                # otherwise spend the rest of the budget rephrasing the request.
                outcome.answer = content
                outcome.ok = False
                outcome.stopped = "answered"
                self._trace.emit(Kind.ANSWER, name, text=content, step=step)
                return outcome

            messages.append(ChatMessage(
                role="user", content=format_result(call, content, ok=result.ok)))

        outcome.ok = False
        outcome.stopped = "budget"
        outcome.answer = (
            f"I used all {self.spec.max_steps} of my steps without finishing. "
            f"Last thing I did: {outcome.calls[-1].name if outcome.calls else 'nothing'}."
        )
        self._trace.emit(Kind.FAILED, name, text=outcome.answer, step=outcome.steps)
        return outcome

    def _generate(self, messages, on_token, is_cancelled, step: int) -> str:
        """One model turn, with reasoning blocks filtered out of the stream."""
        thinking = ThinkFilter()
        collected: list[str] = []

        def emit(chunk: str) -> None:
            if is_cancelled is not None and is_cancelled():
                raise Cancelled()
            visible = thinking.feed(chunk)
            if visible:
                collected.append(visible)
                if on_token is not None:
                    on_token(visible)

        with self._router.acquire(self.spec.route) as backend:
            result = backend.generate(
                messages,
                max_tokens=1024,
                temperature=self.spec.temperature,
                on_token=emit,
            )
        tail = thinking.flush()
        if tail:
            collected.append(tail)

        streamed = "".join(collected)
        if streamed.strip():
            return streamed

        # Nothing arrived through the stream. That is not necessarily a
        # failure: the contract is that `generate` *returns* its text, and
        # streaming is an option on top. A backend that batches -- or a cloud
        # model reached through `model.cloud` -- satisfies the contract without
        # calling `on_token` once, and reconstructing the reply from the stream
        # alone would hand the loop an empty string and end the run with a
        # blank answer. The returned text has not passed the filter, so it goes
        # through a fresh one here.
        text = getattr(result, "text", "") or ""
        if not text:
            return streamed
        whole = ThinkFilter()
        return whole.feed(text) + whole.flush()
