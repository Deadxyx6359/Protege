"""A conversation is filed under the project open when it began (B6), so what is
distilled from it is proposed under that project's name.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

pytest.importorskip("PySide6", reason="the Qt interface is optional for the old app")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from protege.core.config import AppConfig, ModelConfig  # noqa: E402
from protege.core.conversations import ConversationStore  # noqa: E402
from protege.core.models import ModelRouter  # noqa: E402
from protege.models.base import GenerationResult  # noqa: E402
from protege.ui.bridge import ChatBridge  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class Instant:
    is_loaded = True
    n_ctx = 4096

    def count_tokens(self, text):
        return max(1, len(text) // 4)

    def generate(self, messages, *, on_token=None, **_):
        if on_token is not None:
            on_token("Fine.")
        return GenerationResult(text="Fine.")

    def close(self):
        pass


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


def chat(tmp_path, **kwargs):
    model = tmp_path / "fake.gguf"
    model.write_bytes(b"gguf-placeholder")
    config = AppConfig(models={"chat": ModelConfig(path=str(model), max_tokens=64)})
    router = ModelRouter(config)

    @contextmanager
    def acquire(route):
        yield Instant()

    router.acquire = acquire  # type: ignore[method-assign]
    store = ConversationStore(tmp_path / "conversations")
    return ChatBridge(router, config, store, **kwargs), store


def test_a_conversation_keeps_the_project_it_began_in(qt_app, tmp_path):
    open_project = {"id": "0123456789abcdef"}
    bridge, store = chat(tmp_path, project=lambda: open_project["id"])
    bridge.send("first question")
    assert pump_until(lambda: not bridge.busy)

    open_project["id"] = "fedcba9876543210"
    bridge.send("second question")
    assert pump_until(lambda: not bridge.busy)
    assert store.load(bridge.conversationId).project == "0123456789abcdef"


def test_outside_any_project_a_conversation_has_none(qt_app, tmp_path):
    bridge, store = chat(tmp_path)
    bridge.send("a question")
    assert pump_until(lambda: not bridge.busy)
    assert store.load(bridge.conversationId).project == ""
