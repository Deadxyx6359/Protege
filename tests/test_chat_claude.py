"""Choosing Claude in the chat window: its key, the permission, which model answers,
and work handed over going to a team on Claude. Anthropic is a stand-in throughout."""

from __future__ import annotations

import time
from contextlib import contextmanager

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from akira.core.config import AppConfig  # noqa: E402
from akira.core.conversations import ConversationStore  # noqa: E402
from akira.core.models import ModelRouter  # noqa: E402
from akira.models.base import GenerationResult  # noqa: E402
from akira.ui.bridge import ChatBridge  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
    return predicate()


class Backend:
    label = "Claude Opus 5.5"
    n_ctx = 200_000
    is_loaded = True

    def __init__(self, asked):
        self.asked = asked

    def count_tokens(self, text):
        return len(text) // 3

    def generate(self, messages, *, on_token=None, **_):
        self.asked.append(messages)
        if on_token:
            on_token("From Claude.")
        return GenerationResult(text="From Claude.", completion_tokens=3)


class Router:
    def __init__(self, asked):
        self.asked = asked

    def resolve(self, route):
        return route

    @contextmanager
    def acquire(self, route):
        yield Backend(self.asked)


class Spend:
    def month(self):
        return {"read": 1000, "written": 200, "dollars": 0.01}


class FakeClaude:
    def __init__(self, key=False, allowed=False, check=""):
        self.key, self.allowed, self.check_says = key, allowed, check
        self.asked = []
        self.spend = Spend()

    def has_key(self):
        return self.key

    def ready(self):
        if not self.key:
            return "Add your Claude API key first."
        return "" if self.allowed else "Sending chats to Claude is not allowed now."

    def seal(self, key):
        if not key.startswith("sk-ant-"):
            return "That does not look like an Anthropic API key: they begin sk-ant-."
        self.key = True
        return ""

    def check(self):
        return self.check_says

    def forget(self):
        self.key = False

    def router(self, **_):
        return Router(self.asked)


def bridge(tmp_path, claude, *, granted=None):
    config = AppConfig()
    config.save = lambda: None
    given = granted if granted is not None else []

    def allow():
        given.append("model.cloud")
        claude.allowed = True
        return ""

    chat = ChatBridge(ModelRouter(config), config, ConversationStore(tmp_path / "chats"),
                      claude=claude, allow_cloud=allow)
    return chat, config, given


def test_the_window_offers_local_and_claude(app, tmp_path):
    chat, _, _ = bridge(tmp_path, FakeClaude())
    assert [m["id"] for m in chat.models] == ["local", "claude"]
    assert chat.model == "local"
    alone = ChatBridge(ModelRouter(AppConfig()), AppConfig(), ConversationStore(tmp_path / "x"))
    assert [m["id"] for m in alone.models] == ["local"]


def test_choosing_claude_without_a_key_asks_for_one(app, tmp_path):
    chat, _, given = bridge(tmp_path, FakeClaude())
    assert chat.setModel("claude") == "key"
    assert chat.model == "local" and given == []


def test_a_key_is_sealed_allowed_checked_and_claude_chosen(app, tmp_path):
    claude = FakeClaude()
    chat, config, given = bridge(tmp_path, claude)
    finished = []
    chat.claudeFinished.connect(lambda ok, said: finished.append((ok, said)))
    assert "begin sk-ant-" in chat.connectClaude("hello")
    assert chat.connectClaude("sk-ant-api03-" + "x" * 30) == ""
    assert pump_until(lambda: finished)
    assert finished[0][0] and chat.model == "claude" and config.chat_model == "claude"
    assert given == ["model.cloud"]
    assert chat.routeLabel == "Claude Opus 5.5 · sent to Anthropic"


def test_a_key_anthropic_refuses_is_not_kept(app, tmp_path):
    claude = FakeClaude(check="Anthropic refused the API key.")
    chat, _, _ = bridge(tmp_path, claude)
    finished = []
    chat.claudeFinished.connect(lambda ok, said: finished.append((ok, said)))
    chat.connectClaude("sk-ant-api03-" + "x" * 30)
    assert pump_until(lambda: finished)
    assert finished == [(False, "The key was not kept: Anthropic refused the API key.")]
    assert not claude.key and chat.model == "local"


def test_with_claude_chosen_claude_answers(app, tmp_path):
    claude = FakeClaude(key=True, allowed=True)
    chat, _, _ = bridge(tmp_path, claude)
    assert chat.setModel("claude") == ""
    chat.send("Which pins does SPI1 use?")
    assert pump_until(lambda: not chat.busy)
    assert chat._conversation.messages[-1].text.startswith("From Claude.")
    assert claude.asked, "the stand-in for Anthropic was asked"
    assert chat.setModel("local") == "" and chat.routeLabel != "Claude Opus 5.5 · sent to Anthropic"


def test_a_permission_taken_back_is_given_again_only_by_choosing_claude(app, tmp_path):
    claude = FakeClaude(key=True, allowed=False)
    chat, _, given = bridge(tmp_path, claude)
    assert chat.setModel("claude") == "" and given == ["model.cloud"]


def test_forgetting_the_key_goes_back_to_local(app, tmp_path):
    claude = FakeClaude(key=True, allowed=True)
    chat, config, _ = bridge(tmp_path, claude)
    chat.setModel("claude")
    said = chat.forgetClaude()
    assert "Anthropic Console" in said and not claude.key
    assert chat.model == "local" and config.chat_model == "local"


def test_work_handed_over_from_a_claude_chat_goes_to_a_team_on_claude(tmp_path):
    from akira.core.permissions import AuditLog, Policy, SecretStore
    from akira.core.agents import Trace
    from akira.core.tools import default_registry
    from akira.ui.bridge.agents import AgentsBridge
    from akira.ui.run_archive import RunArchive

    asked = []
    agents = AgentsBridge(ModelRouter(AppConfig()), default_registry(), policy=Policy,
                          audit=AuditLog(tmp_path / "audit.jsonl"),
                          secret_store=SecretStore(tmp_path / "secrets"), trace=Trace(),
                          archive=RunArchive(None), cloud=lambda: Router(asked))
    started = agents.run_team("software", "Add a driver.", str(tmp_path), cloud=True)
    assert started == ""
    assert pump_until(lambda: not agents.busy, timeout=20)
    assert asked, "the team's members were run on Claude"
    record = agents.record(agents.runs[0]["id"])
    assert set(m["label"] for m in record["models"].values()) == {"Claude Opus 5.5"}
