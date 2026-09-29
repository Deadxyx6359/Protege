"""The tool list, and the gate every call goes through.

Two checks happen at two different times, and the split matters:

  * **When the list is built**, a tool is included only if every capability it
    needs has been granted at all. An agent working without `files.write` is
    not told there is a way to write files — the tool is absent from its
    schema, so there is nothing to be argued into using. This is why the
    permission model is described as structural rather than instructed.

  * **When a call is made**, the specific scope is checked against the grant.
    Listing `files.read` says the agent may read *somewhere*; this decides
    whether it may read *this path*.

Everything that happens is written to the audit log, refusals included.
"""

from __future__ import annotations

import time

from akira.core.permissions import Policy
from akira.core.permissions.asking import ask_in_place, note_seen
from akira.core.permissions.capabilities import get as get_capability

from .schema import Asking, Tool, ToolContext, ToolError, ToolResult


class ToolRegistry:
    """Every tool the application knows how to run."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # -- registration --------------------------------------------------------

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"a tool named {tool.name!r} is already registered")
        for requirement in tool.requires:
            get_capability(requirement.capability)  # raises if undeclared
        if not tool.requires and not (tool.pure and tool.reversible):
            # Nothing is offered without a grant except what touches nothing.
            raise ValueError(f"{tool.name!r} needs no capability, so it must be pure: "
                             "computing from its arguments alone")
        if tool.pure and tool.requires:
            raise ValueError(f"{tool.name!r} is marked pure but needs capabilities")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    # -- what an agent may see -----------------------------------------------

    def available(self, policy: Policy, *, only: tuple[str, ...] = ()) -> list[Tool]:
        """The tools this policy permits, optionally narrowed to \a only.

        A tool needing several capabilities appears only when all of them are
        granted. Half a tool is not a useful thing to offer: an agent that can
        read a repository but not run git would spend its turns discovering
        that.
        """
        out = []
        for tool in self.all():
            if only and tool.name not in only:
                continue
            if all(policy.granted(r.capability) is not None for r in tool.requires):
                out.append(tool)
        return out

    def schemas(self, policy: Policy, *, only: tuple[str, ...] = ()) -> list[dict]:
        """Tool-call schemas for the model, already filtered by permission."""
        return [tool.json_schema() for tool in self.available(policy, only=only)]

    def missing_for(self, tool_name: str, policy: Policy) -> list[str]:
        """Which capabilities a tool still needs. For the permission prompt."""
        tool = self._tools.get(tool_name)
        if tool is None:
            return []
        return [r.capability for r in tool.requires
                if policy.granted(r.capability) is None]

    # -- running -------------------------------------------------------------

    def invoke(self, name: str, arguments: dict, context: ToolContext) -> ToolResult:
        """Validate, authorise, confirm, run, and record. Never raises."""
        started = time.monotonic()
        tool = self._tools.get(name)

        if tool is None:
            # An agent asking for a tool it was not offered is worth recording:
            # it is either a stale schema or a model inventing capability.
            context.audit.tool_call(context.actor, name, arguments, allowed=False,
                                    error="no such tool")
            return ToolResult.failure(
                f"There is no tool named {name!r}. Use one of the tools you were given."
            )

        try:
            cleaned = tool.validate(arguments)
        except ToolError as exc:
            context.audit.tool_call(context.actor, name, arguments, allowed=False,
                                    error=str(exc))
            return ToolResult.failure(str(exc))

        # -- authorisation, per requirement, with the real scope --------------
        for requirement in tool.requires:
            scope = tool.scope_for(requirement, cleaned)
            decision = context.policy.allows(requirement.capability, scope)
            why_not = ""
            if not decision:
                # A site or folder next to what was allowed: the person is asked
                # there and then, rather than sent to Settings to start again.
                detail = str(cleaned.get(requirement.scope_from, "")) if requirement.scope_from else ""
                allowed, why_not = ask_in_place(context, requirement.capability, scope,
                                                detail=detail, why=tool.summary)
                if allowed:
                    decision = context.policy.allows(requirement.capability, scope)
            if not decision:
                context.audit.tool_call(
                    context.actor, name, cleaned, allowed=False,
                    capability=requirement.capability, scope=scope or "",
                    error=decision.reason,
                    duration_ms=int((time.monotonic() - started) * 1000))
                return ToolResult.failure(
                    f"Not permitted: {decision.reason}"
                    + (f", and {why_not}. " if why_not else ". Ask the user to allow it in "
                       "Settings if it is needed.")
                )

        # -- irreversible actions stop for a person ---------------------------
        context.extra[CONFIRMED] = False
        if not tool.reversible and _asks(tool, cleaned, context):
            try:
                summary = (tool.describe(cleaned, context) if tool.describe is not None
                           else _describe(tool, cleaned))
            except ToolError as exc:
                # Refused before anyone was asked, and recorded like any refusal.
                context.audit.tool_call(
                    context.actor, name, cleaned, allowed=False, error=str(exc),
                    duration_ms=int((time.monotonic() - started) * 1000))
                return ToolResult.failure(str(exc))
            approved = False
            earlier = context.extra.setdefault(APPROVED, set())
            same = (name, str(summary))
            if tool.repeatable and same in earlier:
                # The very call the person said yes to, again, in the same work.
                approved = True
                context.audit.confirmation(context.actor, name, approved=True,
                                           summary=f"{summary}\n(approved earlier in this work)")
            else:
                if tool.repeatable:
                    summary = _with_note(summary, REPEAT_NOTE)
                try:
                    approved = bool(context.confirm(summary))
                except Exception:  # noqa: BLE001 - a broken prompt must mean "no"
                    approved = False
                context.audit.confirmation(context.actor, name,
                                           approved=approved, summary=summary)
                if approved and tool.repeatable:
                    earlier.add(same)
            if not approved:
                return ToolResult.failure(
                    "The user did not approve this action, so it was not carried out."
                )
            context.extra[CONFIRMED] = True

        # -- run ---------------------------------------------------------------
        try:
            result = tool.run(cleaned, context)
        except ToolError as exc:
            result = ToolResult.failure(str(exc))
        except Exception as exc:  # noqa: BLE001 - a tool must not kill the agent
            result = ToolResult.failure(f"{type(exc).__name__}: {exc}")

        if result.ok:
            # Addresses in what was found are ones the person may be asked about.
            note_seen(context, result.content)
        context.audit.tool_call(
            context.actor, name, cleaned, allowed=result.ok,
            capability=tool.requires[0].capability if tool.requires else "",
            # Recorded on success too, not only on refusal, so the security
            # review can see *where* a grant is actually used — the evidence
            # for suggesting it be narrowed.
            scope=(tool.scope_for(tool.requires[0], cleaned) or "") if tool.requires else "",
            duration_ms=int((time.monotonic() - started) * 1000),
            error="" if result.ok else result.content,
            result=result.content if result.ok else None)
        return result


#: In `ToolContext.extra` while a tool runs: whether a person said yes to this call.
CONFIRMED = "confirmed"
#: The calls a person said yes to in this piece of work, for `Tool.repeatable`.
APPROVED = "approved_calls"
REPEAT_NOTE = ("Yes also covers this same call again during this piece of work; "
               "anything different asks again.")


def confirmed(context: ToolContext) -> bool:
    """Whether the call running now was asked about and approved."""
    return bool(context.extra.get(CONFIRMED))


def _asks(tool: Tool, arguments: dict, context: ToolContext) -> bool:
    # Unattended work asks about everything irreversible, a new file included.
    if tool.asks is None or not context.attended:
        return True
    try:
        return bool(tool.asks(arguments, context))
    except Exception:  # noqa: BLE001 - unsure means ask
        return True


def _with_note(summary, note: str):
    """\a summary with \a note after it, keeping a picture that came with it."""
    text = f"{summary}\n\n{note}"
    if isinstance(summary, Asking):
        return Asking(text, summary.image, summary.marks, summary.kind)
    return text


def _describe(tool: Tool, arguments: dict) -> str:
    """A one-line, human-readable account of what is about to happen.

    Shown in the confirmation prompt, so it must state the *actual* effect with
    the *actual* values. "Run a tool?" is not a question anybody can answer.
    """
    parts = ", ".join(f"{k}={v!r}" for k, v in list(arguments.items())[:4])
    return f"{tool.summary} ({tool.name}: {parts})" if parts else tool.summary
