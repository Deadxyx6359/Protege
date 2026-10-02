"""A model on the graphics card that writes far too slowly is said to, once a session, with why.

A research answer came at half a word a second in the app, with no word why: part of
the model was running from ordinary memory, because something else was using the card.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from akira.core.config import AppConfig, ModelConfig  # noqa: E402
from akira.core.conversations import ConversationStore  # noqa: E402
from akira.core.models import ModelRouter  # noqa: E402
from akira.models.base import GenerationResult  # noqa: E402
from akira.ui.bridge import ChatBridge  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class Backend:
    is_loaded = True
    n_ctx = 4096

    def __init__(self, tokens_a_second):
        self.rate = tokens_a_second

    def count_tokens(self, text):
        return max(1, len(text) // 4)

    def generate(self, messages, *, on_token=None, **_):
        if on_token:
            on_token("An answer of some length.")
        # Sixty tokens, after a second spent reading the prompt.
        return GenerationResult(text="An answer of some length.", completion_tokens=60,
                                first_token_s=1.0, duration_s=1.0 + 60 / self.rate)

    def close(self):
        pass


def bridge_with(tmp_path, tokens_a_second, gpu_layers=-1):
    path = tmp_path / "fake.gguf"
    path.write_bytes(b"gguf")
    config = AppConfig(models={"chat": ModelConfig(path=str(path), n_gpu_layers=gpu_layers)})
    router = ModelRouter(config)
    backend = Backend(tokens_a_second)

    @contextmanager
    def acquire(route):
        yield backend

    router.acquire = acquire
    bridge = ChatBridge(router, config, ConversationStore(tmp_path / "chats"))
    told = []
    bridge.slowNoticed.connect(told.append)
    return bridge, told


def say(bridge, text):
    bridge.send(text)
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if not bridge.busy else None)
    timer.start(5)
    QTimer.singleShot(4000, loop.quit)
    loop.exec()
    timer.stop()
    QCoreApplication.processEvents()


def test_slow_writing_is_said_once_a_session_with_what_to_do(qt_app, tmp_path):
    bridge, told = bridge_with(tmp_path, tokens_a_second=1.0)
    say(bridge, "What should I cook tonight?")
    (message,) = told
    assert message.startswith("That reply came at about 0.8 words a second")
    assert "something else is using the graphics card" in message
    assert "restart Akira" in message
    say(bridge, "And for pudding?")
    assert len(told) == 1, "said once, not after every reply"


def test_writing_at_its_usual_speed_is_not_remarked_on(qt_app, tmp_path):
    bridge, told = bridge_with(tmp_path, tokens_a_second=35.0)
    say(bridge, "What should I cook tonight?")
    assert told == []


def test_on_the_processor_alone_slow_is_how_it_is(qt_app, tmp_path):
    bridge, told = bridge_with(tmp_path, tokens_a_second=1.0, gpu_layers=0)
    say(bridge, "What should I cook tonight?")
    assert told == []


def test_a_reply_too_short_to_time_is_not_judged():
    quick = GenerationResult(text="Yes.", completion_tokens=2, first_token_s=1.0, duration_s=5.0)
    assert quick.writing_rate is None
    assert GenerationResult(text="x", completion_tokens=60, first_token_s=1.0,
                            duration_s=3.0).writing_rate == 30.0


def test_a_reply_finished_with_akira_in_the_background_says_nothing_of_the_card(
        qt_app, tmp_path, monkeypatch):
    # Its window closed mid-reply, Akira runs behind every other program: slow then
    # says nothing about the card.
    from akira.core import quiet

    monkeypatch.setattr(quiet, "in_background", lambda: True)
    bridge, told = bridge_with(tmp_path, tokens_a_second=1.0)
    say(bridge, "What should I cook tonight?")
    assert told == []


class Card:
    def __init__(self, used):
        self.used = used

    def used_bytes(self):
        return self.used


def test_a_card_held_by_another_program_is_said_before_the_model_loads(qt_app, tmp_path,
                                                                        monkeypatch):
    from akira.ui.bridge import chat as chat_module

    monkeypatch.setattr(chat_module, "_card", lambda: Card(int(5.4 * 1024**3)))
    bridge, _ = bridge_with(tmp_path, tokens_a_second=35.0)
    told = []
    bridge.cardBusy.connect(told.append)
    say(bridge, "What should I cook tonight?")
    say(bridge, "And for pudding?")
    (message,) = told
    assert message.startswith("Another program is using 5.4 GB of the graphics card")


def test_a_free_card_or_a_model_on_the_processor_says_nothing(qt_app, tmp_path, monkeypatch):
    from akira.ui.bridge import chat as chat_module

    monkeypatch.setattr(chat_module, "_card", lambda: Card(150 * 1024**2))
    bridge, _ = bridge_with(tmp_path, tokens_a_second=35.0)
    told = []
    bridge.cardBusy.connect(told.append)
    say(bridge, "What should I cook tonight?")
    monkeypatch.setattr(chat_module, "_card", lambda: Card(int(5.4 * 1024**3)))
    (tmp_path / "cpu").mkdir()
    processor, _ = bridge_with(tmp_path / "cpu", tokens_a_second=35.0, gpu_layers=0)
    processor.cardBusy.connect(told.append)
    say(processor, "What should I cook tonight?")
    assert told == []
