"""Asking only where the answer matters: new files, and the same run again."""

from __future__ import annotations

import pytest

from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import default_registry
from akira.core.tools.builtin.files import write_file
from akira.core.tools.registry import CONFIRMED, REPEAT_NOTE, ToolRegistry
from akira.core.tools.schema import Parameter, Requirement, Tool, ToolContext, ToolError, ToolResult


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


class Confirm:
    def __init__(self, answer=True):
        self.answer = answer
        self.asked = []

    def __call__(self, summary):
        self.asked.append(str(summary))
        return self.answer


def context_for(tmp_path, confirm, *capabilities, attended=True):
    policy = Policy()
    for capability in capabilities:
        policy.grant(capability, (str(tmp_path),))
    return ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"), confirm=confirm,
                       attended=attended)


def test_a_new_text_file_is_saved_without_asking(tmp_path):
    confirm = Confirm()
    context = context_for(tmp_path, confirm, "files.write")
    target = tmp_path / "notes" / "plan.md"
    result = default_registry().invoke("write_file", {"path": str(target), "content": "# Plan"},
                                       context)
    assert result.ok and confirm.asked == []
    assert target.read_text(encoding="utf-8") == "# Plan"


def test_unattended_work_still_asks_even_for_a_new_file(tmp_path):
    confirm = Confirm(answer=False)
    target = tmp_path / "plan.md"
    result = default_registry().invoke("write_file", {"path": str(target), "content": "x"},
                                       context_for(tmp_path, confirm, "files.write",
                                                   attended=False))
    assert not result.ok and len(confirm.asked) == 1 and not target.exists()


def test_replacing_a_file_still_asks(tmp_path):
    target = tmp_path / "plan.md"
    target.write_text("keep me", encoding="utf-8")
    confirm = Confirm(answer=False)
    result = default_registry().invoke("write_file", {"path": str(target), "content": "gone"},
                                       context_for(tmp_path, confirm, "files.write"))
    assert not result.ok and len(confirm.asked) == 1 and "Replace the file" in confirm.asked[0]
    assert target.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize("name", ["tool.py", "run.ps1", "pyproject.toml", "setup.bat", "Makefile"])
def test_a_new_file_that_could_be_run_still_asks(tmp_path, name):
    confirm = Confirm(answer=False)
    result = default_registry().invoke("write_file", {"path": str(tmp_path / name), "content": "x"},
                                       context_for(tmp_path, confirm, "files.write"))
    assert not result.ok and len(confirm.asked) == 1
    assert not (tmp_path / name).exists()


def test_a_file_that_appeared_meanwhile_is_not_replaced_unasked(tmp_path):
    target = tmp_path / "plan.md"
    target.write_text("someone else's", encoding="utf-8")
    context = context_for(tmp_path, Confirm(), "files.write")
    context.extra[CONFIRMED] = False
    with pytest.raises(ToolError, match="appeared meanwhile"):
        write_file.run({"path": str(target), "content": "mine"}, context)
    assert target.read_text(encoding="utf-8") == "someone else's"


def test_a_new_document_is_made_without_asking_and_never_over_one(tmp_path):
    confirm = Confirm()
    context = context_for(tmp_path, confirm, "docs.write")
    target = tmp_path / "report.docx"
    registry = default_registry()
    assert registry.invoke("create_document", {"path": str(target), "content": "# Report"},
                           context).ok
    assert confirm.asked == [] and target.stat().st_size > 0
    again = registry.invoke("create_document", {"path": str(target), "content": "# Again"},
                            context)
    assert not again.ok and "already exists" in again.content


@pytest.mark.parametrize("name", ["make_image", "save_drawing", "save_screenshot"])
def test_pictures_drawings_and_screenshots_are_new_files_and_do_not_ask(name):
    tool = default_registry().get(name)
    assert not tool.reversible and tool.asks is not None and not tool.asks({}, None)


def _counter(runs):
    return Tool(name="run_thing", summary="Run a thing.",
                parameters=(Parameter("path", "string", "Where."),),
                requires=(Requirement("files.read", scope_from="path"),),
                run=lambda arguments, context: (runs.append(arguments["path"]),
                                                ToolResult.success("ran"))[1],
                reversible=False, repeatable=True)


def test_a_yes_covers_the_very_same_run_again_in_the_same_work(tmp_path):
    runs = []
    registry = ToolRegistry()
    registry.register(_counter(runs))
    confirm = Confirm()
    context = context_for(tmp_path, confirm, "files.read")
    same = {"path": str(tmp_path / "a")}
    assert registry.invoke("run_thing", same, context).ok
    assert registry.invoke("run_thing", same, context).ok
    assert len(confirm.asked) == 1 and REPEAT_NOTE in confirm.asked[0]
    # Anything different asks again, and a new piece of work starts over.
    assert registry.invoke("run_thing", {"path": str(tmp_path / "b")}, context).ok
    assert len(confirm.asked) == 2
    assert registry.invoke("run_thing", same, context_for(tmp_path, confirm, "files.read")).ok
    assert len(confirm.asked) == 3 and len(runs) == 4


def test_a_no_is_not_remembered_as_a_yes(tmp_path):
    registry = ToolRegistry()
    registry.register(_counter([]))
    confirm = Confirm(answer=False)
    context = context_for(tmp_path, confirm, "files.read")
    same = {"path": str(tmp_path / "a")}
    assert not registry.invoke("run_thing", same, context).ok
    assert not registry.invoke("run_thing", same, context).ok
    assert len(confirm.asked) == 2


def test_running_a_script_shows_the_script_and_a_change_asks_again(tmp_path):
    script = tmp_path / "hello.py"
    script.write_text("print('hello')\n", encoding="utf-8")
    tool = default_registry().get("run_python")
    assert tool.repeatable
    shown = tool.describe({"path": str(script)}, None)
    assert "print('hello')" in shown
    script.write_text("print('changed')\n", encoding="utf-8")
    assert tool.describe({"path": str(script)}, None) != shown
