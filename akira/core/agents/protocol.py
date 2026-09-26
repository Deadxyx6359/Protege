"""Getting tool calls out of a local model, and results back in.

llama.cpp exposes no reliable native tool-calling across model families, so
this is prompted: the tools are described in the system message and the model
is asked to emit a call in a fixed shape. Different families were trained on
different shapes, and a model under pressure will reach for the one it knows,
so the parser accepts all the common ones rather than insisting on the house
style:

    <tool_call>{"name": "...", "arguments": {...}}</tool_call>   Hermes, Qwen
    ```json {"name": "...", "arguments": {...}} ```              generic
    {"name": "...", "arguments": {...}}                          bare

Being liberal here is not sloppiness. The alternative is a turn wasted telling
a model its correct answer was formatted wrong, and models rarely recover from
that gracefully — they tend to apologise and reformat it wrong a second way.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from akira.core.tools import Tool

_TOOL_CALL_TAG = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL | re.IGNORECASE)
_FENCED = re.compile(
    r"```(?:json|tool_call)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Call:
    """One tool invocation the model asked for."""

    name: str
    arguments: dict = field(default_factory=dict)


def _coerce(raw: dict) -> Call | None:
    """Turn one parsed object into a Call, tolerating the usual variations."""
    if not isinstance(raw, dict):
        return None

    name = raw.get("name") or raw.get("tool") or raw.get("function")
    # Some models nest as {"function": {"name": ..., "arguments": ...}}.
    if isinstance(name, dict):
        raw = name
        name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None

    arguments = raw.get("arguments")
    if arguments is None:
        arguments = raw.get("parameters") or raw.get("args") or {}
    # Occasionally the arguments arrive as a JSON string rather than an object.
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}

    return Call(name.strip(), arguments)


def _balanced_objects(text: str) -> list[str]:
    """Every top-level {...} span, tracking string literals.

    A brace-counting scan rather than a regex, because tool arguments regularly
    contain braces inside strings — file contents and code especially — and a
    regex cannot tell those from the object's own.
    """
    spans: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth:
                depth -= 1
                if depth == 0 and start >= 0:
                    spans.append(text[start:index + 1])
    return spans


_PYTHON_CALL = re.compile(r"^[ \t]*([A-Za-z_]\w*)\s*\(", re.MULTILINE)


def _python_calls(text: str, known: frozenset[str]) -> tuple[list[Call], str]:
    """Calls written as Python, `write_file(path="...", content="...")`, the way a
    coding model reaches for them. Only for tools the agent has, and only with
    literal keyword arguments: nothing in them is ever run."""
    import ast

    for match in _PYTHON_CALL.finditer(text):
        if match.group(1) not in known:
            continue
        # The call runs to its closing bracket, however many lines that takes.
        start, depth, quote, index = match.start(1), 0, "", match.end() - 1
        while index < len(text):
            char = text[index]
            if quote:
                if char == "\\":
                    index += 1
                elif text.startswith(quote, index):
                    index += len(quote) - 1
                    quote = ""
            elif text.startswith(('"""', "'''"), index):
                quote = text[index:index + 3]
                index += 2
            elif char in "\"'":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        source = text[start:index + 1]
        try:
            node = ast.parse(source.strip(), mode="eval").body
            if not isinstance(node, ast.Call) or node.args:
                continue
            arguments = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords if kw.arg}
        except (SyntaxError, ValueError):
            continue
        remainder = text.replace(source, "")
        remainder = re.sub(r"```\w*\s*```", "", remainder)
        return [Call(match.group(1), arguments)], remainder.strip()
    return [], text


def parse_calls(text: str, known: frozenset[str] = frozenset()) -> tuple[list[Call], str]:
    """Pull tool calls out of \a text.

    Returns the calls and the prose with the call syntax removed, so the
    interface never shows a user raw JSON the model meant for the runtime.
    \a known is the agent's tool names, which lets a call written as Python be
    recognised too.
    """
    calls: list[Call] = []
    remainder = text

    for pattern in (_TOOL_CALL_TAG, _FENCED):
        for match in pattern.finditer(remainder):
            try:
                call = _coerce(json.loads(match.group(1)))
            except json.JSONDecodeError:
                continue
            if call is not None:
                calls.append(call)
        if calls:
            remainder = pattern.sub("", remainder)
            return calls, remainder.strip()

    # Nothing tagged or fenced. Accept a bare object only when it really looks
    # like a call, so ordinary prose containing JSON is not mistaken for one.
    for span in _balanced_objects(remainder):
        try:
            raw = json.loads(span)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        if not ({"name", "tool", "function"} & set(raw)):
            continue
        call = _coerce(raw)
        if call is not None:
            calls.append(call)
            remainder = remainder.replace(span, "")

    if not calls and known:
        named = _named_objects(text, known)
        if named[0]:
            return named
        return _python_calls(text, known)
    return calls, remainder.strip()


_NAMED_OBJECT = re.compile(r"(?:^|\s)`?([A-Za-z_]\w*)`?\s*[:=]?\s*(?=\{)")


def _named_objects(text: str, known: frozenset[str]) -> tuple[list[Call], str]:
    """A tool's name followed by its arguments as JSON, `save_drawing {"path": ...}`,
    for tools the agent has."""
    for match in _NAMED_OBJECT.finditer(text):
        if match.group(1) not in known:
            continue
        spans = _balanced_objects(text[match.end():])
        if not spans:
            continue
        try:
            arguments = json.loads(spans[0])
        except json.JSONDecodeError:
            continue
        if isinstance(arguments, dict):
            remainder = text.replace(match.group(0).lstrip() + spans[0], "")
            return [Call(match.group(1), arguments)], remainder.strip()
    return [], text


def _placeholder(parameter) -> object:
    return {"integer": 1, "number": 1.0, "boolean": True, "array": ["..."]}.get(
        parameter.type, "...")


def render_tools(tools: list[Tool]) -> str:
    """The tool catalogue, as it appears in the system message."""
    if not tools:
        return (
            "You have no tools available in this conversation. Answer from what "
            "you know, and say plainly when something would need a tool you do "
            "not have."
        )

    # The example is one of the agent's own tools with its own argument names:
    # given `{"argument": "value"}`, a small model copies "argument" verbatim.
    example = tools[0]
    arguments = {p.name: _placeholder(p) for p in example.parameters if p.required}
    lines = [
        "You can use tools. To use one, reply with a single call in exactly "
        "this form and nothing else, with the tool's own argument names:",
        "",
        "<tool_call>" + json.dumps({"name": example.name, "arguments": arguments})
        + "</tool_call>",
        "",
        "Rules:",
        "  - One call at a time. Wait for the result before deciding what to do next.",
        "  - Use only the tools listed below, with exactly the arguments listed.",
        "  - When you have what you need, answer normally with no tool call.",
        "  - If a tool is refused, do not retry it unchanged. Say what you needed "
        "and why, and let the user decide.",
        "",
        "Available tools:",
    ]

    for tool in tools:
        lines.append(f"\n{tool.name} — {tool.summary}")
        for parameter in tool.parameters:
            flag = "required" if parameter.required else "optional"
            detail = f"    {parameter.name} ({parameter.type}, {flag}): {parameter.description}"
            if parameter.enum:
                detail += f" One of: {', '.join(parameter.enum)}."
            lines.append(detail)
    return "\n".join(lines)


def format_result(call: Call, content: str, *, ok: bool) -> str:
    """A tool's outcome, as the model sees it on the next turn."""
    status = "result" if ok else "error"
    return f"<tool_response name=\"{call.name}\" status=\"{status}\">\n{content}\n</tool_response>"
