"""The tool gate: what an agent is shown, and what happens when it calls.

The property this file exists to pin down is that permission is enforced
*structurally*. An agent without a grant is not told the tool exists, so the
question "could a clever prompt talk it into writing a file" does not arise —
there is no tool in its schema to talk it into using.
"""

from __future__ import annotations

import pytest

from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import (
    Parameter,
    Requirement,
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    ToolResult,
    default_registry,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "work"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text(
        "def main():\n    # TODO tidy this\n    return 1\n", encoding="utf-8")
    (root / "notes.md").write_text("# Notes\nsomething\n", encoding="utf-8")
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
        )
    return build


# -- what an agent is shown -------------------------------------------------


def test_no_grants_means_no_tool_that_touches_anything(context):
    # Only pure computation is offered without a grant: arithmetic, which reads
    # and reaches nothing.
    offered = default_registry().available(Policy())
    assert [t.name for t in offered] == ["calculate"]
    assert all(t.pure and not t.requires and t.reversible for t in offered)


def test_a_tool_needing_nothing_must_be_pure():
    from akira.core.tools import Tool, ToolRegistry, ToolResult

    loose = Tool(name="loose", summary="x", parameters=(), requires=(),
                 run=lambda a, c: ToolResult.success("x"))
    with pytest.raises(ValueError, match="must be pure"):
        ToolRegistry().register(loose)


def test_a_tool_is_hidden_until_every_capability_it_needs_is_granted(workspace):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    names = [t.name for t in default_registry().available(policy)]
    assert "read_file" in names
    assert "write_file" not in names


def test_the_schema_handed_to_the_model_is_filtered_too(workspace):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    names = {s["function"]["name"] for s in default_registry().schemas(policy)}
    assert "write_file" not in names


def test_an_agent_can_be_narrowed_below_its_permissions(workspace):
    """A reviewer that cannot write is a better reviewer."""
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    policy.grant("files.write", (str(workspace),))
    registry = default_registry()
    narrowed = registry.available(policy, only=("read_file",))
    assert [t.name for t in narrowed] == ["read_file"]


def test_missing_capabilities_can_be_named_for_the_prompt(workspace):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    assert default_registry().missing_for("write_file", policy) == ["files.write"]


# -- what happens on a call -------------------------------------------------


def test_scope_is_checked_at_call_time_not_only_at_list_time(workspace, tmp_path, context):
    """Being offered `read_file` says it may read *somewhere*."""
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("private", encoding="utf-8")

    result = default_registry().invoke(
        "read_file", {"path": str(elsewhere)}, context(policy))
    assert not result.ok and "Not permitted" in result.content


def test_a_permitted_read_returns_the_file_with_line_numbers(workspace, context):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    result = default_registry().invoke(
        "read_file", {"path": str(workspace / "notes.md")}, context(policy))
    assert result.ok and "1  # Notes" in result.content


def test_binary_files_are_refused_rather_than_returned_as_mojibake(workspace, context):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    blob = workspace / "image.png"
    blob.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
    result = default_registry().invoke(
        "read_file", {"path": str(blob)}, context(policy))
    assert not result.ok and "binary" in result.content.lower()


def test_a_very_large_file_is_truncated_not_returned_whole(workspace, context):
    """Returning 40 MB to a model destroys the conversation it was helping."""
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    big = workspace / "big.txt"
    big.write_text("line\n" * 200_000, encoding="utf-8")
    result = default_registry().invoke(
        "read_file", {"path": str(big)}, context(policy))
    assert result.ok and "truncated" in result.content
    # Well under the 1.2 MB original. Line numbering adds a prefix per line, so
    # the ceiling sits above the 200 KB read cap rather than at it.
    assert len(result.content) < 600_000


def test_search_finds_matches_with_their_locations(workspace, context):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    result = default_registry().invoke(
        "search_files", {"path": str(workspace), "text": "TODO"}, context(policy))
    assert result.ok and "main.py:2" in result.content


# -- irreversible actions ---------------------------------------------------


def test_writing_asks_even_when_the_capability_is_granted(workspace, context):
    """A grant says the agent *may try*, never "and need not ask"."""
    policy = Policy()
    policy.grant("files.write", (str(workspace),))
    asked = []
    ctx = context(policy, confirm=lambda summary: asked.append(summary) or False)

    result = default_registry().invoke(
        "write_file", {"path": str(workspace / "new.txt"), "content": "x"}, ctx)

    assert not result.ok
    assert not (workspace / "new.txt").exists()
    assert asked and "Create a new file" in asked[0] and "new.txt" in asked[0]


def test_the_confirmation_prompt_states_the_actual_values(workspace, context):
    """"Run a tool?" is not a question anybody can answer."""
    policy = Policy()
    policy.grant("files.write", (str(workspace),))
    asked = []
    ctx = context(policy, confirm=lambda s: asked.append(s) or False)
    default_registry().invoke(
        "write_file", {"path": str(workspace / "x.txt"), "content": "y"}, ctx)
    assert "x.txt" in asked[0]


def test_approving_lets_it_through(workspace, context):
    policy = Policy()
    policy.grant("files.write", (str(workspace),))
    ctx = context(policy, confirm=lambda summary: True)
    result = default_registry().invoke(
        "write_file", {"path": str(workspace / "new.txt"), "content": "hello"}, ctx)
    assert result.ok
    assert (workspace / "new.txt").read_text(encoding="utf-8") == "hello"


def test_a_context_with_no_way_to_ask_cannot_approve(workspace):
    """The default must be no, or a headless run silently gains consent."""
    policy = Policy()
    policy.grant("files.write", (str(workspace),))
    bare = ToolContext(policy=policy, audit=AuditLog(workspace / "a.jsonl"),
                       secrets=SecretStore(workspace / "s"))
    result = default_registry().invoke(
        "write_file", {"path": str(workspace / "n.txt"), "content": "x"}, bare)
    assert not result.ok
    assert not (workspace / "n.txt").exists()


def test_a_confirmation_prompt_that_raises_counts_as_no(workspace, context):
    def broken(summary):
        raise RuntimeError("the dialog blew up")

    policy = Policy()
    policy.grant("files.write", (str(workspace),))
    result = default_registry().invoke(
        "write_file", {"path": str(workspace / "n.txt"), "content": "x"},
        context(policy, confirm=broken))
    assert not result.ok


# -- arguments from an untrusted source -------------------------------------


def test_a_missing_required_argument_is_refused(context):
    result = default_registry().invoke("read_file", {}, context())
    assert not result.ok and "missing required argument" in result.content


def test_a_wrongly_typed_argument_is_refused(workspace, context):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    result = default_registry().invoke("read_file", {"path": 42}, context(policy))
    assert not result.ok and "must be a string" in result.content


def test_a_boolean_is_not_accepted_where_a_number_belongs():
    tool = Tool(
        name="t", summary="s",
        parameters=(Parameter("count", "integer", "how many"),),
        requires=(), pure=True, run=lambda a, c: ToolResult.success("ok"))
    with pytest.raises(ToolError):
        tool.validate({"count": True})


def test_a_numeric_string_is_accepted_where_a_number_belongs():
    tool = Tool(
        name="t", summary="s",
        parameters=(Parameter("count", "integer", "how many"),),
        requires=(), pure=True, run=lambda a, c: ToolResult.success("ok"))
    assert tool.validate({"count": "7"}) == {"count": 7}


def test_undeclared_arguments_are_dropped_rather_than_passed_through():
    """Models invent a plausible extra field; nothing undeclared reaches a tool."""
    tool = Tool(
        name="t", summary="s",
        parameters=(Parameter("path", "string", "where"),),
        requires=(), pure=True, run=lambda a, c: ToolResult.success("ok"))
    assert tool.validate({"path": "/a", "recursive": True}) == {"path": "/a"}


def test_an_enum_argument_rejects_anything_else():
    tool = Tool(
        name="t", summary="s",
        parameters=(Parameter("mode", "string", "how", enum=("fast", "slow")),),
        requires=(), pure=True, run=lambda a, c: ToolResult.success("ok"))
    with pytest.raises(ToolError):
        tool.validate({"mode": "sideways"})


# -- failure containment ----------------------------------------------------


def test_calling_a_tool_that_does_not_exist_is_reported_not_raised(context):
    result = default_registry().invoke("summon_daemon", {}, context())
    assert not result.ok and "no tool named" in result.content.lower()


def test_a_tool_that_raises_does_not_take_the_agent_with_it(context):
    def explode(arguments, ctx):
        raise ZeroDivisionError("boom")

    registry = ToolRegistry()
    registry.register(Tool(name="explode", summary="s", parameters=(),
                           requires=(), pure=True, run=explode))
    result = registry.invoke("explode", {}, context())
    assert not result.ok and "ZeroDivisionError" in result.content


def test_a_tool_cannot_be_registered_for_a_capability_nobody_declared():
    with pytest.raises(KeyError):
        ToolRegistry().register(Tool(
            name="t", summary="s", parameters=(),
            requires=(Requirement("nonsense.power"),),
            run=lambda a, c: ToolResult.success("ok")))


def test_a_scoped_capability_must_say_which_argument_carries_its_scope():
    """Otherwise the scope on the grant would be decorative."""
    with pytest.raises(ValueError):
        Requirement("files.read")


def test_registering_the_same_name_twice_is_refused():
    registry = ToolRegistry()
    tool = Tool(name="t", summary="s", parameters=(), requires=(), pure=True,
                run=lambda a, c: ToolResult.success("ok"))
    registry.register(tool)
    with pytest.raises(ValueError):
        registry.register(tool)


# -- the record -------------------------------------------------------------


def test_every_call_is_audited_including_refusals(workspace, context):
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    ctx = context(policy)
    registry = default_registry()
    registry.invoke("read_file", {"path": str(workspace / "notes.md")}, ctx)
    registry.invoke("read_file", {"path": "C:/Windows/win.ini"}, ctx)

    events = ctx.audit.read()
    assert [e.allowed for e in events] == [True, False]
    assert all(e.action == "read_file" for e in events)


def test_a_permitted_call_records_where_it_was_used(workspace, context):
    """The security review suggests narrowing a grant from exactly this."""
    policy = Policy()
    policy.grant("files.read", (str(workspace),))
    ctx = context(policy)
    default_registry().invoke("read_file", {"path": str(workspace / "notes.md")}, ctx)
    event = ctx.audit.read()[-1]
    assert event.allowed and "notes.md" in event.detail.get("scope", "")
