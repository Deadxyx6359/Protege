"""Working on code: checking it, running it, testing it, using git, opening it.

Three tiers of consequence, each behind the gate it deserves:

  * **Looking** — `check_syntax` parses without executing; `git_status`,
    `git_diff` and `git_log` read history; `open_in_editor` shows a file to the
    person. Reversible, so no prompt.
  * **Running** — `run_python` and `run_tests` execute code, which can do
    anything the user can. That is `shell.run`: irreversible, so every single
    run is confirmed, whatever the grant says.
  * **Recording** — `git_commit` writes history. Confirmed as well.

**There is no push.** Pushing sends the repository off this machine, and the
only door off this machine is to be the network chokepoint (C1), which does
not exist yet. Until it does nothing here speaks a network protocol, and git
is explicitly told not to.

## Running code

Children start through `_guarded.py`, which installs the same network guard as
the skill runner before any project code is compiled. The environment is
reduced to an allowlist, stdin is closed, output is capped and there is a wall
clock timeout. None of that is a sandbox — code running as the user can do what
the user can, and `ctypes` walks straight past the network guard — which is why
the real control is that a person approves each run.

If the folder being run from has its own virtual environment (`.venv` or
`venv`), its Python runs the code, so the project's dependencies import. Only
that folder is checked. Searching parent folders would mean executing an
interpreter from outside the folder the permission was granted for.

## Read-only git is not read-only by default

A repository's own configuration can make "just looking" run programs:
`core.fsmonitor` runs a command on every `status`, and hooks, credential
helpers and signing programs are all commands a repository can name. Every git
call here overrides those, and blocks every network protocol. What cannot be
switched off generically is a clean or smudge filter defined in a repository's
own `.git/config` — so treat a repository someone else prepared as you would
treat their code.

Commits made here are therefore unsigned and run no hooks. The result says so.

## The editor

VS Code's `code` command is a batch file, and cmd.exe re-parses a batch file's
arguments: a file name containing `&` can become a second command. Paths here
come from a model, so `open_in_editor` never goes near cmd.exe. It finds the
real `Code.exe` and its CLI script and starts them directly — which is exactly
what the batch file itself does — and if they cannot be found it says so rather
than falling back to the batch file.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from akira.security.paths import PathViolation, real, reject_dangerous

from ..schema import Parameter, Requirement, Tool, ToolContext, ToolError, ToolResult

GUARDED = Path(__file__).with_name("_guarded.py")

RUN_TIMEOUT_S = 60.0
TEST_TIMEOUT_S = 300.0
GIT_TIMEOUT_S = 30.0

#: Output handed back to a model. Smaller than the skill runner's cap, because
#: this lands in a context window rather than on a screen.
MAX_OUTPUT_CHARS = 20_000
MAX_CHECK_BYTES = 2_000_000
MAX_ARGUMENTS = 50
MAX_ARGUMENT_CHARS = 1000
MAX_MESSAGE_CHARS = 5000

#: Passed through to code this runs. Credential-bearing variables — tokens,
#: cloud keys, proxy settings — are dropped by omission. The location variables
#: are kept, unlike the skill runner, because real test suites need a home
#: directory to exist and fail in baffling ways when it does not.
ENV_ALLOWLIST = (
    "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
    "LANG", "LC_ALL", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "HOME",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "NUMBER_OF_PROCESSORS",
)

_PYTHON_ENV = {
    "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1",
}

_GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    # A partial clone fetches missing objects over the network on demand.
    "GIT_NO_LAZY_FETCH": "1",
    # `status` refreshes the index by default, which is a write. Not needed.
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "cat",
}

#: No console window flashing up when a GUI process starts a child.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_TEST_OUTCOMES = {
    0: "All tests passed",
    1: "Some tests failed",
    2: "The test run was interrupted",
    3: "pytest hit an internal error",
    4: "pytest was called with arguments it did not accept",
    5: "No tests were found",
}


# -- shared ------------------------------------------------------------------


def _env(**extra: str) -> dict[str, str]:
    env = {name: os.environ[name] for name in ENV_ALLOWLIST if name in os.environ}
    env.update(extra)
    return env


def _clip(text: str | bytes | None) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n[... cut at {MAX_OUTPUT_CHARS} characters ...]"


def _run(argv: list[str], *, cwd: Path, timeout: float,
         env: dict[str, str]) -> tuple[int | None, str, str, bool]:
    """Run to completion. Returns (exit code, stdout, stderr, timed out)."""
    try:
        completed = subprocess.run(
            argv, cwd=str(cwd), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            # A child reading stdin would block forever behind a GUI.
            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        return None, _clip(exc.stdout), _clip(exc.stderr), True
    except OSError as exc:
        raise ToolError(f"could not start {Path(argv[0]).name}: {exc}") from None
    return completed.returncode, _clip(completed.stdout), _clip(completed.stderr), False


def _inside(root: Path, relative: str) -> Path:
    """Resolve \a relative under \a root, refusing anything that leaves it."""
    text = str(relative).strip()
    if not text or text.startswith("-") or "\n" in text or "\x00" in text:
        raise ToolError(f"{relative!r} is not a path inside {root}")
    try:
        candidate = (root / text).resolve()
        reject_dangerous(candidate)
    except (PathViolation, OSError, ValueError) as exc:
        raise ToolError(f"{relative!r} cannot be used: {exc}") from None
    if not candidate.is_relative_to(root):
        raise ToolError(f"{relative!r} is outside {root}")
    return candidate


def _strings(raw) -> list[str]:
    """An optional list of plain strings, as a model might supply it."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, (list, tuple)):
        raise ToolError("expected a list of strings")
    if len(raw) > MAX_ARGUMENTS:
        raise ToolError(f"at most {MAX_ARGUMENTS} entries")
    cleaned = []
    for item in raw:
        if not isinstance(item, str):
            raise ToolError("every entry must be a string")
        if len(item) > MAX_ARGUMENT_CHARS or "\x00" in item:
            raise ToolError("an entry is too long or contains a null character")
        cleaned.append(item)
    return cleaned


def _interpreter(folder: Path) -> Path:
    for venv in (".venv", "venv"):
        for relative in ("Scripts/python.exe", "bin/python"):
            candidate = folder / venv / relative
            if candidate.is_file():
                return candidate
    return Path(sys.executable)


def _report(head: str, exit_code: int | None, stdout: str, stderr: str,
            timed_out: bool, python: Path) -> ToolResult:
    parts = [head, f"Python: {python}"]
    if stdout.strip():
        parts += ["", "--- output ---", stdout.rstrip()]
    if stderr.strip():
        parts += ["", "--- errors ---", stderr.rstrip()]
    return ToolResult.success("\n".join(parts),
                              data={"exit_code": exit_code, "timed_out": timed_out})


# -- check_syntax ------------------------------------------------------------


def _pointer(path: Path, line: int | None, column: int | None, message: str,
             lines: list[str]) -> str:
    text = f"{path.name}, line {line}, column {column}: {message}"
    if line and 1 <= line <= len(lines):
        caret = " " * max(0, (column or 1) - 1) + "^"
        text += f"\n    {lines[line - 1]}\n    {caret}"
    return text


def _run_check(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    if not path.is_file():
        raise ToolError(f"no such file: {path}")
    suffix = path.suffix.lower()
    if suffix not in (".py", ".pyw", ".json"):
        raise ToolError(f"{path.name}: only Python and JSON files can be checked")
    if path.stat().st_size > MAX_CHECK_BYTES:
        raise ToolError(f"{path.name} is too large to check")
    try:
        source = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        return ToolResult.success(f"{path.name} is not valid UTF-8 (at byte {exc.start}).",
                                  data={"ok": False})
    except OSError as exc:
        raise ToolError(f"could not read {path.name}: {exc}") from None

    lines = source.splitlines()
    try:
        if suffix == ".json":
            json.loads(source)
        else:
            # Parses; never compiles to bytecode and never executes.
            ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return ToolResult.success(_pointer(path, exc.lineno, exc.offset, exc.msg, lines),
                                  data={"ok": False, "line": exc.lineno})
    except json.JSONDecodeError as exc:
        return ToolResult.success(_pointer(path, exc.lineno, exc.colno, exc.msg, lines),
                                  data={"ok": False, "line": exc.lineno})
    except (RecursionError, MemoryError, ValueError) as exc:
        raise ToolError(f"{path.name} could not be checked: {exc}") from None
    return ToolResult.success(f"No syntax errors in {path} ({len(lines)} lines).",
                              data={"ok": True})


check_syntax = Tool(
    name="check_syntax",
    summary="Check a Python or JSON file for syntax errors without running it.",
    parameters=(Parameter("path", "string", "Absolute path to the file."),),
    requires=(Requirement("files.read", scope_from="path"),),
    run=_run_check,
)


# -- run_python --------------------------------------------------------------


def _run_python(arguments: dict, context: ToolContext) -> ToolResult:
    script = real(arguments["path"])
    if not script.is_file() or script.suffix.lower() not in (".py", ".pyw"):
        raise ToolError(f"{script} is not a Python file")
    extra = _strings(arguments.get("arguments"))
    folder = script.parent
    python = _interpreter(folder)

    code, out, err, timed_out = _run(
        [str(python), "-I", str(GUARDED), "--script", str(script), *extra],
        cwd=folder, timeout=RUN_TIMEOUT_S, env=_env(**_PYTHON_ENV))

    if timed_out:
        head = f"{script.name} was stopped after {RUN_TIMEOUT_S:.0f} seconds."
    elif code == 0:
        head = f"{script.name} finished (exit code 0)."
    else:
        head = f"{script.name} exited with code {code}."
    return _report(head, code, out, err, timed_out, python)


run_python = Tool(
    name="run_python",
    summary="Run a Python script and return what it printed.",
    parameters=(
        Parameter("path", "string", "Absolute path to the .py file."),
        Parameter("arguments", "array", "Optional command-line arguments for the script.",
                  required=False),
    ),
    requires=(Requirement("shell.run", scope_from="path"),),
    # Code can do anything the user can. Every run is approved by a person.
    reversible=False,
    run=_run_python,
)


# -- run_tests ---------------------------------------------------------------


def _run_tests(arguments: dict, context: ToolContext) -> ToolResult:
    root = real(arguments["path"])
    if not root.is_dir():
        raise ToolError(f"not a folder: {root}")

    # Caching off: a test run should leave the project as it found it.
    pytest_args = ["-q", "--color=no", "-p", "no:cacheprovider"]
    selector = str(arguments.get("selector") or "").strip()
    if selector:
        # A selector is a test path or node id, never an option — `-p` alone
        # would load an arbitrary plugin, which is code nobody approved.
        _inside(root, selector.split("::", 1)[0])
        pytest_args.append(selector)
    python = _interpreter(root)

    code, out, err, timed_out = _run(
        [str(python), "-I", str(GUARDED), "--module", "pytest", *pytest_args],
        cwd=root, timeout=TEST_TIMEOUT_S, env=_env(**_PYTHON_ENV))

    if timed_out:
        head = f"The tests were stopped after {TEST_TIMEOUT_S:.0f} seconds."
    else:
        head = f"{_TEST_OUTCOMES.get(code, 'pytest finished')} (exit code {code})."
    # Failing tests are information, not a tool failure: the agent needs to
    # read them, and the loop treats a failed tool as something went wrong.
    return _report(head, code, out, err, timed_out, python)


run_tests = Tool(
    name="run_tests",
    summary="Run a project's tests with pytest and report what passed and failed.",
    parameters=(
        Parameter("path", "string", "Absolute path to the project folder."),
        Parameter("selector", "string",
                  "Optional test file or test id inside the project, "
                  "e.g. tests/test_api.py::test_login.", required=False),
    ),
    requires=(Requirement("shell.run", scope_from="path"),),
    reversible=False,
    run=_run_tests,
)


# -- git ---------------------------------------------------------------------

_NO_HOOKS: str | None = None


def _no_hooks_dir() -> str:
    """An empty folder to point `core.hooksPath` at, so no hook is found."""
    global _NO_HOOKS
    if _NO_HOOKS is None or not Path(_NO_HOOKS).is_dir():
        _NO_HOOKS = tempfile.mkdtemp(prefix="akira-no-hooks-")
    return _NO_HOOKS


def _git_argv(repo: Path, *args: str) -> list[str]:
    git = shutil.which("git")
    if git is None:
        raise ToolError("git is not installed, or is not on PATH")
    return [
        git, "--no-pager",
        "-c", "core.fsmonitor=false",
        "-c", f"core.hooksPath={_no_hooks_dir()}",
        # The empty value resets the helper list: no credential program runs.
        "-c", "credential.helper=",
        "-c", "protocol.allow=never",
        "-c", "commit.gpgSign=false",
        "-c", "tag.gpgSign=false",
        "-C", str(repo), *args,
    ]


def _git(repo: Path, *args: str) -> tuple[int, str, str]:
    code, out, err, timed_out = _run(_git_argv(repo, *args), cwd=repo,
                                     timeout=GIT_TIMEOUT_S, env=_env(**_GIT_ENV))
    if timed_out:
        raise ToolError(f"git {args[0]} did not finish within {GIT_TIMEOUT_S:.0f} seconds")
    return code or 0, out, err


def _repository(path_text: str) -> Path:
    """The repository at \a path_text, which must be its top folder.

    A folder *inside* a repository is refused: git would show the whole
    repository, including everything outside the folder the permission was
    granted for.
    """
    folder = real(path_text)
    if not folder.is_dir():
        raise ToolError(f"not a folder: {folder}")
    code, out, err = _git(folder, "rev-parse", "--show-toplevel")
    if code != 0:
        raise ToolError(f"{folder} is not a git repository: {err.strip()[:300]}")
    top = Path(out.strip()).resolve()
    if top != folder.resolve():
        raise ToolError(
            f"give the top of the repository, {top}, not a folder inside it — the "
            "permission has to cover everything git will show")
    return folder


def _path_parameter() -> Parameter:
    return Parameter("path", "string", "Absolute path to the top folder of the repository.")


def _run_status(arguments: dict, context: ToolContext) -> ToolResult:
    repo = _repository(arguments["path"])
    code, out, err = _git(repo, "status", "--porcelain=v1", "--branch",
                          "--untracked-files=normal")
    if code != 0:
        raise ToolError(f"git status failed: {err.strip()[:500]}")
    lines = out.splitlines()
    branch = lines[0][3:] if lines and lines[0].startswith("## ") else "(unknown)"
    changes = [line for line in lines if not line.startswith("## ")]
    body = "\n".join(changes) if changes else "Nothing to commit; the working tree is clean."
    return ToolResult.success(f"{repo}\nBranch: {branch}\n\n{body}",
                              data={"changes": len(changes)})


git_status = Tool(
    name="git_status",
    summary="Show the branch and the uncommitted changes in a git repository.",
    parameters=(_path_parameter(),),
    requires=(Requirement("vcs.read", scope_from="path"),),
    run=_run_status,
)


def _run_diff(arguments: dict, context: ToolContext) -> ToolResult:
    repo = _repository(arguments["path"])
    base = ["diff", "--no-ext-diff", "--no-textconv", "--no-color"]
    if arguments.get("staged"):
        base.append("--staged")
    limit: list[str] = []
    file = str(arguments.get("file") or "").strip()
    if file:
        limit = ["--", _inside(repo, file).relative_to(repo.resolve()).as_posix()]

    code, stat, err = _git(repo, *base, "--stat", *limit)
    if code != 0:
        raise ToolError(f"git diff failed: {err.strip()[:500]}")
    code, patch, err = _git(repo, *base, *limit)
    if code != 0:
        raise ToolError(f"git diff failed: {err.strip()[:500]}")
    if not patch.strip():
        return ToolResult.success(
            "No staged changes." if arguments.get("staged") else "No unstaged changes.")
    return ToolResult.success(f"{stat.rstrip()}\n\n{patch}")


git_diff = Tool(
    name="git_diff",
    summary="Show uncommitted changes in a git repository as a diff.",
    parameters=(
        _path_parameter(),
        Parameter("staged", "boolean", "Show staged changes instead of unstaged ones.",
                  required=False, default=False),
        Parameter("file", "string", "Optional file inside the repository to limit it to.",
                  required=False),
    ),
    requires=(Requirement("vcs.read", scope_from="path"),),
    run=_run_diff,
)


def _run_log(arguments: dict, context: ToolContext) -> ToolResult:
    repo = _repository(arguments["path"])
    limit = max(1, min(int(arguments.get("limit") or 10), 100))
    code, out, err = _git(repo, "log", f"-n{limit}", "--no-color", "--date=short",
                          "--pretty=format:%h  %ad  %an  %s")
    if code != 0:
        if "does not have any commits" in err:
            return ToolResult.success("No commits yet.")
        raise ToolError(f"git log failed: {err.strip()[:500]}")
    return ToolResult.success(out.strip() or "No commits yet.")


git_log = Tool(
    name="git_log",
    summary="List the most recent commits in a git repository.",
    parameters=(
        _path_parameter(),
        Parameter("limit", "integer", "How many commits to list, from 1 to 100.",
                  required=False, default=10),
    ),
    requires=(Requirement("vcs.read", scope_from="path"),),
    run=_run_log,
)


def _run_commit(arguments: dict, context: ToolContext) -> ToolResult:
    repo = _repository(arguments["path"])
    message = str(arguments["message"]).strip()
    if not message:
        raise ToolError("a commit needs a message")
    if len(message) > MAX_MESSAGE_CHARS:
        raise ToolError(f"a commit message is limited to {MAX_MESSAGE_CHARS} characters")

    top = repo.resolve()
    files = [_inside(repo, f).relative_to(top).as_posix()
             for f in _strings(arguments.get("files"))]
    if files:
        code, out, err = _git(repo, "add", "--", *files)
        if code != 0:
            raise ToolError(f"git add failed: {err.strip()[:500]}")

    code, out, err = _git(repo, "commit", "-m", message)
    if code != 0:
        text = (out + err).strip()
        if "nothing to commit" in text or "no changes added" in text:
            return ToolResult.failure("Nothing was staged, so nothing was committed.")
        raise ToolError(f"git commit failed: {text[:500]}")

    _, head, _ = _git(repo, "rev-parse", "--short", "HEAD")
    head = head.strip()
    return ToolResult.success(
        f"Committed {head} on this computer: {message.splitlines()[0][:100]}\n"
        "Nothing was pushed. Hooks were not run and the commit is unsigned, because "
        "a repository's hooks and signing program are code nobody has approved.",
        data={"commit": head})


git_commit = Tool(
    name="git_commit",
    summary="Commit changes to a git repository on this computer. Never pushes.",
    parameters=(
        _path_parameter(),
        Parameter("message", "string", "The commit message."),
        Parameter("files", "array", "Optional files inside the repository to stage first.",
                  required=False),
    ),
    requires=(Requirement("vcs.write", scope_from="path"),),
    reversible=False,
    run=_run_commit,
)


# -- open_in_editor ------------------------------------------------------------


def _find_vscode() -> tuple[Path, Path] | None:
    """`Code.exe` and its CLI script, from the `code` launcher's install."""
    launcher = shutil.which("code")
    if not launcher:
        return None
    install = Path(launcher).resolve().parent.parent
    exe = install / "Code.exe"
    if not exe.is_file():
        return None
    scripts = list(install.glob("*/resources/app/out/cli.js"))
    scripts.append(install / "resources" / "app" / "out" / "cli.js")
    scripts = [s for s in scripts if s.is_file()]
    if not scripts:
        return None
    # Several versioned folders can linger after an update; the newest is live.
    return exe, max(scripts, key=lambda s: s.stat().st_mtime)


def _launch(argv: list[str], env: dict[str, str]) -> None:
    """Start the editor and do not wait for it."""
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, creationflags=flags)


def _run_open(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    if not path.exists():
        raise ToolError(f"no such file or folder: {path}")
    line = int(arguments.get("line") or 1)
    if line < 1:
        raise ToolError("line numbers start at 1")

    found = _find_vscode()
    if found is None:
        return ToolResult.failure(
            "VS Code was not found. It is located through the `code` command on "
            "PATH — reinstall it with that option ticked, or open the file yourself.")
    exe, cli = found
    target = [str(path)] if path.is_dir() else ["--goto", f"{path}:{line}"]
    env = dict(os.environ)
    env["ELECTRON_RUN_AS_NODE"] = "1"
    env.pop("VSCODE_DEV", None)
    try:
        _launch([str(exe), str(cli), *target], env)
    except OSError as exc:
        raise ToolError(f"VS Code could not be started: {exc}") from None
    where = "" if path.is_dir() else f" at line {line}"
    return ToolResult.success(f"Opened {path.name} in VS Code{where}.")


open_in_editor = Tool(
    name="open_in_editor",
    summary="Open a file or folder in VS Code for the person to see, optionally at a line.",
    parameters=(
        Parameter("path", "string", "Absolute path to the file or folder."),
        Parameter("line", "integer", "Line to jump to.", required=False, default=1),
    ),
    requires=(Requirement("files.read", scope_from="path"),),
    run=_run_open,
)


ALL = (check_syntax, run_python, run_tests, git_status, git_diff, git_log,
       git_commit, open_in_editor)
