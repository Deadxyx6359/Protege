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

from protege.core.permissions import Policy
from protege.core.permissions.capabilities import get as get_capability

from .schema import Tool, ToolContext, ToolError, ToolResult


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
            if not decision:
                context.audit.tool_call(
                    context.actor, name, cleaned, allowed=False,
                    capability=requirement.capability, scope=scope or "",
                    error=decision.reason,
                    duration_ms=int((time.monotonic() - started) * 1000))
                return ToolResult.failure(
                    f"Not permitted: {decision.reason}. "
                    "Ask the user to allow it in Settings if it is needed."
                )

        # -- irreversible actions stop for a person ---------------------------
        if not tool.reversible:
            summary = _describe(tool, cleaned)
            approved = False
            try:
                approved = bool(context.confirm(summary))
            except Exception:  # noqa: BLE001 - a broken prompt must mean "no"
                approved = False
            context.audit.confirmation(context.actor, name,
                                       approved=approved, summary=summary)
            if not approved:
                return ToolResult.failure(
                    "The user did not approve this action, so it was not carried out."
                )

        # -- run ---------------------------------------------------------------
        try:
            result = tool.run(cleaned, context)
        except ToolError as exc:
            result = ToolResult.failure(str(exc))
        except Exception as exc:  # noqa: BLE001 - a tool must not kill the agent
            result = ToolResult.failure(f"{type(exc).__name__}: {exc}")

        context.audit.tool_call(
            context.actor, name, cleaned, allowed=result.ok,
            capability=tool.requires[0].capability if tool.requires else "",
            duration_ms=int((time.monotonic() - started) * 1000),
            error="" if result.ok else result.content,
            result=result.content if result.ok else None)
        return result


def _describe(tool: Tool, arguments: dict) -> str:
    """A one-line, human-readable account of what is about to happen.

    Shown in the confirmation prompt, so it must state the *actual* effect with
    the *actual* values. "Run a tool?" is not a question anybody can answer.
    """
    parts = ", ".join(f"{k}={v!r}" for k, v in list(arguments.items())[:4])
    return f"{tool.summary} ({tool.name}: {parts})" if parts else tool.summary
