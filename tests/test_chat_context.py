"""The chat turn's context (B4/B6): what the assembler finds reaches the model for
that turn only, what was used is shown, and a failure to look costs the context,
never the answer.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

pytest.importorskip("PySide6", reason="the Qt interface is optional for the old app")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from akira.core.brain.recall import TurnContext  # noqa: E402
from akira.core.config import AppConfig, ModelConfig  # noqa: E402
from akira.core.conversation import DEFAULT_SYSTEM_PROMPT  # noqa: E402
from akira.core.conversations import ConversationStore  # noqa: E402
from akira.core.models import ModelRouter  # noqa: E402
from akira.models.base import GenerationResult  # noqa: E402
from akira.ui.bridge import ChatBridge  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class Recorder:
    """Answers at once, keeping every prompt it was sent."""

    is_loaded = True
    n_ctx = 4096

    def __init__(self):
        self.prompts = []

    def count_tokens(self, text):
        return max(1, len(text) // 4)

    def generate(self, messages, *, on_token=None, **_):
        self.prompts.append(list(messages))
        if on_token is not None:
            on_token("Answer.")
        return GenerationResult(text="Answer.")

    def close(self):
        pass


def bridge_with(tmp_path, backend, context):
    model = tmp_path / "fake.gguf"
    model.write_bytes(b"gguf-placeholder")
    config = AppConfig(models={"chat": ModelConfig(path=str(model), max_tokens=64)})
    router = ModelRouter(config)

    @contextmanager
    def acquire(route):
        yield backend

    router.acquire = acquire  # type: ignore[method-assign]
    return ChatBridge(router, config, ConversationStore(tmp_path / "conversations"),
                      context=context)


def pump_until(predicate, timeout_ms=4000):
    loop = QEventLoop()
    elapsed = {"ms": 0}

    def tick():
        elapsed["ms"] += 10
        if predicate() or elapsed["ms"] >= timeout_ms:
            loop.quit()

    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(tick)
    timer.start()
    loop.exec()
    timer.stop()
    return predicate()


def last_text(bridge):
    model = bridge.messages
    return model.data(model.index(model.rowCount() - 1, 0), model.TextRole)


def test_the_turns_context_reaches_the_model_and_is_not_saved(qt_app, tmp_path):
    backend, asked = Recorder(), []

    def context(message):
        asked.append(message)
        return TurnContext("PASSAGES GO HERE",
                           [{"source": "notes", "cite": "Garden.md › Tomatoes"}],
                           "1 passage from notes")

    bridge = bridge_with(tmp_path, backend, context)
    bridge.send("when do I stake the tomatoes")
    assert pump_until(lambda: not bridge.busy), "the turn never finished"

    assert asked == ["when do I stake the tomatoes"]
    assert backend.prompts[0][0].content.endswith("PASSAGES GO HERE")
    assert bridge.lastSources == [{"source": "notes", "cite": "Garden.md › Tomatoes"}]
    assert bridge.lastContextNote == "1 passage from notes"
    saved = ConversationStore(tmp_path / "conversations").load(bridge.conversationId)
    assert "PASSAGES GO HERE" not in saved.system_prompt


def test_failing_to_look_costs_the_context_not_the_answer(qt_app, tmp_path):
    def broken(message):
        raise RuntimeError("the index is locked")

    bridge = bridge_with(tmp_path, Recorder(), broken)
    bridge.send("hello there")
    assert pump_until(lambda: not bridge.busy)
    assert last_text(bridge) == "Answer."
    assert "the index is locked" in bridge.lastContextNote and bridge.lastSources == []


def test_without_an_assembler_the_turn_is_as_before(qt_app, tmp_path):
    backend = Recorder()
    bridge = bridge_with(tmp_path, backend, None)
    bridge.send("hello")
    assert pump_until(lambda: not bridge.busy)
    assert last_text(bridge) == "Answer."
    assert backend.prompts[0][0].content == DEFAULT_SYSTEM_PROMPT
    assert bridge.lastSources == [] and bridge.lastContextNote == ""
