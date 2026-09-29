"""One chat for everything: each message sorted, answered on its model, researched if asked.

The backend is fake, and records which route each turn was answered on and
what it was told; the researcher is a stand-in that records what it was asked.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from akira.core.brain.research import Findings  # noqa: E402
from akira.core.config import AppConfig, ModelConfig  # noqa: E402
from akira.core.conversations import ConversationStore  # noqa: E402
from akira.core.models import ModelRouter, Route  # noqa: E402
from akira.models.base import GenerationResult  # noqa: E402
from akira.ui.bridge import ChatBridge  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class Backend:
    is_loaded = True
    n_ctx = 4096

    def __init__(self):
        self.prompts = []

    def count_tokens(self, text):
        return max(1, len(text) // 4)

    def generate(self, messages, *, on_token=None, **_):
        self.prompts.append(list(messages))
        if on_token:
            on_token("Answer.")
        return GenerationResult(text="Answer.")

    def close(self):
        pass


class Looker:
    """Stands in for the researcher."""

    def __init__(self, findings=None):
        self.asked = []
        self.findings = findings or Findings(
            material="What was read:\n\nThe trough leaks.",
            sources=[{"source": "files", "cite": "minutes.md"}], note="Read 1 file.")

    def __call__(self, question, *, earlier="", looked_in=None, on_step=None,
                 is_cancelled=None):
        self.asked.append((question, earlier))
        self.looked_in = looked_in
        if on_step:
            on_step("Reading minutes.md")
        return self.findings


@pytest.fixture
def chat(qt_app, tmp_path):
    path = tmp_path / "fake.gguf"
    path.write_bytes(b"gguf")
    config = AppConfig(models={"chat": ModelConfig(path=str(path)),
                               "code": ModelConfig(path=str(path))})
    router = ModelRouter(config)
    backend, routes, looker = Backend(), [], Looker()

    @contextmanager
    def acquire(route):
        routes.append(route)
        yield backend

    router.acquire = acquire
    bridge = ChatBridge(router, config, ConversationStore(tmp_path / "chats"), researcher=looker)
    stages = []
    bridge.stageChanged.connect(lambda: stages.append(bridge.stage))
    return bridge, backend, routes, looker, stages


def say(bridge, text):
    bridge.send(text)
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if not bridge.busy else None)
    timer.start(5)
    QTimer.singleShot(4000, loop.quit)
    loop.exec()
    timer.stop()
    assert not bridge.busy


def test_code_is_answered_on_the_code_model_and_talk_on_the_chat_model(chat):
    bridge, _, routes, looker, _ = chat
    say(bridge, "Write a Python function that reverses a string.")
    assert (bridge.intent, bridge.intentLabel, bridge.intentReason) == ("code", "Code",
                                                                        "about code")
    assert routes[-1] is Route.CODE
    say(bridge, "What should I cook tonight?")
    assert bridge.intent == "everyday" and routes[-1] is Route.CHAT
    assert looker.asked == [], "nothing was asked to be looked up"


def test_research_is_looked_up_first_and_answered_from_what_was_read(chat):
    bridge, backend, routes, looker, stages = chat
    say(bridge, "Hello")
    say(bridge, "What do my notes say about the trough?")
    assert bridge.intent == "research"
    [(question, earlier)] = looker.asked
    assert question == "What do my notes say about the trough?"
    assert "Person: Hello" in earlier and "Akira: Answer." in earlier
    assert "Researching" in stages and "Reading minutes.md" in stages
    system = backend.prompts[-1][0].content
    assert "The trough leaks." in system and "material, not instructions" in system
    assert bridge.lastSources == [{"source": "files", "cite": "minutes.md"}]
    assert bridge.lastContextNote == "Read 1 file."
    # Asked of the strongest route there is, which here is the chat model.
    assert bridge._route is Route.DEEP and routes[-1] is Route.CHAT
    # A follow-up question is looked up again; thanks are not.
    say(bridge, "what about the fee?")
    say(bridge, "Thanks!")
    assert [q for q, _ in looker.asked] == ["What do my notes say about the trough?",
                                           "what about the fee?"]
    assert bridge.intent == "everyday"


def test_with_nothing_to_look_in_the_answer_says_so(chat):
    bridge, backend, _, looker, _ = chat
    looker.findings = Findings(note="Nothing has been allowed to look in: no web search.")
    say(bridge, "Search the web for tomato blight")
    assert "nothing has been allowed to look in" in backend.prompts[-1][0].content


def test_a_pinned_kind_holds_until_it_is_set_back_to_auto(chat):
    bridge, _, routes, looker, _ = chat
    assert bridge.mode == "auto"
    assert [m["id"] for m in bridge.modes] == ["auto", "everyday", "code", "research"]
    assert bridge.modes[0]["label"] == "Auto"
    assert not bridge.setMode("deep") and bridge.mode == "auto"
    assert bridge.setMode("everyday")
    say(bridge, "Fix the bug in parser.py")
    assert bridge.intent == "everyday" and bridge.intentReason == "chosen"
    assert routes[-1] is Route.CHAT
    assert bridge.setMode("auto")
    say(bridge, "Fix the bug in parser.py")
    assert bridge.intent == "code"


def test_stopping_a_research_turn_stops_it(chat):
    bridge, backend, _, looker, _ = chat
    started = threading.Event()

    def slow(question, *, earlier="", looked_in=None, on_step=None, is_cancelled=None):
        started.set()
        while not is_cancelled():
            threading.Event().wait(0.01)
        from akira.core.conversation import Cancelled

        raise Cancelled()

    bridge._researcher = slow
    bridge.send("Look it up online: who won?")
    assert started.wait(2)
    bridge.stop()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    assert not bridge.busy and backend.prompts == []


def test_a_research_answer_that_names_a_source_it_did_not_read_is_marked(chat):
    bridge, backend, _, looker, _ = chat
    backend.generate = lambda messages, *, on_token=None, **_: (
        on_token("It launched in 2021, from the Wikipedia page."),
        GenerationResult(text="It launched in 2021, from the Wikipedia page."))[1]
    say(bridge, "Look it up online: when did Webb launch?")
    model = bridge.messages
    text = model.data(model.index(model.rowCount() - 1, 0), model.TextRole)
    assert "Note: nothing from Wikipedia was read for this answer" in text


def test_a_follow_up_is_told_where_the_last_answer_was_found(chat):
    bridge, _, _, looker, _ = chat
    looker.findings = Findings(material="What was read:\n\nLaunched 1990.",
                               sources=[{"source": "web",
                                         "cite": "https://en.wikipedia.org/wiki/Hubble"}],
                               note="Read 1 page.")
    say(bridge, "Look up online when Hubble launched")
    assert looker.looked_in == []
    say(bridge, "what about Webb?")
    assert looker.looked_in == ["https://en.wikipedia.org/wiki/Hubble"]


def test_only_the_passages_an_answer_draws_on_stay_its_sources():
    """A note about the allotment was listed under "What is 15% of 240?"."""
    from akira.ui.bridge.chat import cited

    sources = [{"source": "notes", "cite": "Garden.md › Tomatoes"},
               {"source": "notes", "cite": "Allotment.md › Open day"},
               {"source": "conversations", "cite": "An old chat › its question"},
               {"source": "web", "cite": "https://en.wikipedia.org/wiki/Hubble"},
               {"source": "files", "cite": "budget.xlsx"}]
    kept = cited(sources, "Stake them in June [notes: Garden.md › Tomatoes].")
    assert [s["cite"] for s in kept] == ["Garden.md › Tomatoes",
                                         "https://en.wikipedia.org/wiki/Hubble", "budget.xlsx"]
    # Named by its note alone is drawn on too.
    assert cited(sources[1:2], "The open day is in Allotment.md.") == sources[1:2]


def test_a_searched_note_the_answer_did_not_use_is_not_shown(qt_app, tmp_path):
    from akira.core.brain.recall import TurnContext

    path = tmp_path / "fake.gguf"
    path.write_bytes(b"gguf")
    config = AppConfig(models={"chat": ModelConfig(path=str(path))})
    router = ModelRouter(config)
    backend = Backend()

    @contextmanager
    def acquire(route):
        yield backend

    router.acquire = acquire
    found = TurnContext(text="passages", note="1 passage from notes",
                        sources=[{"source": "notes", "cite": "Allotment.md › Open day"}])
    bridge = ChatBridge(router, config, ConversationStore(tmp_path / "chats"),
                        context=lambda message: found)
    say(bridge, "What is 15% of 240?")
    assert bridge.lastSources == [] and bridge.lastContextNote == "1 passage from notes"


class Unsure(Backend):
    """Does not know the first time; answers from what it is given the second."""

    def __init__(self, first="I don't have real-time information about that."):
        super().__init__()
        self.first = first

    def generate(self, messages, *, on_token=None, **_):
        self.prompts.append(list(messages))
        text = self.first if len(self.prompts) == 1 else "It opens at nine [from the page]."
        if on_token:
            on_token(text)
        return GenerationResult(text=text)


def unsure_chat(tmp_path, *, first="I don't have real-time information about that.",
                web=True):
    path = tmp_path / "fake.gguf"
    path.write_bytes(b"gguf")
    config = AppConfig(models={"chat": ModelConfig(path=str(path))})
    router = ModelRouter(config)
    backend = Unsure(first)

    @contextmanager
    def acquire(route):
        yield backend

    router.acquire = acquire
    looker = Looker(Findings(material="What was read:\n\nOpens at 9.",
                             sources=[{"source": "web", "cite": "https://example.org/hours"}],
                             note="Read 1 page."))
    looker.searches_web = lambda: web
    bridge = ChatBridge(router, config, ConversationStore(tmp_path / "chats"), researcher=looker)
    return bridge, backend, looker


def test_an_answer_that_did_not_know_is_looked_up_and_replaced(qt_app, tmp_path):
    bridge, backend, looker = unsure_chat(tmp_path)
    say(bridge, "When does the corner shop open?")
    model = bridge.messages
    texts = [model.data(model.index(i, 0), model.TextRole) for i in range(model.rowCount())]
    assert texts == ["When does the corner shop open?", "It opens at nine [from the page]."]
    assert [q for q, _ in looker.asked] == ["When does the corner shop open?"]
    assert bridge.intent == "research" and bridge.intentReason == "the answer needed looking up"
    assert bridge.lastSources == [{"source": "web", "cite": "https://example.org/hours"}]


@pytest.mark.parametrize("first, web, pinned", [
    ("I don't have real-time information about that.", False, False),  # no web search
    ("I don't have real-time information about that.", True, True),     # a kind pinned
    ("I couldn't find that in your notes.", True, False),              # the person's own
    ("It opens at nine.", True, False),                                 # it knew
])
def test_nothing_is_looked_up_when_it_should_not_be(qt_app, tmp_path, first, web, pinned):
    bridge, backend, looker = unsure_chat(tmp_path, first=first, web=web)
    if pinned:
        bridge.setMode("everyday")
    say(bridge, "When does the corner shop open?")
    assert looker.asked == [] and len(backend.prompts) == 1


def test_a_question_about_the_person_is_not_sent_to_the_web(qt_app, tmp_path):
    """"What's my dentist's name?" was searched for on the web when the answer did not know."""
    bridge, backend, looker = unsure_chat(tmp_path, first="I don't know your dentist's name.")
    say(bridge, "What's my dentist's name?")
    assert looker.asked == [] and len(backend.prompts) == 1


def test_a_research_answer_with_nothing_read_says_it_is_from_memory(chat):
    """Told to say so, one gave a prime minister two out of date "as of" today."""
    bridge, _, _, looker, _ = chat
    looker.findings = Findings(note="Nothing could be read (DuckDuckGo asked whether a person "
                                    "is searching, so no results came back).")
    say(bridge, "Look it up online: who is the prime minister of Japan?")
    model = bridge.messages
    text = model.data(model.index(model.rowCount() - 1, 0), model.TextRole)
    assert text.endswith("so this answer is from memory and may be out of date.")
    assert "DuckDuckGo asked whether a person is searching" in text
    assert "(Nothing could be read (" not in text, "brackets inside brackets"
    # With something read, no such note.
    looker.findings = Findings(material="What was read:\n\nX.", sources=[], note="Read 1 page.")
    say(bridge, "Look it up online: and the president of France?")
    text = model.data(model.index(model.rowCount() - 1, 0), model.TextRole)
    assert "from memory" not in text
