"""Looking something up for a chat turn: the gatherer reads, and what it read goes on.

The model is scripted; the tools, the permissions and the trace are real.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from akira.core.brain.research import MAX_MATERIAL, NOTHING, PREAMBLE, Researcher, material
from akira.core.conversation import Cancelled
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import default_registry


class Scripted:
    def __init__(self, replies, stop_after=None):
        self.replies = list(replies)
        self.prompts = []

    @contextmanager
    def acquire(self, route):
        yield self

    def generate(self, messages, *, on_token=None, **_):
        self.prompts.append(list(messages))
        reply = self.replies.pop(0) if self.replies else "Done."
        if on_token:
            on_token(reply)
        return reply


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "Garden"
    root.mkdir()
    (root / "minutes.md").write_text("The trough leaks; Tom fixes it by 1 Oct.\n"
                                     "The fee rises from £40 to £46.\n", encoding="utf-8")
    return root


def researcher(tmp_path, policy, router):
    return Researcher(router=router, registry=default_registry(), policy=lambda: policy,
                      audit=AuditLog(tmp_path / "audit.jsonl"),
                      secrets=SecretStore(tmp_path / "secrets"))


def test_what_was_read_goes_on_whole_with_where_it_came_from(tmp_path, folder):
    policy = Policy()
    policy.grant("files.read", (str(folder),))
    read = ('<tool_call>{"name": "read_file", "arguments": {"path": "%s"}}</tool_call>'
            % (folder / "minutes.md").as_posix())
    router = Scripted([read, "minutes.md: the trough leaks."])
    steps = []
    findings = researcher(tmp_path, policy, router)("What did the committee decide?",
                                                    earlier="Person: hello", on_step=steps.append)
    # The summary left out the fee; the file as read did not.
    assert "£40 to £46" in findings.material and "the trough leaks." in findings.material
    assert findings.material.index("What was read:") < findings.material.index(
        "What the gatherer made of it:")
    assert findings.sources == [{"source": "files", "cite": "minutes.md"}]
    assert steps == ["Reading minutes.md"] and findings.note == "Read 1 file."
    assert findings.for_prompt().startswith(PREAMBLE)
    # It was told where it may read, and what the question follows.
    system, task = router.prompts[0][0].content, router.prompts[0][1].content
    assert str(folder) in system and "Person: hello" in task


def test_with_nothing_allowed_to_look_in_it_says_so_and_runs_nothing(tmp_path):
    router = Scripted([])
    findings = researcher(tmp_path, Policy(), router)("Who won the 2026 World Cup?")
    assert not findings.found and router.prompts == []
    assert "nothing has been allowed to look in" in findings.for_prompt()
    assert findings.for_prompt().startswith(NOTHING.split("{}")[0])


def test_stopping_it_stops_the_turn(tmp_path, folder):
    policy = Policy()
    policy.grant("files.read", (str(folder),))
    with pytest.raises(Cancelled):
        researcher(tmp_path, policy, Scripted(["Thinking."]))("What?", is_cancelled=lambda: True)


def test_it_only_reads_and_what_would_ask_is_refused(tmp_path, folder):
    """A gatherer has no tool that writes; if one ever did, the confirm refuses."""
    policy = Policy()
    policy.grant("files.read", (str(folder),))
    policy.grant("files.write", (str(folder),))
    write = ('<tool_call>{"name": "write_file", "arguments": {"path": "%s", "content": "x"}}'
             '</tool_call>' % (folder / "new.md").as_posix())
    researcher(tmp_path, policy, Scripted([write, "Nothing."]))("Anything?")
    assert not (folder / "new.md").exists()


def test_pages_come_before_searches_and_the_summary_is_cut_first():
    read = [("web_search", "1. A result"), ("fetch_page", "The page."), ("read_file", "A file.")]
    text = material(read, "summary " * 5000)
    assert text.index("The page.") < text.index("A file.") < text.index("1. A result")
    assert len(text) <= MAX_MATERIAL and "What the gatherer made of it:" in text


def test_a_long_page_is_cut_to_what_bears_on_the_question():
    """Wikipedia's Hubble article spends 3,500 characters on menus first."""
    from akira.core.excerpt import excerpt

    menu = "\n\n".join(f"- Menu item {n}" for n in range(400))
    page = (f"Hubble - Wikipedia\n\n{menu}\n\nHubble was launched on 24 April 1990 aboard the "
            "Space Shuttle Discovery, on mission STS-31.\n\n" + "Other history. " * 300)
    cut = excerpt(page, "When did Hubble launch, and on what?", 2000)
    assert len(cut) <= 2000 and cut.startswith("Hubble - Wikipedia")
    assert "24 April 1990 aboard the Space Shuttle Discovery" in cut
    assert excerpt("short", "anything", 100) == "short"


def test_a_source_the_answer_names_but_did_not_read_is_noted():
    from akira.core.brain.research import unread_note

    read = [{"source": "files", "cite": "budget.xlsx"}]
    assert unread_note("From budget.xlsx: 81.1.", read) == ""
    note = unread_note("This is from the Wikipedia page, and plan.docx says 120.", read)
    assert "nothing from Wikipedia, plan.docx was read" in note and "from memory" in note
    web = [{"source": "web", "cite": "https://en.wikipedia.org/wiki/Hubble_Space_Telescope"}]
    assert unread_note("From the Wikipedia page on Hubble.", web) == ""


def test_an_answer_from_search_results_is_not_said_to_be_from_memory():
    """Only Wikipedia's search results were read, and the note said "from memory"."""
    from akira.core.brain.research import noted, only_searched, unread_note

    note = unread_note("78.37 °C, according to Wikipedia.", [], searched=True)
    assert "only search results were read" in note and "from memory" not in note
    assert only_searched(noted([("web_search", "1. Ethanol")], []))
    assert noted([("web_search", "a"), ("web_search", "b")], []) == "Read 2 searches."
    assert not only_searched(noted([("web_search", "a"), ("fetch_page", "b")], []))
    assert not only_searched("Nothing could be read (DuckDuckGo asked).")


def test_a_page_given_and_not_read_is_said_to_be_unread_not_answered_from_memory():
    """Told to answer from memory, it said "I cannot access external websites" and gave
    the news "as of my last update"."""
    from akira.core.brain.research import Findings

    prompt = Findings(note="Nothing could be read (the person said no to it).",
                      given=True).for_prompt()
    assert prompt.startswith("The person gave a page to read, but nothing could be read")
    assert "answer from what you know" not in prompt


def test_a_follow_up_is_sent_first_to_where_the_last_answer_was_found(tmp_path):
    from akira.core.brain.research import where_to_look

    assert where_to_look([]) == ""
    told = where_to_look(["https://en.wikipedia.org/wiki/Hubble_Space_Telescope", "budget.xlsx"])
    assert "Start on en.wikipedia.org" in told and "index.php?search=" in told
    assert "Start with budget.xlsx" in told
    policy = Policy()
    policy.grant("net.http", ("en.wikipedia.org",))
    router = Scripted(["Nothing."])
    researcher(tmp_path, policy, router)(
        "what about Webb?", looked_in=["https://en.wikipedia.org/wiki/Hubble_Space_Telescope"])
    task = router.prompts[0][1].content
    assert task.startswith("Start on en.wikipedia.org"), "the direction was not first"


# -- a page given in the question ------------------------------------------------------------

TURING = (b"<html><head><title>Alan Turing</title></head><body><p>Alan Turing was born in "
          b"Maida Vale, London.</p></body></html>")


@pytest.fixture
def pages(monkeypatch):
    from akira.core.net import client as net
    from test_net import PUBLIC, Reply, Site

    fake = Site({("en.wikipedia.org", "/wiki/Alan_Turing"):
                 Reply(200, TURING, {"Content-Type": "text/html"})})
    monkeypatch.setattr(net, "_resolve", lambda host, port: [PUBLIC])
    monkeypatch.setattr(net, "_open", fake.open)
    return fake


def test_a_page_given_in_the_question_is_read_and_nothing_is_searched(tmp_path, pages):
    """Given a Wikipedia page, chat said it "cannot access external links"; research
    searched Wikipedia for it instead of reading it."""
    policy = Policy()
    policy.grant("net.http", ("en.wikipedia.org",))
    policy.grant("web.search")
    router = Scripted([])
    steps = []
    findings = researcher(tmp_path, policy, router)(
        "Read https://en.wikipedia.org/wiki/Alan_Turing and tell me where he was born.",
        on_step=steps.append)
    assert "Maida Vale" in findings.material and router.prompts == []
    assert findings.sources == [{"source": "web",
                                 "cite": "https://en.wikipedia.org/wiki/Alan_Turing"}]
    assert steps == ["Reading en.wikipedia.org"] and findings.note == "Read 1 page."


def test_a_page_on_a_site_not_allowed_is_asked_about_and_no_is_said(tmp_path, pages):
    """Given a BBC page, research searched Wikipedia, and the person was never asked."""
    policy = Policy()
    policy.grant("net.http", ("en.wikipedia.org",))
    asked = []

    def ask(request):
        asked.append(request)
        return "no"

    found = Researcher(router=Scripted([]), registry=default_registry(), policy=lambda: policy,
                       audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"), ask=ask)(
        "What is the top story on https://www.bbc.co.uk/news right now?")
    assert [request.scope for request in asked] == ["www.bbc.co.uk"]
    assert not found.found and pages.requests == []
    assert found.note.startswith("Nothing could be read (Not permitted") and "said no" in found.note
    # Said as it is: told why, the model still said it "cannot access external websites".
    assert found.said == ("I didn't read https://www.bbc.co.uk/news, because you said no when "
                          "I asked to read www.bbc.co.uk.")


def test_why_a_page_was_not_read_is_said_plainly():
    from akira.core.brain.research import not_read

    assert not_read("https://www.bbc.co.uk/news", "Not permitted: www.bbc.co.uk is outside "
                    "what Fetch web pages was allowed for.") == (
        "I couldn't read https://www.bbc.co.uk/news: reading www.bbc.co.uk isn't allowed. To "
        "let me, choose Allow when I ask, or add the site in Settings → Permissions.")
    assert not_read("https://example.org/gone", "https://example.org/gone answered 404 Not "
                    "Found.") == ("I couldn't read https://example.org/gone: "
                                  "https://example.org/gone answered 404 Not Found.")


@pytest.mark.parametrize("question, wanted", [
    ("Read https://en.wikipedia.org/wiki/Alan_Turing.", ["https://en.wikipedia.org/wiki/Alan_Turing"]),
    ("see (https://en.wikipedia.org/wiki/Mercury_(planet)).",
     ["https://en.wikipedia.org/wiki/Mercury_(planet)"]),
    ("https://a.org/x, https://b.org/y; https://b.org/y", ["https://a.org/x", "https://b.org/y"]),
    ("no address here", []),
])
def test_the_pages_given_are_found_without_the_punctuation_after_them(question, wanted):
    from akira.core.brain.research import given_pages
    assert given_pages(question) == wanted
