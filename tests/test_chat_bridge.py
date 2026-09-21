"""The Qt bridge: threading, streaming, cancellation, and error surfacing.

A turn runs on a worker thread and reports back through queued signals, which
is the part most likely to break subtly — a missed signal shows up as a UI that
streams nothing, or one that never stops saying it is working.

The backend is fake throughout. Loading the real 13.3 GB model would exceed
this machine's free RAM, take minutes, and test llama.cpp rather than this code.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest

pytest.importorskip("PySide6", reason="the Qt interface is optional for the old app")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from akira.core.config import AppConfig, ModelConfig  # noqa: E402
from akira.core.conversations import ConversationStore  # noqa: E402
from akira.core.models import ModelRouter, Route  # noqa: E402
from akira.models.base import GenerationResult, ModelUnavailable  # noqa: E402
from akira.ui.bridge import ChatBridge  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    """One application for the module.

    Queued cross-thread signals are only delivered while an event loop runs, so
    every test here needs one to exist.
    """
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


class SlowBackend:
    """Streams on the worker thread, pausing so cancellation has a gap to land in."""

    is_loaded = True
    n_ctx = 2048

    def __init__(self, pieces, delay=0.01, fail=None):
        self.pieces = pieces
        self.delay = delay
        self.fail = fail
        self.started = threading.Event()

    def count_tokens(self, text):
        return max(1, len(text) // 4)

    def generate(self, messages, *, max_tokens=512, temperature=0.7, top_p=0.95,
                 stop=(), deadline=None, on_token=None):
        self.started.set()
        if self.fail is not None:
            raise self.fail
        for piece in self.pieces:
            if on_token is not None:
                on_token(piece)
            threading.Event().wait(self.delay)
        return GenerationResult(text="".join(self.pieces))

    def close(self):
        pass


@pytest.fixture(scope="module")
def model_file(tmp_path_factory):
    """A file that exists so the router reports a usable model.

    Pointing at a real path rather than overriding `any_usable`: that property
    is deliberately read-only, and a test that reaches around the design stops
    testing it.
    """
    path = tmp_path_factory.mktemp("models") / "fake.gguf"
    path.write_bytes(b"gguf-placeholder")
    return path


@pytest.fixture
def make_bridge(model_file, tmp_path):
    """Build a ChatBridge whose router yields  backend for every route."""

    def build(backend=None, *, configured=True):
        models = (
            {"chat": ModelConfig(path=str(model_file), max_tokens=64)}
            if configured
            else {}
        )
        config = AppConfig(models=models)
        router = ModelRouter(config)

        if backend is not None:
            @contextmanager
            def acquire(route):
                yield backend

            router.acquire = acquire  # type: ignore[method-assign]

        return ChatBridge(router, config, ConversationStore(tmp_path / "conversations"))

    return build


def pump_until(predicate, timeout_ms=4000):
    """Run the event loop until \a predicate holds, so queued signals arrive."""
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


def texts(bridge):
    model = bridge.messages
    return [
        model.data(model.index(row, 0), model.TextRole)
        for row in range(model.rowCount())
    ]


def roles(bridge):
    model = bridge.messages
    return [
        model.data(model.index(row, 0), model.RoleRole)
        for row in range(model.rowCount())
    ]


# -- the happy path ----------------------------------------------------------


def test_a_turn_streams_into_the_transcript(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["Hel", "lo ", "world"]))
    bridge.send("hi")

    assert pump_until(lambda: not bridge.busy), "the turn never finished"

    assert roles(bridge) == ["user", "assistant"]
    assert texts(bridge) == ["hi", "Hello world"]


def test_the_placeholder_exists_before_the_first_token(qt_app, make_bridge):
    """The view needs somewhere to put the stream the instant it starts."""
    bridge = make_bridge(SlowBackend(["x"], delay=0.2))
    bridge.send("hi")

    assert bridge.messages.rowCount() == 2
    assert roles(bridge) == ["user", "assistant"]

    pump_until(lambda: not bridge.busy)


def test_busy_is_set_synchronously_and_cleared_when_done(qt_app, make_bridge):
    """Set on the calling thread, so the composer switches to Stop immediately."""
    bridge = make_bridge(SlowBackend(["a"], delay=0.05))
    bridge.send("hi")

    assert bridge.busy is True
    assert pump_until(lambda: not bridge.busy)


def test_the_title_is_taken_from_the_first_question(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["ok"]))
    assert bridge.title == "New chat"

    bridge.send("How do squircles work?")
    assert bridge.title == "How do squircles work?"

    pump_until(lambda: not bridge.busy)


# -- refusing to run ---------------------------------------------------------


def test_blank_input_starts_nothing(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["x"]))
    bridge.send("   ")

    assert bridge.messages.rowCount() == 0
    assert bridge.busy is False


def test_a_second_send_while_busy_is_ignored(qt_app, make_bridge):
    """Two turns on one llama.cpp context interleave their KV cache."""
    bridge = make_bridge(SlowBackend(["a", "b"], delay=0.1))
    bridge.send("first")
    bridge.send("second")

    assert texts(bridge)[0] == "first"
    assert bridge.messages.rowCount() == 2

    pump_until(lambda: not bridge.busy)


def test_no_model_explains_itself_instead_of_failing(qt_app, make_bridge):
    """An empty screen after pressing send is indistinguishable from a crash."""
    bridge = make_bridge(configured=False)
    bridge.send("hello")

    assert bridge.ready is False
    assert bridge.messages.rowCount() == 2

    model = bridge.messages
    last = model.index(1, 0)
    assert model.data(last, model.ErrorRole) is True
    assert "No model is configured" in model.data(last, model.TextRole)
    assert bridge.busy is False


# -- stopping ----------------------------------------------------------------


def test_stop_ends_the_turn_and_keeps_partial_output(qt_app, make_bridge):
    backend = SlowBackend(["one ", "two ", "three ", "four "], delay=0.05)
    bridge = make_bridge(backend)
    bridge.send("count")

    assert backend.started.wait(2.0)
    pump_until(lambda: bool(texts(bridge)[1]), timeout_ms=2000)
    bridge.stop()

    assert pump_until(lambda: not bridge.busy), "stop did not end the turn"

    partial = texts(bridge)[1]
    assert partial, "a partial answer should survive being stopped"
    assert partial.startswith("one ")


def test_stopping_before_anything_arrives_says_so(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["a"], delay=0.05))
    bridge.send("go")
    bridge.stop()

    assert pump_until(lambda: not bridge.busy)

    model = bridge.messages
    last = model.index(1, 0)
    text = model.data(last, model.TextRole)
    assert text.startswith(("Stopped", "a"))


# -- failures ----------------------------------------------------------------


def test_a_backend_failure_is_shown_as_an_error(qt_app, make_bridge):
    """An error dressed as an answer is worse than no answer."""
    bridge = make_bridge(SlowBackend([], fail=ModelUnavailable("out of memory")))
    bridge.send("hi")

    assert pump_until(lambda: not bridge.busy)

    model = bridge.messages
    last = model.index(1, 0)
    assert model.data(last, model.ErrorRole) is True
    assert "out of memory" in model.data(last, model.TextRole)


def test_an_unexpected_exception_does_not_leave_the_ui_stuck(qt_app, make_bridge):
    """A crashed worker that never clears `busy` is an app that must be restarted."""
    bridge = make_bridge(SlowBackend([], fail=ValueError("boom")))
    bridge.send("hi")

    assert pump_until(lambda: not bridge.busy), "busy was never cleared"

    model = bridge.messages
    assert "boom" in model.data(model.index(1, 0), model.TextRole)


def test_an_empty_reply_is_reported_rather_than_shown_blank(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend([]))
    bridge.send("hi")

    assert pump_until(lambda: not bridge.busy)

    model = bridge.messages
    last = model.index(1, 0)
    assert model.data(last, model.ErrorRole) is True
    assert model.data(last, model.TextRole) == "The model returned nothing."


# -- the reply as it grows, for reading aloud --------------------------------


def test_a_reply_is_announced_as_it_grows_and_whole_at_the_end(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["Hel", "lo"]))
    grew, ended = [], []
    bridge.replyGrew.connect(grew.append)
    bridge.replyEnded.connect(lambda text: ended.append((text, bridge.busy)))
    bridge.send("hi")
    assert pump_until(lambda: not bridge.busy)
    assert grew == ["Hel", "Hello"]
    # Ended while still busy, so what waits for the chat to be idle finds it over.
    assert ended == [("Hello", True)]


@pytest.mark.parametrize("backend", [
    SlowBackend([], fail=ModelUnavailable("out of memory")),
    SlowBackend([]),
])
def test_a_failed_or_empty_reply_ends_with_nothing_to_read(qt_app, make_bridge, backend):
    bridge = make_bridge(backend)
    ended = []
    bridge.replyEnded.connect(ended.append)
    bridge.send("hi")
    assert pump_until(lambda: not bridge.busy)
    assert ended == [""]


def test_a_stopped_reply_ends_with_nothing_more_to_read(qt_app, make_bridge):
    backend = SlowBackend(["one ", "two ", "three ", "four "], delay=0.05)
    bridge = make_bridge(backend)
    ended = []
    bridge.replyEnded.connect(ended.append)
    bridge.send("count")
    assert backend.started.wait(2.0)
    bridge.stop()
    assert pump_until(lambda: not bridge.busy)
    assert ended == [""]


# -- starting over -----------------------------------------------------------


def test_new_chat_clears_the_transcript(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["ok"]))
    bridge.send("hi")
    pump_until(lambda: not bridge.busy)

    bridge.newChat()

    assert bridge.messages.rowCount() == 0
    assert bridge.title == "New chat"


# -- persistence -------------------------------------------------------------


def test_a_finished_turn_is_saved_and_appears_in_recents(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["done"]))
    bridge.send("remember this")

    assert pump_until(lambda: not bridge.busy)

    titles = [entry["title"] for entry in bridge.recents]
    assert titles == ["remember this"]


def test_starting_a_new_chat_keeps_the_old_one(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["one"]))
    bridge.send("first question")
    pump_until(lambda: not bridge.busy)

    bridge.newChat()

    assert bridge.messages.rowCount() == 0
    assert [e["title"] for e in bridge.recents] == ["first question"]


def test_a_saved_conversation_can_be_reopened(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["the answer"]))
    bridge.send("the question")
    pump_until(lambda: not bridge.busy)
    saved_id = bridge.conversationId

    bridge.newChat()
    assert bridge.messages.rowCount() == 0

    bridge.openConversation(saved_id)

    assert texts(bridge) == ["the question", "the answer"]
    assert bridge.title == "the question"


def test_deleting_the_open_conversation_clears_the_view(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["x"]))
    bridge.send("delete me")
    pump_until(lambda: not bridge.busy)

    bridge.deleteConversation(bridge.conversationId)

    assert bridge.messages.rowCount() == 0
    assert bridge.recents == []


def test_opening_an_unreadable_conversation_leaves_the_current_one_alone(qt_app, make_bridge):
    """A file that will not load must not take the window with it."""
    bridge = make_bridge(SlowBackend(["ok"]))
    bridge.send("still here")
    pump_until(lambda: not bridge.busy)

    bridge.openConversation("deadbeefdeadbeef")

    assert texts(bridge)[0] == "still here"


def test_an_abandoned_empty_chat_leaves_nothing_behind(qt_app, make_bridge):
    bridge = make_bridge(SlowBackend(["x"]))
    bridge.newChat()
    bridge.newChat()

    assert bridge.recents == []
