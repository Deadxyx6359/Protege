"""What a tool is, and the contract every tool signs.

A tool declares the capabilities it needs and which of its arguments supplies
the scope for each. That declaration is the whole basis of enforcement: the
registry reads it to decide whether an agent is even *shown* the tool, and to
check the specific scope before the call runs.

Two rules that are not negotiable and are enforced here rather than trusted to
each tool's implementation:

  * **Arguments are validated before the tool sees them.** They arrive from a
    language model, which means they arrive from whatever the model last read —
    a web page, an email, a file. They are input from an untrusted source and
    are treated as such.
  * **Irreversible actions confirm every time.** A grant says an agent *may
    try*; it never means "and you need not ask again". Sending, posting,
    buying, submitting and deleting all stop for a person.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.permissions.capabilities import ScopeKind, get as get_capability


class ToolError(RuntimeError):
    """A tool failed in a way worth telling the agent about.

    Distinct from an internal exception: the message goes back to the model as
    the tool's result, so it should say what went wrong in terms the model can
    act on — "no such file", not a traceback.
    """


class Asking(str):
    """What a person is asked before an irreversible call, and a picture of what it is about.

    A `str`, so everything that asks in words alone goes on working, and the
    log records the words. The picture is for the person's eyes only: a JPEG of
    what the action is about, such as the page a button is on, with `marks`
    outlining the parts about to be used, each as fractions of the picture's
    width and height (x, y, width, height). It is never logged or kept.
    """

    image: bytes
    marks: tuple[tuple[float, float, float, float], ...]
    kind: str
    """The picture's media type: `image/jpeg`, or `image/png`."""

    def __new__(cls, text: str, image: bytes = b"",
                marks: tuple[tuple[float, float, float, float], ...] = (),
                kind: str = "image/jpeg") -> "Asking":
        asking = super().__new__(cls, text)
        asking.image = bytes(image or b"")
        asking.marks = tuple(marks)
        asking.kind = kind if kind in ("image/jpeg", "image/png") else "image/jpeg"
        return asking


@dataclass(frozen=True, slots=True)
class Parameter:
    """One argument, described well enough for a model to fill it in."""

    name: str
    type: str
    """`string`, `integer`, `number`, `boolean`, or `array`."""

    description: str
    required: bool = True
    default: Any = None
    enum: tuple[str, ...] = ()

    def json_schema(self) -> dict:
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.type == "array":
            schema["items"] = {"type": "string"}
        return schema


_PY_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
}


@dataclass(frozen=True, slots=True)
class Requirement:
    """A capability a tool needs, and where its scope comes from."""

    capability: str

    scope_from: str | None = None
    """Name of the argument carrying the scope — a path, a host, an account.

    Required for any scoped capability. Without it the registry could only ask
    "may this agent read files at all", never "may it read *this* file", and
    the scope on the grant would be decorative.
    """

    scope_of: Callable[[str], str] | None = None
    """Turns the argument into the scope, when the two differ: a web address into
    the site it names, so a grant for `example.com` is checked against the site
    rather than the whole address. Returns "" for an argument with no scope in
    it, which no grant covers."""

    def __post_init__(self) -> None:
        capability = get_capability(self.capability)
        if capability.scope is not ScopeKind.NONE and not self.scope_from:
            raise ValueError(
                f"{self.capability} is scoped by {capability.scope.value}, so the "
                "tool must say which argument supplies it (scope_from=...)"
            )


@dataclass(slots=True)
class ToolContext:
    """Everything a tool is allowed to reach.

    Passed in rather than imported, so a tool cannot quietly acquire something
    it was not given — and so tests can hand it a policy that denies everything
    and watch what happens.
    """

    policy: Policy
    audit: AuditLog
    secrets: SecretStore
    actor: str = "assistant"

    confirm: Callable[[str], bool] = lambda summary: False
    """Asks a person to approve an irreversible action. Defaults to *no*: a
    context assembled without a way to ask cannot approve on the user's behalf."""

    workspace: str = ""
    """The project directory the agent is working in, when there is one."""

    extra: dict[str, Any] = field(default_factory=dict)

    closers: list[Callable[[], None]] = field(default_factory=list)
    """What to close when the work this context is for ends: a browser a tool
    kept open for the next step, for one. See `finish`."""

    def on_finish(self, close: Callable[[], None]) -> None:
        """Have \a close called when the work ends, however it ends."""
        self.closers.append(close)

    def finish(self) -> None:
        """Close what tools kept open for this work, newest first. Never raises."""
        while self.closers:
            close = self.closers.pop()
            try:
                close()
            except Exception:  # noqa: BLE001 - one thing failing to close must not keep the rest open
                pass


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool hands back."""

    ok: bool
    content: str
    """Goes to the model verbatim. Prose or data, not a Python repr."""

    data: Any = None
    """Structured form, for the interface. The model never sees this."""

    @staticmethod
    def success(content: str, data: Any = None) -> "ToolResult":
        return ToolResult(True, content, data)

    @staticmethod
    def failure(content: str) -> "ToolResult":
        return ToolResult(False, content)


class Runner(Protocol):
    def __call__(self, arguments: dict, context: ToolContext) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class Tool:
    """One capability of the assistant, as offered to a model."""

    name: str
    summary: str
    """One line. This is what the model reads to decide whether to call it, so
    it describes what the tool *does*, not how it is implemented."""

    parameters: tuple[Parameter, ...]
    requires: tuple[Requirement, ...]
    run: Runner

    reversible: bool = True
    """False means every call stops for confirmation, grant or no grant."""

    describe: Callable[[dict, ToolContext], str] | None = None
    """What to ask the person before an irreversible call, when the arguments
    alone do not say it: a push names the address it goes to and how many
    commits. It may raise `ToolError` to refuse before anyone is asked."""

    def json_schema(self) -> dict:
        """The tool-call schema handed to the model."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.summary,
                "parameters": {
                    "type": "object",
                    "properties": {p.name: p.json_schema() for p in self.parameters},
                    "required": [p.name for p in self.parameters if p.required],
                },
            },
        }

    def validate(self, arguments: dict) -> dict:
        """Check and normalise arguments, raising `ToolError` on anything wrong.

        Unknown keys are dropped rather than refused. Models routinely invent a
        plausible extra field, and failing the whole call over it wastes a turn
        for something harmless — but nothing undeclared is ever passed through
        to the tool.
        """
        if not isinstance(arguments, dict):
            raise ToolError("arguments must be an object")

        declared = {p.name: p for p in self.parameters}
        cleaned: dict[str, Any] = {}

        for parameter in self.parameters:
            if parameter.name not in arguments:
                if parameter.required:
                    raise ToolError(f"missing required argument {parameter.name!r}")
                if parameter.default is not None:
                    cleaned[parameter.name] = parameter.default
                continue

            value = arguments[parameter.name]
            expected = _PY_TYPES.get(parameter.type, (str,))

            # bool is a subclass of int; an integer field must not accept True.
            if parameter.type in ("integer", "number") and isinstance(value, bool):
                raise ToolError(f"{parameter.name!r} must be a {parameter.type}")

            if not isinstance(value, expected):
                # One accommodation: a numeric string where a number is wanted.
                if parameter.type in ("integer", "number") and isinstance(value, str):
                    try:
                        value = int(value) if parameter.type == "integer" else float(value)
                    except ValueError:
                        raise ToolError(
                            f"{parameter.name!r} must be a {parameter.type}"
                        ) from None
                else:
                    raise ToolError(f"{parameter.name!r} must be a {parameter.type}")

            if parameter.enum and value not in parameter.enum:
                raise ToolError(
                    f"{parameter.name!r} must be one of: {', '.join(parameter.enum)}"
                )

            cleaned[parameter.name] = value

        for key in arguments:
            if key not in declared:
                continue
        return cleaned

    def scope_for(self, requirement: Requirement, arguments: dict) -> str | None:
        """The scope value this call needs checking against."""
        if requirement.scope_from is None:
            return None
        value = arguments.get(requirement.scope_from)
        if value is None:
            return None
        text = str(value)
        return requirement.scope_of(text) if requirement.scope_of is not None else text
