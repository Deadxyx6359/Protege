"""The agent loop, the tool-call protocol, and the trace.

These three sit under everything else in the platform, so what is pinned down
here is mostly about *containment*: that the loop always terminates, that a
refusal ends a run instead of starting a retry spiral, that a broken listener
cannot take an agent down with it, and that the parser survives the shapes a
local model actually emits rather than only the one it was asked for.

The model is scripted throughout. A test that depended on what a 4-bit Qwen
felt like saying that afternoon would not be a test.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from protege.core.agents import Agent, AgentSpec, Kind, Trace, parse_calls, render_tools
from protege.core.agents.protocol import format_result
from protege.core.conversation import Cancelled
from protege.core.models import Route
from protege.core.permissions import AuditLog, Policy, SecretStore
from protege.core.tools import (
    Parameter,
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    default_registry,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


# -- a model that says exactly what the test needs ---------------------------


class ScriptedBackend:
    """Replays a fixed list of replies, one per turn."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.prompts: list[list] = []

    def generate(self, messages, *, max_tokens=None, temperature=None,
                 on_token=None, **_) -> str:
        self.prompts.append(list(messages))
        reply = self._replies.pop(0) if self._replies else "done"
        if on_token is not None:
            # Stream it in pieces; the loop reassembles, and chunking is where
            # a think-filter bug would show up.
            for index in range(0, len(reply), 7):
                on_token(reply[index:index + 7])
        return reply


class ScriptedRouter:
    def __init__(self, replies: list[str]) -> None:
        self.backend = ScriptedBackend(replies)
        self.routes: list[Route] = []

    @contextmanager
    def acquire(self, route: Route):
        self.routes.append(route)
        yield self.backend


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / "notes.md").write_text("# Notes\nthe answer is 41\n", encoding="utf-8")
    return root


@pytest.fixture
def context(workspace):
    def build(policy=None, confirm=None):
        return ToolContext(
            policy=policy if policy is not None else Policy(),
            audit=AuditLog(workspace / "audit.jsonl"),
            secrets=SecretStore(workspace / "secrets"),
            actor="tester",
            confirm=confirm if confirm is not None else (lambda summary: False),
            workspace=str(workspace),
        )
    return build


def build_agent(replies, context, *, registry=None, **spec_kwargs):
    router = ScriptedRouter(replies)
    spec = AgentSpec(name="tester", role="You are a test agent.", **spec_kwargs)
    agent = Agent(spec, router=router, registry=registry or default_registry(),
                  context=context, trace=Trace())
    return agent, router


# -- the protocol: shapes a model actually emits -----------------------------


def test_the_house_style_is_parsed():
    calls, prose = parse_calls(
        'Let me look.<tool_call>{"name": "read_file", '
        '"arguments": {"path": "/a.txt"}}</tool_call>')
    assert [c.name for c in calls] == ["read_file"]
    assert calls[0].arguments == {"path": "/a.txt"}
    assert "tool_call" not in prose


def test_a_fenced_block_is_parsed_too():
    """Models trained on generic function calling reach for this."""
    calls, _ = parse_calls('```json\n{"name": "list_directory", '
                           '"arguments": {"path": "/x"}}\n```')
    assert [c.name for c in calls] == ["list_directory"]


def test_a_bare_object_is_parsed_when_it_looks_like_a_call():
    calls, _ = parse_calls('{"name": "read_file", "arguments": {"path": "/a"}}')
    assert [c.name for c in calls] == ["read_file"]


def test_prose_containing_json_is_not_mistaken_for_a_call():
    """Otherwise explaining a config file becomes a tool invocation."""
    calls, prose = parse_calls(
        'Your settings look like {"theme": "dark", "size": 12} which is fine.')
    assert calls == []
    assert "theme" in prose


def test_braces_inside_string_arguments_do_not_break_the_scan():
    """Writing code through write_file is the common case, and code has braces."""
    body = "def f() {\\n  return {\\\"a\\\": 1};\\n}"
    calls, _ = parse_calls(
        '{"name": "write_file", "arguments": {"path": "/a.js", "content": "%s"}}' % body)
    assert [c.name for c in calls] == ["write_file"]
    assert "return" in calls[0].arguments["content"]


def test_the_nested_function_shape_is_accepted():
    calls, _ = parse_calls(
        '<tool_call>{"function": {"name": "read_file", '
        '"arguments": {"path": "/a"}}}</tool_call>')
    assert [c.name for c in calls] == ["read_file"]


def test_arguments_arriving_as_a_json_string_are_decoded():
    calls, _ = parse_calls(
        '<tool_call>{"name": "read_file", "arguments": "{\\"path\\": \\"/a\\"}"}'
        '</tool_call>')
    assert calls[0].arguments == {"path": "/a"}


def test_a_call_with_no_name_is_not_a_call():
    calls, _ = parse_calls('<tool_call>{"arguments": {"path": "/a"}}</tool_call>')
    assert calls == []


def test_malformed_json_is_ignored_rather_than_raising():
    calls, _ = parse_calls('<tool_call>{"name": "read_file", oops}</tool_call>')
    assert calls == []


def test_having_no_tools_is_stated_plainly_in_the_prompt():
    """A model that is not told it has nothing will invent a call anyway."""
    text = render_tools([])
    assert "no tools" in text.lower()


def test_rendered_tools_name_their_arguments():
    tool = Tool(name="probe", summary="Look at a thing.",
                parameters=(Parameter("path", "string", "Where to look."),),
                requires=(), run=lambda a, c: ToolResult.success("ok"))
    text = render_tools([tool])
    assert "probe" in text and "path" in text and "required" in text


def test_a_result_is_labelled_with_its_status():
    from protege.core.agents.protocol import Call

    ok = format_result(Call("read_file"), "contents", ok=True)
    bad = format_result(Call("read_file"), "boom", ok=False)
    assert 'status="result"' in ok and 'status="error"' in bad


# -- the trace ---------------------------------------------------------------


def test_events_reach_a_listener_and_stop_when_it_unsubscribes():
    trace = Trace()
    seen = []
    stop = trace.listen(seen.append)
    trace.emit(Kind.NOTE, "a", text="one")
    stop()
    trace.emit(Kind.NOTE, "a", text="two")
    assert [e.text for e in seen] == ["one"]


def test_a_listener_that_raises_does_not_stop_the_run():
    """A broken view must never be able to kill an agent mid-task."""
    trace = Trace()
    good = []

    def explode(event):
        raise RuntimeError("the view blew up")

    trace.listen(explode)
    trace.listen(good.append)
    trace.emit(Kind.NOTE, "a", text="still delivered")
    assert [e.text for e in good] == ["still delivered"]


def test_replay_lets_a_view_attach_late():
    trace = Trace()
    trace.emit(Kind.STARTED, "a", text="before the window opened")
    assert [e.text for e in trace.replay()] == ["before the window opened"]


def test_events_can_be_filtered_by_kind():
    trace = Trace()
    trace.emit(Kind.NOTE, "a")
    trace.emit(Kind.ANSWER, "a", text="final")
    assert [e.text for e in trace.events(Kind.ANSWER)] == ["final"]


def test_an_event_serialises_for_the_interface():
    trace = Trace()
    event = trace.emit(Kind.TOOL_CALL, "a", tool="read_file",
                       arguments={"path": "/a"}, step=2)
    blob = event.to_json()
    assert blob["kind"] == "tool_call" and blob["tool"] == "read_file"
    assert blob["step"] == 2


# -- the loop ----------------------------------------------------------------


def test_an_answer_with_no_tool_call_ends_the_run(context):
    agent, _ = build_agent(["The answer is 41."], context())
    outcome = agent.run("what is the answer?")
    assert outcome.ok and outcome.stopped == "answered"
    assert outcome.answer == "The answer is 41."
    assert outcome.steps == 1


def test_a_tool_call_is_run_and_its_result_comes_back(context, workspace):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    agent, _ = build_agent([
        '<tool_call>{"name": "read_file", "arguments": {"path": "%s"}}</tool_call>'
        % str(workspace / "notes.md").replace("\\", "\\\\"),
        "The answer is 41.",
    ], context(policy))

    outcome = agent.run("read the notes")
    assert outcome.ok
    assert [c.name for c in outcome.calls] == ["read_file"]
    assert outcome.answer == "The answer is 41."
    kinds = [e.kind for e in agent.trace.events()]
    assert Kind.TOOL_CALL in kinds and Kind.TOOL_RESULT in kinds


def test_only_the_first_call_of_a_step_is_honoured(context, workspace):
    """Models emit several at once having guessed results they have not seen."""
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    path = str(workspace / "notes.md").replace("\\", "\\\\")
    agent, _ = build_agent([
        '<tool_call>{"name": "read_file", "arguments": {"path": "%s"}}</tool_call>'
        '<tool_call>{"name": "list_directory", "arguments": {"path": "%s"}}</tool_call>'
        % (path, str(workspace).replace("\\", "\\\\")),
        "Done.",
    ], context(policy))

    outcome = agent.run("look around")
    assert [c.name for c in outcome.calls] == ["read_file"]


def test_a_refusal_ends_the_run_instead_of_starting_a_retry_spiral(context, tmp_path):
    """A local model told "no" will otherwise rephrase until the budget dies."""
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("private", encoding="utf-8")
    policy = Policy()
    policy.grant("files.read", (str(tmp_path / "work"),))

    agent, router = build_agent([
        '<tool_call>{"name": "read_file", "arguments": {"path": "%s"}}</tool_call>'
        % str(outside).replace("\\", "\\\\"),
    ] * 6, context(policy))

    outcome = agent.run("read that file")
    assert not outcome.ok
    assert "Not permitted" in outcome.answer
    assert outcome.steps == 1, "it should not have asked the model a second time"


def test_running_out_of_steps_is_an_outcome_not_a_hang(context, workspace):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    path = str(workspace / "notes.md").replace("\\", "\\\\")
    call = ('<tool_call>{"name": "read_file", "arguments": {"path": "%s"}}'
            '</tool_call>' % path)

    agent, _ = build_agent([call] * 10, context(policy), max_steps=3)
    outcome = agent.run("loop forever")

    assert not outcome.ok and outcome.stopped == "budget"
    assert outcome.steps == 3
    assert "3" in outcome.answer


def test_a_model_that_raises_is_reported_not_propagated(context):
    class Exploding(ScriptedRouter):
        @contextmanager
        def acquire(self, route):
            raise RuntimeError("the GPU fell over")
            yield  # pragma: no cover

    spec = AgentSpec(name="tester", role="r")
    agent = Agent(spec, router=Exploding([]), registry=default_registry(),
                  context=context(), trace=Trace())

    outcome = agent.run("do something")
    assert not outcome.ok and outcome.stopped == "failed"
    assert "the GPU fell over" in outcome.answer


def test_cancellation_stops_the_run_cleanly(context):
    agent, _ = build_agent(["a reply long enough to stream in pieces"], context())
    outcome = agent.run("go", is_cancelled=lambda: True)
    assert not outcome.ok and outcome.stopped == "cancelled"


def test_an_ungranted_tool_never_appears_in_the_system_prompt(context, workspace):
    """The structural guarantee, seen from the model's side of the wire."""
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    agent, _ = build_agent(["fine"], context(policy))

    prompt = agent.system_prompt()
    assert "read_file" in prompt
    assert "write_file" not in prompt


def test_the_workspace_is_stated_in_the_prompt(context, workspace):
    agent, _ = build_agent(["fine"], context())
    assert str(workspace) in agent.system_prompt()


def test_the_agent_asks_the_router_for_its_declared_route(context):
    agent, router = build_agent(["fine"], context(), route=Route.CODE)
    agent.run("go")
    assert router.routes == [Route.CODE]


def test_a_narrowed_agent_cannot_reach_a_tool_it_holds_permission_for(
        context, workspace):
    """A reviewer that cannot write is a better reviewer."""
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    policy.grant("files.write", (str(workspace),))
    agent, _ = build_agent(["fine"], context(policy), tools=("read_file",))
    assert "write_file" not in agent.system_prompt()


def test_a_tool_failure_does_not_end_the_run(context, workspace):
    """A tool that breaks is information, not a reason to stop working."""
    def explode(arguments, ctx):
        raise ZeroDivisionError("boom")

    registry = ToolRegistry()
    registry.register(Tool(name="explode", summary="Break.", parameters=(),
                           requires=(), run=explode))

    agent, _ = build_agent([
        '<tool_call>{"name": "explode", "arguments": {}}</tool_call>',
        "I could not do that, so here is what I know instead.",
    ], context(), registry=registry)

    outcome = agent.run("try it")
    assert outcome.ok and outcome.stopped == "answered"
    assert outcome.steps == 2
