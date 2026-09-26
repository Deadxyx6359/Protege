"""What trying Akira with its real models showed about agents, pinned down.

A coding model writes a tool call as Python; a small model given the example
`{"argument": "value"}` copies "argument"; an agent that can act answers in
words. Each is handled here, and each is tested.
"""

from __future__ import annotations

from akira.core.agents.protocol import parse_calls, render_tools
from akira.core.tools import default_registry


KNOWN = frozenset({"write_file", "read_file"})


def test_a_call_written_as_python_is_understood_for_a_tool_the_agent_has():
    text = ('Here it is.\n```python\nwrite_file(\n    path=r"C:\\notes\\shopping.md",\n'
            '    content="# List\\n\\n- [ ] eggs (and flour)\\n"\n)\n```\nDone.')
    [call], prose = parse_calls(text, KNOWN)
    assert call.name == "write_file"
    assert call.arguments == {"path": "C:\\notes\\shopping.md",
                              "content": "# List\n\n- [ ] eggs (and flour)\n"}
    assert "write_file" not in prose and prose.startswith("Here it is.")


def test_python_that_is_not_one_of_its_tools_or_not_literal_is_left_alone():
    assert parse_calls("print(len(x))", KNOWN)[0] == []
    assert parse_calls('write_file(path=open("x"), content="y")', KNOWN)[0] == []
    assert parse_calls('write_file("positional.md", "content")', KNOWN)[0] == []
    # Without the agent's tool names, nothing Python-shaped is a call.
    assert parse_calls('write_file(path="a.md", content="b")')[0] == []


def test_a_tool_name_followed_by_its_arguments_is_understood():
    text = ('Let me save it.\n\nsave_drawing {"path": "C:\\\\art\\\\logo.svg", '
            '"svg": "<svg viewBox=\\"0 0 1 1\\"/>"}')
    [call], prose = parse_calls(text, frozenset({"save_drawing"}))
    assert call.name == "save_drawing"
    assert call.arguments == {"path": "C:\\art\\logo.svg", "svg": '<svg viewBox="0 0 1 1"/>'}
    assert prose == "Let me save it."
    assert parse_calls('unknown_tool {"a": 1}', frozenset({"save_drawing"}))[0] == []


def test_the_tagged_form_still_wins():
    text = '<tool_call>{"name": "read_file", "arguments": {"path": "a.md"}}</tool_call>'
    [call], _ = parse_calls(text, KNOWN)
    assert call.name == "read_file" and call.arguments == {"path": "a.md"}


def test_the_example_call_uses_a_real_tool_and_its_real_argument_names():
    tools = [default_registry().get("list_directory"), default_registry().get("read_file")]
    rendered = render_tools(tools)
    assert '{"name": "list_directory", "arguments": {"path": "..."}}' in rendered
    assert '"argument"' not in rendered
