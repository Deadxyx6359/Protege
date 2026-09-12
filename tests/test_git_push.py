"""git_push (A8, finished): the checked-out branch to its remote with the
person's own git login, never forced, asked each time with the real address,
and never through anything a repository's own configuration names.

The remote here is a bare repository in a temporary folder. Pushing to a folder
is refused in use, because it writes outside the repository the permission
covers, so these tests let the file protocol through; every other rule is the
real one, and the test of the protocol rule puts it back.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import ToolContext, default_registry
from akira.core.tools.builtin import coding

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


def git(root, *args, check=True):
    return subprocess.run([GIT, "-C", str(root), *args], check=check, capture_output=True,
                          text=True)


def commit(root, name, text):
    (root / name).write_text(text, encoding="utf-8")
    git(root, "add", name)
    git(root, "commit", "-q", "-m", f"add {name}")


def remote_log(remote):
    done = git(remote, "log", "--pretty=format:%s", "main", check=False)
    return done.stdout.splitlines() if done.returncode == 0 else []


def identify(root, name):
    for key, value in (("user.name", name), ("user.email", f"{name.lower()}@example.com"),
                       ("commit.gpgsign", "false")):
        git(root, "config", key, value)


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.setattr(coding, "PUSH_PROTOCOLS", ("https", "ssh", "file"))
    remote = tmp_path / "remote.git"
    subprocess.run([GIT, "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    identify(root, "Tester")
    commit(root, "a.txt", "one\n")
    git(root, "remote", "add", "origin", remote.as_uri())
    return root, remote


def context(tmp_path, root, *, granted=True, confirm=None):
    policy = Policy()
    if granted:
        policy.grant("vcs.write", (str(root),))
    return ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"), actor="tester",
                       confirm=confirm or (lambda summary: False))


def push(tmp_path, root, arguments=None, **kw):
    return default_registry().invoke("git_push", {"path": str(root), **(arguments or {})},
                                     context(tmp_path, root, **kw))


def test_pushing_needs_the_permission(pair, tmp_path):
    root, remote = pair
    result = push(tmp_path, root, granted=False, confirm=lambda summary: True)
    assert not result.ok and "Not permitted" in result.content
    assert remote_log(remote) == []


def test_the_question_names_the_real_address_and_no_pushes_nothing(pair, tmp_path):
    root, remote = pair
    asked = []
    result = push(tmp_path, root, confirm=lambda summary: asked.append(summary) or False)
    assert not result.ok and remote_log(remote) == []
    [question] = asked
    assert "the new branch main" in question and "origin" in question
    assert remote.as_uri() in question


def test_an_approved_push_publishes_and_sets_the_upstream(pair, tmp_path):
    root, remote = pair
    assert push(tmp_path, root, confirm=lambda summary: True).ok
    assert remote_log(remote) == ["add a.txt"]
    assert git(root, "config", "branch.main.remote").stdout.strip() == "origin"

    commit(root, "b.txt", "two\n")
    asked = []
    assert push(tmp_path, root, confirm=lambda summary: asked.append(summary) or True).ok
    assert "1 commit on main" in asked[0]
    assert remote_log(remote) == ["add b.txt", "add a.txt"]


def test_nothing_to_push_is_said_without_asking(pair, tmp_path):
    root, remote = pair
    assert push(tmp_path, root, confirm=lambda summary: True).ok
    asked = []
    again = push(tmp_path, root, confirm=lambda summary: asked.append(summary) or True)
    assert not again.ok and "nothing to push" in again.content and asked == []


def test_only_https_and_ssh_addresses_are_pushed_to(pair, tmp_path, monkeypatch):
    root, remote = pair
    monkeypatch.setattr(coding, "PUSH_PROTOCOLS", ("https", "ssh"))
    asked = []
    for address in (remote.as_uri(), "http://example.com/x.git", "git://example.com/x.git",
                    "ext::sh -c touch% pwned"):
        git(root, "remote", "set-url", "origin", address)
        result = push(tmp_path, root, confirm=lambda summary: asked.append(summary) or True)
        assert not result.ok and "not an https or ssh address" in result.content, address
    assert asked == [], "a push to a refused address was put to the person"


def test_a_token_in_the_address_is_never_shown(pair, tmp_path):
    root, remote = pair
    git(root, "remote", "set-url", "origin", "https://me:ghp_s3cret@example.com/me/x.git")
    asked = []
    result = push(tmp_path, root, confirm=lambda summary: asked.append(summary) or False)
    assert not result.ok
    assert "ghp_s3cret" not in asked[0] and "•••@example.com" in asked[0]
    assert "ghp_s3cret" not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_a_push_the_remote_refuses_is_not_forced(pair, tmp_path):
    root, remote = pair
    assert push(tmp_path, root, confirm=lambda summary: True).ok
    other = tmp_path / "other"
    subprocess.run([GIT, "clone", "-q", str(remote), str(other)], check=True)
    identify(other, "Other")
    commit(other, "theirs.txt", "theirs\n")
    git(other, "push", "-q", "origin", "main")

    commit(root, "mine.txt", "mine\n")
    result = push(tmp_path, root, confirm=lambda summary: True)
    assert not result.ok and "Nothing was forced" in result.content
    assert remote_log(remote) == ["add theirs.txt", "add a.txt"]


def test_a_repositorys_own_login_program_is_never_run(pair, tmp_path):
    root, remote = pair
    git(root, "config", "credential.helper", "!echo pwned")
    git(root, "config", "core.sshCommand", "calc.exe")
    argv = coding._push_argv(coding._push_plan({"path": str(root)}))
    settings = [argv[i + 1] for i, part in enumerate(argv) if part == "-c"]
    assert "credential.helper=!echo pwned" not in settings
    helpers = [i for i, s in enumerate(settings) if s.startswith("credential.helper=")]
    assert helpers and settings[helpers[0]] == "credential.helper=", \
        "the helper list was not reset before the person's own"
    assert "core.sshCommand=calc.exe" not in settings
    assert any(s.startswith("core.hooksPath=") for s in settings)
    assert not {"--force", "-f", "--mirror", "--force-with-lease"} & set(argv)
    assert argv[-1] == "refs/heads/main:refs/heads/main"


def test_only_the_checked_out_branch_is_pushed(pair, tmp_path):
    root, remote = pair
    result = push(tmp_path, root, {"branch": "other"}, confirm=lambda summary: True)
    assert not result.ok and "only the checked-out branch" in result.content
    git(root, "checkout", "-q", "--detach")
    detached = push(tmp_path, root, confirm=lambda summary: True)
    assert not detached.ok and "not on a branch" in detached.content
    assert remote_log(remote) == []
