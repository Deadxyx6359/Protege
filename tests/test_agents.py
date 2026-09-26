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

from akira.core.agents import Agent, AgentSpec, Kind, Trace, parse_calls, render_tools
from akira.core.agents.protocol import format_result
from akira.core.conversation import Cancelled
from akira.core.models import Route
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import (
    Parameter,
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    default_registry,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


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
                requires=(), pure=True, run=lambda a, c: ToolResult.success("ok"))
    text = render_tools([tool])
    assert "probe" in text and "path" in text and "required" in text


def test_a_result_is_labelled_with_its_status():
    from akira.core.agents.protocol import Call

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


def test_no_model_is_left_free_to_invent_a_web_address(context):
    """An address is the detail a model makes up without feeling unsure.

    The eleven characters that pick out a video carry nothing to reason from,
    so a model writes something of the right shape and the link goes nowhere.
    Every model Akira runs is told not to: the plain conversation, and each
    agent, whether or not it has a tool that could fetch a real one.
    """
    from akira.core.conversation import DEFAULT_SYSTEM_PROMPT, NO_INVENTED_ADDRESSES

    assert NO_INVENTED_ADDRESSES in DEFAULT_SYSTEM_PROMPT
    agent, _ = build_agent(["fine"], context())
    assert NO_INVENTED_ADDRESSES in agent.system_prompt()


def test_what_the_tools_kept_open_is_closed_when_the_work_ends(context):
    """A browser left open for the next step must not outlive the work it was for."""
    closed = []
    ctx = context()
    ctx.on_finish(lambda: closed.append("first"))
    ctx.on_finish(lambda: (_ for _ in ()).throw(RuntimeError("would not close")))
    ctx.on_finish(lambda: closed.append("last"))
    agent, _ = build_agent(["fine"], ctx)
    agent.run("go")
    assert closed == ["last", "first"], "something was left open, or one failure kept the rest"
    assert ctx.closers == []

    broken = context()
    broken.on_finish(lambda: closed.append("after a failure"))
    agent, _ = build_agent([], broken)
    agent.run("go")
    assert "after a failure" in closed, "work that failed left its browser open"


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
                           requires=(), pure=True, run=explode))

    agent, _ = build_agent([
        '<tool_call>{"name": "explode", "arguments": {}}</tool_call>',
        "I could not do that, so here is what I know instead.",
    ], context(), registry=registry)

    outcome = agent.run("try it")
    assert outcome.ok and outcome.stopped == "answered"
    assert outcome.steps == 2


# -- teams (A4) --------------------------------------------------------------


def two_member_team(**kwargs):
    from akira.core.agents import TeamSpec

    first = AgentSpec(name="first", role="You go first.", tools=(), max_steps=2)
    second = AgentSpec(name="second", role="You go second.", tools=(), max_steps=2)
    return TeamSpec(name="pair", purpose="test", members=(first, second), **kwargs)


def build_team(replies, context, spec=None, registry=None):
    from akira.core.agents import Team

    router = ScriptedRouter(replies)
    team = Team(spec or two_member_team(), router=router,
                registry=registry or default_registry(),
                context=context, trace=Trace())
    return team, router


def test_a_team_runs_its_members_in_order(context):
    team, _ = build_team(["from first", "from second"], context())
    outcome = team.run("do the thing")
    assert outcome.ok and outcome.stopped == "answered"
    assert list(outcome.contributions) == ["first", "second"]


def test_the_answer_is_the_last_contribution(context):
    team, _ = build_team(["from first", "from second"], context())
    assert team.run("go").answer == "from second"


def test_a_handoff_is_traceable(context):
    """The MESSAGE edge is what the interface draws between two agents."""
    team, _ = build_team(["from first", "from second"], context())
    outcome = team.run("go")

    assert [(h.sender, h.recipient) for h in outcome.handoffs] == [("first", "second")]
    messages = [e for e in team.trace.events(Kind.MESSAGE)]
    assert len(messages) == 1
    assert messages[0].agent == "first" and messages[0].to == "second"


def test_each_member_is_told_what_came_before(context):
    team, router = build_team(["gathered the facts", "and here is the answer"],
                              context())
    team.run("the original question")

    second_prompt = router.backend.prompts[-1]
    brief = next(m.content for m in second_prompt if m.role == "user")
    assert "the original question" in brief
    assert "gathered the facts" in brief
    assert "You are second" in brief


def test_a_member_that_fails_does_not_take_the_team_with_it(context):
    """A research answer missing its critic beats no answer."""
    class HalfBroken(ScriptedRouter):
        def __init__(self):
            super().__init__([])
            self.turn = 0

        @contextmanager
        def acquire(self, route):
            self.turn += 1
            if self.turn == 1:
                raise RuntimeError("the first one fell over")
            yield ScriptedBackend(["the second one managed"])

    from akira.core.agents import Team

    team = Team(two_member_team(), router=HalfBroken(),
                registry=default_registry(), context=context(), trace=Trace())
    outcome = team.run("go")

    assert outcome.answer == "the second one managed"
    assert [who for who, _ in outcome.failures] == ["first"]
    assert not outcome.ok, "the run finished, but not cleanly, and says so"


def test_a_later_member_is_told_the_step_was_lost(context):
    """Silently handing on less than expected makes a model invent the rest."""
    class FirstBroken(ScriptedRouter):
        def __init__(self):
            super().__init__([])
            self.turn = 0
            self.backend = ScriptedBackend(["second speaking"])

        @contextmanager
        def acquire(self, route):
            self.turn += 1
            if self.turn == 1:
                raise RuntimeError("down")
            yield self.backend

    from akira.core.agents import Team

    router = FirstBroken()
    team = Team(two_member_team(), router=router, registry=default_registry(),
                context=context(), trace=Trace())
    team.run("go")

    brief = next(m.content for m in router.backend.prompts[-1] if m.role == "user")
    assert "could not finish" in brief


def test_a_team_where_nobody_finishes_says_so(context):
    class AllBroken(ScriptedRouter):
        @contextmanager
        def acquire(self, route):
            raise RuntimeError("everything is down")
            yield  # pragma: no cover

    from akira.core.agents import Team

    team = Team(two_member_team(), router=AllBroken([]),
                registry=default_registry(), context=context(), trace=Trace())
    outcome = team.run("go")

    assert not outcome.ok and outcome.stopped == "failed"
    assert "Nobody" in outcome.answer


def test_a_member_cannot_exceed_the_teams_permissions(context, workspace):
    """Joining a team grants nothing. The team's policy is the ceiling."""
    from akira.core.agents import Team, TeamSpec

    greedy = AgentSpec(name="greedy", role="r",
                       tools=("read_file", "write_file"), max_steps=2)
    policy = Policy()
    policy.grant("files.read", (str(workspace),))   # read only, no write

    # The member tries to write anyway, as a jailbroken one would.
    target = str(workspace / "new.txt").replace("\\", "\\\\")
    team = Team(
        TeamSpec(name="t", purpose="p", members=(greedy,)),
        router=ScriptedRouter([
            '<tool_call>{"name": "write_file", "arguments": '
            '{"path": "%s", "content": "x"}}</tool_call>' % target,
            "I could not write it.",
        ]),
        registry=default_registry(), context=context(policy), trace=Trace())

    outcome = team.run("write a file")

    assert not (workspace / "new.txt").exists(), "the write must not have happened"
    result = [e for e in team.trace.events(Kind.TOOL_RESULT)]
    assert result and not result[0].ok


def test_cancelling_stops_the_team_between_members(context):
    team, _ = build_team(["first", "second"], context())
    outcome = team.run("go", is_cancelled=lambda: True)
    assert not outcome.ok and outcome.stopped == "cancelled"


def test_a_contribution_is_trimmed_before_the_next_member_sees_it(context):
    """Four members each passing on 6000 characters overflows an 8k context."""
    from akira.core.agents.team import MAX_CONTRIBUTION_CHARS

    team, router = build_team(["x" * 9000, "done"], context())
    team.run("go")

    brief = next(m.content for m in router.backend.prompts[-1] if m.role == "user")
    assert len(brief) < MAX_CONTRIBUTION_CHARS + 500


def test_the_shipped_teams_are_well_formed(context):
    from akira.core.agents import research_team, software_team

    for spec in (research_team(), software_team()):
        assert spec.members
        assert len({m.name for m in spec.members}) == len(spec.members)


def test_a_team_needs_members():
    from akira.core.agents import TeamSpec

    with pytest.raises(ValueError):
        TeamSpec(name="empty", purpose="p", members=())


def test_two_members_cannot_share_a_name():
    from akira.core.agents import TeamSpec

    twin = AgentSpec(name="same", role="r")
    with pytest.raises(ValueError):
        TeamSpec(name="t", purpose="p", members=(twin, twin))


def test_the_reviewer_cannot_write():
    """The role narrowing is the point, so it is asserted rather than trusted."""
    from akira.core.agents.roles import CRITIC, REVIEWER

    assert "write_file" not in REVIEWER.tools
    assert CRITIC.tools == ()


def test_a_backend_that_does_not_stream_still_produces_a_reply():
    """`generate` returns its text; streaming is an option on top of that.

    A batching backend, or a cloud model reached through `model.cloud`, can
    satisfy the contract without calling `on_token` once. Rebuilding the reply
    from the stream alone would end the run with a blank answer.
    """
    from dataclasses import dataclass

    @dataclass
    class Result:
        text: str

    class Silent:
        def generate(self, messages, **_):
            return Result(text="I did not stream this.")

    class SilentRouter:
        @contextmanager
        def acquire(self, route):
            yield Silent()

    policy = Policy()
    ctx = ToolContext(policy=policy, audit=AuditLog("nowhere/a.jsonl"),
                      secrets=SecretStore("nowhere/s"))
    agent = Agent(AgentSpec(name="a", role="r"), router=SilentRouter(),
                  registry=default_registry(), context=ctx, trace=Trace())

    outcome = agent.run("say something")
    assert outcome.ok
    assert outcome.answer == "I did not stream this."


def test_reasoning_is_filtered_out_of_a_non_streamed_reply():
    """The returned text has not been through the filter; the stream had."""
    from dataclasses import dataclass

    @dataclass
    class Result:
        text: str

    class Thinker:
        def generate(self, messages, **_):
            return Result(text="<think>hmm, let me see</think>The answer is 41.")

    class ThinkerRouter:
        @contextmanager
        def acquire(self, route):
            yield Thinker()

    ctx = ToolContext(policy=Policy(), audit=AuditLog("nowhere/a.jsonl"),
                      secrets=SecretStore("nowhere/s"))
    agent = Agent(AgentSpec(name="a", role="r"), router=ThinkerRouter(),
                  registry=default_registry(), context=ctx, trace=Trace())

    outcome = agent.run("go")
    assert "hmm, let me see" not in outcome.answer
    assert "The answer is 41." in outcome.answer


def test_the_reviewer_holds_nothing_irreversible():
    """Read-only by construction, not by the reviewer's good behaviour."""
    from akira.core.agents.roles import REVIEWER
    from akira.core.tools.builtin import MODULES

    tools = {tool.name: tool for module in MODULES for tool in module.ALL}
    for name in REVIEWER.tools:
        assert name in tools, f"the reviewer names a tool that does not exist: {name}"
        assert tools[name].reversible, f"the reviewer can do something irreversible: {name}"


# -- a grounded agent reads before it answers ----------------------------------


def test_a_grounded_agent_that_answers_unread_is_told_to_read_first(workspace, context):
    from akira.core.agents.loop import READ_FIRST

    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    call = ('<tool_call>{"name": "read_file", "arguments": {"path": "%s"}}</tool_call>'
            % (workspace / "notes.md").as_posix())
    agent, router = build_agent(["The answer is 12.", call, "The answer is 41."],
                                context(policy), grounded=True, tools=("read_file",))
    outcome = agent.run("What is the answer?")
    assert outcome.answer == "The answer is 41."
    assert [c.name for c in outcome.calls] == ["read_file"]
    assert any(m.content == READ_FIRST for m in router.backend.prompts[1])


def test_an_agent_not_grounded_may_answer_from_its_brief(workspace, context):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    agent, _ = build_agent(["From the brief: 41."], context(policy), tools=("read_file",))
    assert agent.run("The brief says 41. What is it?").answer == "From the brief: 41."


def test_a_grounded_agent_with_nothing_to_read_with_is_not_told_to(context):
    agent, _ = build_agent(["It is 4."], context(Policy()), grounded=True,
                           tools=("read_file", "calculate"))
    assert agent.run("What is 2 + 2?").answer == "It is 4."


def test_an_agent_is_told_the_folders_its_file_tools_may_reach(workspace, context):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    reader, _ = build_agent([], context(policy), tools=("read_file",))
    assert f"Folders you can read (start by searching these): {workspace}" in reader.system_prompt()
    # Not the folders of a permission its own tools do not use.
    helper, _ = build_agent([], context(policy), tools=("calculate",))
    assert "Folders you can" not in helper.system_prompt()
