"""The coding tools (A8): checking, running, testing, git, and the editor.

The git tests carry *controls*. "Hooks are not run" proves nothing on a
machine where hooks never run anyway, so each of those tests first shows the
attack working through plain git, and skips if it does not — a green result
here means the defence did something, not that the attack was inert.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap

import pytest

from protege.core.permissions import AuditLog, Policy, SecretStore
from protege.core.tools import ToolContext, default_registry
from protege.core.tools.builtin import coding

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


def ctx(tmp_path, *grants, confirm=None):
    policy = Policy()
    for capability, scope in grants:
        policy.grant(capability, (str(scope),))
    return ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"), actor="tester",
                       confirm=confirm or (lambda summary: False))


def approved(tmp_path, *grants):
    return ctx(tmp_path, *grants, confirm=lambda summary: True)


def call(name, arguments, context):
    return default_registry().invoke(name, arguments, context)


def write(path, body):
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


# -- what is offered ---------------------------------------------------------


def test_the_coding_tools_are_offered_only_once_granted(project):
    registry = default_registry()
    assert not {t.name for t in registry.available(Policy())}

    reading = Policy()
    reading.grant("vcs.read", (str(project),))
    names = {t.name for t in registry.available(reading)}
    assert {"git_status", "git_diff", "git_log"} <= names
    assert not {"git_commit", "run_tests", "run_python"} & names


# -- check_syntax --------------------------------------------------------------


def test_a_clean_python_file_passes(project, tmp_path):
    source = write(project / "ok.py", "def f():\n    return 1\n")
    result = call("check_syntax", {"path": str(source)}, ctx(tmp_path, ("files.read", project)))
    assert result.ok and "No syntax errors" in result.content


def test_a_syntax_error_is_pointed_at(project, tmp_path):
    source = write(project / "bad.py", "def f(:\n    return 1\n")
    result = call("check_syntax", {"path": str(source)}, ctx(tmp_path, ("files.read", project)))
    assert result.ok and "line 1" in result.content and "^" in result.content


def test_checking_never_runs_the_code(project, tmp_path):
    marker = project / "ran"
    source = write(project / "sneaky.py", f"open({str(marker)!r}, 'w').write('x')\n")
    call("check_syntax", {"path": str(source)}, ctx(tmp_path, ("files.read", project)))
    assert not marker.exists()


def test_broken_json_is_pointed_at(project, tmp_path):
    source = write(project / "c.json", '{"a": 1,,}')
    result = call("check_syntax", {"path": str(source)}, ctx(tmp_path, ("files.read", project)))
    assert result.ok and "line 1" in result.content


def test_other_file_types_are_refused(project, tmp_path):
    source = write(project / "notes.txt", "hello")
    result = call("check_syntax", {"path": str(source)}, ctx(tmp_path, ("files.read", project)))
    assert not result.ok


def test_checking_needs_permission_to_read(project, tmp_path):
    source = write(project / "ok.py", "x = 1\n")
    result = call("check_syntax", {"path": str(source)}, ctx(tmp_path))
    assert "Not permitted" in result.content


# -- run_python ----------------------------------------------------------------


def test_running_code_asks_first_and_declining_runs_nothing(project, tmp_path):
    marker = project / "ran"
    script = write(project / "s.py", f"open({str(marker)!r}, 'w').write('x')\n")
    asked = []
    result = call("run_python", {"path": str(script)},
                  ctx(tmp_path, ("shell.run", project),
                      confirm=lambda summary: asked.append(summary) or False))
    assert not result.ok
    assert asked and "s.py" in asked[0]
    assert not marker.exists()


def test_approved_code_runs_and_its_output_comes_back(project, tmp_path):
    script = write(project / "s.py", "import sys\nprint('hello', sys.argv[1:])\n")
    result = call("run_python", {"path": str(script), "arguments": ["a", "b c"]},
                  approved(tmp_path, ("shell.run", project)))
    assert result.ok
    assert "hello ['a', 'b c']" in result.content
    assert "exit code 0" in result.content


def test_a_script_can_import_its_neighbours(project, tmp_path):
    write(project / "helper.py", "VALUE = 41\n")
    script = write(project / "main.py", "import helper\nprint(helper.VALUE + 1)\n")
    result = call("run_python", {"path": str(script)}, approved(tmp_path, ("shell.run", project)))
    assert "42" in result.content


def test_code_run_this_way_cannot_reach_the_network(project, tmp_path):
    script = write(project / "net.py", """
        import socket
        socket.create_connection(("192.0.2.1", 80), timeout=2)
        print("connected")
    """)
    result = call("run_python", {"path": str(script)}, approved(tmp_path, ("shell.run", project)))
    assert "connected" not in result.content
    assert "NetworkAccessBlocked" in result.content


def test_credentials_in_the_environment_do_not_reach_the_code(project, tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_TEST_TOKEN", "sk-live-secret")
    script = write(project / "env.py", """
        import os
        print("token:", os.environ.get("PROTEGE_TEST_TOKEN"))
    """)
    result = call("run_python", {"path": str(script)}, approved(tmp_path, ("shell.run", project)))
    assert "token: None" in result.content
    assert "sk-live-secret" not in result.content


def test_a_runaway_script_is_stopped(project, tmp_path, monkeypatch):
    monkeypatch.setattr(coding, "RUN_TIMEOUT_S", 2.0)
    script = write(project / "slow.py", "import time\ntime.sleep(30)\n")
    result = call("run_python", {"path": str(script)}, approved(tmp_path, ("shell.run", project)))
    assert result.ok and "stopped after" in result.content


def test_running_outside_the_granted_folder_is_refused(project, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    script = write(other / "x.py", "print(1)\n")
    result = call("run_python", {"path": str(script)}, approved(tmp_path, ("shell.run", project)))
    assert "Not permitted" in result.content


def test_only_python_files_are_run(project, tmp_path):
    script = write(project / "x.bat", "echo hi\n")
    result = call("run_python", {"path": str(script)}, approved(tmp_path, ("shell.run", project)))
    assert not result.ok


def test_an_argument_that_is_not_a_string_is_refused(project, tmp_path):
    script = write(project / "s.py", "print(1)\n")
    result = call("run_python", {"path": str(script), "arguments": [1]},
                  approved(tmp_path, ("shell.run", project)))
    assert not result.ok


# -- run_tests -----------------------------------------------------------------


def test_passing_tests_are_reported(project, tmp_path):
    write(project / "test_sample.py", "def test_ok():\n    assert 1 + 1 == 2\n")
    result = call("run_tests", {"path": str(project)}, approved(tmp_path, ("shell.run", project)))
    assert result.ok and "All tests passed" in result.content
    assert "1 passed" in result.content


def test_failing_tests_are_information_not_a_tool_failure(project, tmp_path):
    """The agent has to read the failure; a failed *tool* reads as breakage."""
    write(project / "test_sample.py", "def test_bad():\n    assert 1 == 2\n")
    result = call("run_tests", {"path": str(project)}, approved(tmp_path, ("shell.run", project)))
    assert result.ok and "Some tests failed" in result.content
    assert "1 failed" in result.content


def test_running_tests_asks_first(project, tmp_path):
    write(project / "test_sample.py", "def test_ok():\n    pass\n")
    result = call("run_tests", {"path": str(project)}, ctx(tmp_path, ("shell.run", project)))
    assert not result.ok


def test_a_selector_cannot_smuggle_in_an_option(project, tmp_path):
    """`-p` would load an arbitrary plugin — code nobody approved."""
    result = call("run_tests", {"path": str(project), "selector": "-p evil_plugin"},
                  approved(tmp_path, ("shell.run", project)))
    assert not result.ok


def test_a_selector_cannot_point_outside_the_project(project, tmp_path):
    result = call("run_tests", {"path": str(project), "selector": "../elsewhere/test_x.py"},
                  approved(tmp_path, ("shell.run", project)))
    assert not result.ok


# -- git -----------------------------------------------------------------------


def git(root, *args):
    return subprocess.run([GIT, "-C", str(root), *args], check=True,
                          capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Tester")
    git(root, "config", "user.email", "tester@example.com")
    git(root, "config", "commit.gpgsign", "false")
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    git(root, "add", "a.txt")
    git(root, "commit", "-q", "-m", "first")
    return root


def commits(root):
    return git(root, "log", "--pretty=format:%s").stdout.splitlines()


@needs_git
def test_status_shows_the_branch_and_the_changes(repo, tmp_path):
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    (repo / "new.txt").write_text("x\n", encoding="utf-8")
    result = call("git_status", {"path": str(repo)}, ctx(tmp_path, ("vcs.read", repo)))
    assert result.ok and "main" in result.content
    assert "a.txt" in result.content and "new.txt" in result.content


@needs_git
def test_diff_shows_what_changed(repo, tmp_path):
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    result = call("git_diff", {"path": str(repo)}, ctx(tmp_path, ("vcs.read", repo)))
    assert result.ok and "-one" in result.content and "+two" in result.content


@needs_git
def test_log_lists_commits(repo, tmp_path):
    result = call("git_log", {"path": str(repo)}, ctx(tmp_path, ("vcs.read", repo)))
    assert result.ok and "first" in result.content


@needs_git
def test_a_folder_inside_the_repository_is_refused(repo, tmp_path):
    """Git would show the whole repository, not just the granted folder."""
    inner = repo / "sub"
    inner.mkdir()
    result = call("git_status", {"path": str(inner)}, ctx(tmp_path, ("vcs.read", inner)))
    assert not result.ok and "top of the repository" in result.content


@needs_git
def test_committing_asks_first_and_declining_changes_nothing(repo, tmp_path):
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    result = call("git_commit", {"path": str(repo), "message": "second", "files": ["a.txt"]},
                  ctx(tmp_path, ("vcs.write", repo)))
    assert not result.ok
    assert commits(repo) == ["first"]


@needs_git
def test_an_approved_commit_is_made_and_nothing_is_pushed(repo, tmp_path):
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    result = call("git_commit", {"path": str(repo), "message": "second", "files": ["a.txt"]},
                  approved(tmp_path, ("vcs.write", repo)))
    assert result.ok and "Nothing was pushed" in result.content
    assert commits(repo) == ["second", "first"]


@needs_git
def test_committing_with_nothing_staged_says_so(repo, tmp_path):
    result = call("git_commit", {"path": str(repo), "message": "empty"},
                  approved(tmp_path, ("vcs.write", repo)))
    assert not result.ok and "Nothing was staged" in result.content


@needs_git
def test_a_file_outside_the_repository_cannot_be_staged(repo, tmp_path):
    result = call("git_commit", {"path": str(repo), "message": "x", "files": ["../outside.txt"]},
                  approved(tmp_path, ("vcs.write", repo)))
    assert not result.ok
    assert commits(repo) == ["first"]


@needs_git
def test_a_repositorys_own_hooks_are_not_run(repo, tmp_path):
    marker = tmp_path / "hook-ran"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\necho ran > '{marker.as_posix()}'\n", encoding="utf-8")
    hook.chmod(0o755)

    # Control: plain git runs it. If not, this machine proves nothing either way.
    git(repo, "commit", "-q", "--allow-empty", "-m", "control")
    if not marker.exists():
        pytest.skip("hooks do not run under plain git on this machine")
    marker.unlink()

    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    result = call("git_commit", {"path": str(repo), "message": "via tool", "files": ["a.txt"]},
                  approved(tmp_path, ("vcs.write", repo)))
    assert result.ok
    assert not marker.exists(), "the repository's hook ran"


@needs_git
def test_looking_does_not_run_a_repositorys_fsmonitor_command(repo, tmp_path):
    """`core.fsmonitor` turns `git status` into running a program."""
    marker = tmp_path / "fsmonitor-ran"
    git(repo, "config", "core.fsmonitor", f"echo ran > '{marker.as_posix()}'")

    subprocess.run([GIT, "-C", str(repo), "status"], capture_output=True)
    if not marker.exists():
        pytest.skip("this git does not run fsmonitor commands under plain status")
    marker.unlink()

    result = call("git_status", {"path": str(repo)}, ctx(tmp_path, ("vcs.read", repo)))
    assert result.ok
    assert not marker.exists(), "status ran the repository's fsmonitor command"


# -- open_in_editor ----------------------------------------------------------


def test_the_editor_is_started_directly_never_through_cmd(project, tmp_path, monkeypatch):
    """A batch file's arguments are re-parsed by cmd.exe; `&` would be a command."""
    target = write(project / "odd & calc ^ %PATH%.py", "x = 1\n")
    launched = []
    monkeypatch.setattr(coding, "_find_vscode",
                        lambda: (tmp_path / "Code.exe", tmp_path / "cli.js"))
    monkeypatch.setattr(coding, "_launch", lambda argv, env: launched.append((argv, env)))

    result = call("open_in_editor", {"path": str(target), "line": 12},
                  ctx(tmp_path, ("files.read", project)))

    assert result.ok
    argv, env = launched[0]
    assert argv[0].endswith("Code.exe") and argv[1].endswith("cli.js")
    assert argv[2:] == ["--goto", f"{target}:12"]
    assert env["ELECTRON_RUN_AS_NODE"] == "1"
    assert not any(a.lower().endswith((".cmd", ".bat")) for a in argv)


def test_a_folder_opens_as_a_folder(project, tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr(coding, "_find_vscode",
                        lambda: (tmp_path / "Code.exe", tmp_path / "cli.js"))
    monkeypatch.setattr(coding, "_launch", lambda argv, env: launched.append(argv))
    call("open_in_editor", {"path": str(project)}, ctx(tmp_path, ("files.read", project)))
    assert launched[0][2:] == [str(project)]


def test_vscode_is_found_from_its_install_layout(tmp_path, monkeypatch):
    install = tmp_path / "VS Code"
    (install / "bin").mkdir(parents=True)
    (install / "bin" / "code.cmd").write_text("@echo off\n", encoding="utf-8")
    (install / "Code.exe").write_bytes(b"MZ")
    cli = install / "a44adf7f53" / "resources" / "app" / "out" / "cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("//\n", encoding="utf-8")
    monkeypatch.setattr(coding.shutil, "which",
                        lambda name: str(install / "bin" / "code.cmd"))

    assert coding._find_vscode() == ((install / "Code.exe").resolve(), cli.resolve())


def test_without_vscode_it_says_so_rather_than_trying_the_batch_file(project, tmp_path,
                                                                   monkeypatch):
    monkeypatch.setattr(coding, "_find_vscode", lambda: None)
    launched = []
    monkeypatch.setattr(coding, "_launch", lambda argv, env: launched.append(argv))
    target = write(project / "a.py", "x = 1\n")
    result = call("open_in_editor", {"path": str(target)}, ctx(tmp_path, ("files.read", project)))
    assert not result.ok and "VS Code was not found" in result.content
    assert launched == []


def test_opening_needs_permission_to_read(project, tmp_path, monkeypatch):
    monkeypatch.setattr(coding, "_launch", lambda argv, env: None)
    target = write(project / "a.py", "x = 1\n")
    result = call("open_in_editor", {"path": str(target)}, ctx(tmp_path))
    assert "Not permitted" in result.content
