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


def test_data_with_a_name_in_code_is_not_a_call():
    """An architect's test data, `{"name": "canes", ...}`, was run as a tool called "canes"."""
    text = ('Here is the test:\n```python\n'
            'items = [{"name": "canes", "price": 0.5, "quantity": 20}]\n```')
    assert parse_calls(text, KNOWN) == ([], text)
    fenced = '```json\n{"name": "canes", "price": 1}\n```'
    assert parse_calls(fenced, KNOWN) == ([], fenced)
    # A misnamed call still reaches the registry, which says there is no such tool.
    [call], _ = parse_calls('{"name": "reed_file", "arguments": {"path": "a"}}', KNOWN)
    assert call.name == "reed_file"


def test_a_file_written_in_triple_quotes_or_with_raw_line_breaks_is_still_written():
    """A coding model's write_file was lost this way, and it said the function was added."""
    escaped = ('```python\n{"name": "write_file", "arguments": {"path": "a.py", "content": '
               '"""\\"\\"\\"Doc.\\"\\"\\"\\n\\ndef f():\\n    return {\\"a\\": 1}\\n"""}}\n```')
    [call], _ = parse_calls(escaped, KNOWN | {"write_file"})
    assert call.arguments["content"] == '"""Doc."""\n\ndef f():\n    return {"a": 1}\n'
    plain = ('{"name": "write_file", "arguments": {"path": "a.py", "content": """def f():\n'
             '    return "x"\n"""}}')
    [call], _ = parse_calls(plain, KNOWN | {"write_file"})
    assert call.arguments["content"] == 'def f():\n    return "x"\n'
    raw_lines = '{"name": "write_file", "arguments": {"path": "a.py", "content": "a\nb"}}'
    [call], _ = parse_calls(raw_lines, KNOWN | {"write_file"})
    assert call.arguments["content"] == "a\nb"


def test_the_example_call_uses_a_real_tool_and_its_real_argument_names():
    tools = [default_registry().get("list_directory"), default_registry().get("read_file")]
    rendered = render_tools(tools)
    assert '{"name": "list_directory", "arguments": {"path": "..."}}' in rendered
    assert '"argument"' not in rendered



def test_a_windows_path_with_single_backslashes_is_still_a_call():
    from akira.core.agents.protocol import parse_calls

    written = ('<tool_call>{"name": "list_directory", "arguments": {"path": '
               '"C:\\Users\\rose4\\STM32Cube\\Repository\\STM32Cube_FW_G4_V1.6.3"}}</tool_call>')
    assert "\\U" in written and "\\\\" not in written
    calls, _ = parse_calls(written, frozenset({"list_directory"}))
    assert [c.arguments["path"] for c in calls] == [
        "C:\\Users\\rose4\\STM32Cube\\Repository\\STM32Cube_FW_G4_V1.6.3"]


def test_a_path_whose_backslashes_read_as_escapes_gets_them_back():
    from akira.core.agents.protocol import parse_calls

    # Valid JSON, but \r and \n are read as a carriage return and a line break.
    written = '{"name": "read_file", "arguments": {"path": "C:\\rose\\new\\main.c"}}'
    calls, _ = parse_calls(written, frozenset({"read_file"}))
    assert calls[0].arguments["path"] == "C:\\rose\\new\\main.c"


def test_file_contents_keep_their_line_breaks():
    from akira.core.agents.protocol import parse_calls

    written = ('{"name": "write_file", "arguments": {"path": "C:\\\\p\\\\a.c", '
               '"content": "int a;\\nint b;\\n"}}')
    calls, _ = parse_calls(written, frozenset({"write_file"}))
    assert calls[0].arguments == {"path": "C:\\p\\a.c", "content": "int a;\nint b;\n"}


def test_a_step_writes_what_it_was_given_or_what_the_context_has_left():
    from akira.core.agents.loop import MIN_TO_WRITE, room_to_write
    from akira.models.base import ChatMessage

    class Backend:
        n_ctx = 8192

        def count_tokens(self, text):
            return len(text) // 4

    small = [ChatMessage(role="system", content="x" * 4000)]
    assert room_to_write(Backend(), small, 3072) == 3072
    full = [ChatMessage(role="system", content="x" * 26000)]
    assert room_to_write(Backend(), full, 3072) == 8192 - (6500 + 4) - 96
    overfull = [ChatMessage(role="system", content="x" * 40000)]
    assert room_to_write(Backend(), overfull, 3072) == MIN_TO_WRITE

    class Uncounted:
        n_ctx = 8192

    assert room_to_write(Uncounted(), small, 1024) == 1024


def test_the_implementer_may_write_a_whole_file_in_one_step():
    from akira.core.agents.roles import IMPLEMENTER

    assert IMPLEMENTER.max_tokens >= 3000 and IMPLEMENTER.max_steps >= 16
    assert {"edit_file", "build_project"} <= set(IMPLEMENTER.tools)


def test_a_long_run_cuts_its_oldest_results_to_keep_room_to_write():
    from akira.core.agents.loop import SHORTENED, fit, room_to_write
    from akira.models.base import ChatMessage

    class Backend:
        n_ctx = 8192

        def count_tokens(self, text):
            return len(text) // 4

    messages = [ChatMessage(role="system", content="s" * 4000),
                ChatMessage(role="user", content="the task " * 100),
                *[ChatMessage(role="user" if n % 2 else "assistant", content=str(n) * 6000)
                  for n in range(6)],
                ChatMessage(role="assistant", content="call build_project"),
                ChatMessage(role="user", content="error: unterminated #ifndef " * 50)]
    fit(Backend(), messages, 3072)
    assert room_to_write(Backend(), messages, 3072) == 3072
    assert messages[0].content == "s" * 4000 and messages[1].content.startswith("the task")
    assert messages[-1].content.startswith("error: unterminated") and SHORTENED not in \
        messages[-1].content, "the latest exchange is whole"
    assert messages[2].content.endswith(SHORTENED), "the oldest result is cut first"
    assert not messages[7].content.endswith(SHORTENED), "only as many as needed"


def test_an_answer_that_only_says_it_is_coming_is_not_the_answer():
    from akira.core.agents.loop import _ANNOUNCES

    for said in ("I have finished my plan and will now provide the answer.",
                 "Here is the plan:", "I will now write the file."):
        assert _ANNOUNCES.search(said), said
    for said in ("Here is the plan: write the header, then the driver.",
                 "The driver sends 0x01, then the line address.",
                 "Let me know if you want more."):
        assert not _ANNOUNCES.search(said), said
