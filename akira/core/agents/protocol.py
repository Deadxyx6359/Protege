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


#: A value in Python's triple quotes, where JSON wants one pair: `"content": """…"""`.
_TRIPLE_QUOTED = re.compile(r'(:\s*)"""(.*?)"""(\s*[,}])', re.DOTALL)


def _loads(span: str):
    """A call's JSON, forgiving the two ways small models get it wrong.

    Raw line breaks inside a string, which `strict=False` accepts; and a file's
    content wrapped in triple quotes, as a coding model wrote a `write_file`
    call: the call was lost, and it reported a function added that was never
    written. The inside of the quotes is taken as already escaped when that
    reads, and as plain text otherwise. Raises `json.JSONDecodeError` when
    neither helps.
    """
    try:
        return _windows_paths(json.loads(span))
    except json.JSONDecodeError as first:
        error = first
    try:
        return _windows_paths(json.loads(span, strict=False))
    except json.JSONDecodeError:
        pass
    # A Windows path written with single backslashes: "C:\Users\..." has \U,
    # which JSON has no escape for, and an architect's call was lost to it.
    if _BAD_ESCAPE.search(span):
        try:
            return _windows_paths(json.loads(_BAD_ESCAPE.sub(r"\\\\", span), strict=False))
        except json.JSONDecodeError:
            pass
    if '"""' in span:
        for as_written in (True, False):
            repaired = _TRIPLE_QUOTED.sub(
                lambda found: found[1] + (f'"{found[2]}"' if as_written
                                          else json.dumps(found[2])) + found[3], span)
            try:
                return json.loads(repaired, strict=False)
            except json.JSONDecodeError:
                continue
    raise error


#: A backslash that does not start one of JSON's escapes.
_BAD_ESCAPE = re.compile(r'(?<!\\)\\(?![\\"/bfnrtu])')
#: A Windows path, and the characters a single backslash in one was read as.
_WINDOWS_PATH = re.compile(r"\A[A-Za-z]:[\\/\r\t\x08\x0c\n]")
_READ_AS = {"\r": "\\r", "\t": "\\t", "\x08": "\\b", "\x0c": "\\f", "\n": "\\n"}


def _windows_paths(value):
    """\a value with the backslashes of Windows paths put back: in "C:\\Users\\rose4"
    written with single backslashes, "\\r" is read as a carriage return. A path
    never holds a control character, so one in a path is a backslash lost."""
    if isinstance(value, dict):
        return {key: _windows_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_windows_paths(item) for item in value]
    if isinstance(value, str) and _WINDOWS_PATH.match(value) and len(value) <= 400:
        return "".join(_READ_AS.get(char, char) for char in value)
    return value


def _meant(raw: dict, call: Call, known: frozenset[str]) -> bool:
    """Whether an untagged object is a call rather than data with a "name".

    Writing a test, an architect put `{"name": "canes", "price": 0.5}` in its
    code; it was taken for a call to a tool called "canes" and cut out of the
    code. With the agent's tools known, an object is a call when it names one
    of them, or says what its arguments are: a call to a tool that does not
    exist still reaches the registry, which says so.
    """
    if not known:
        return True
    return call.name in known or any(key in raw for key in ("arguments", "parameters"))


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
        taken = []
        for match in pattern.finditer(remainder):
            try:
                raw = _loads(match.group(1))
            except json.JSONDecodeError:
                continue
            call = _coerce(raw)
            # A tag is always meant as a call; a ```json block may be data.
            if call is not None and (pattern is _TOOL_CALL_TAG or _meant(raw, call, known)):
                calls.append(call)
                taken.append(match.group(0))
        if calls:
            for whole in taken:
                remainder = remainder.replace(whole, "")
            return calls, remainder.strip()

    # Nothing tagged or fenced. Accept a bare object only when it really looks
    # like a call, so ordinary prose containing JSON is not mistaken for one.
    for span in _balanced_objects(remainder):
        try:
            raw = _loads(span)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        if not ({"name", "tool", "function"} & set(raw)):
            continue
        call = _coerce(raw)
        if call is not None and _meant(raw, call, known):
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
            arguments = _loads(spans[0])
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
