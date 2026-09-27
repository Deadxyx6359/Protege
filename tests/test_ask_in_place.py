"""Asking the person, in place, for a site or folder next to the ones allowed."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from akira.core.config import config_dir
from akira.core.net import host_of
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.permissions import asking
from akira.core.permissions.asking import (ALWAYS, MAX_ASKS, NO, ONCE, SEARCH_FIRST, Allowances,
                                           note_seen, secret_place, widen)
from akira.core.tools.registry import ToolRegistry
from akira.core.tools.schema import Parameter, Requirement, Tool, ToolContext, ToolResult


def _reader(capability: str, argument: str, scope_of=None) -> Tool:
    return Tool(name=f"read_{capability.replace('.', '_')}", summary="Read something.",
                parameters=(Parameter(argument, "string", "Where."),),
                requires=(Requirement(capability, scope_from=argument, scope_of=scope_of),),
                run=lambda arguments, context: ToolResult.success(f"read {arguments[argument]}"))


@pytest.fixture
def registry():
    registry = ToolRegistry()
    registry.register(_reader("net.http", "url", host_of))
    registry.register(_reader("files.read", "path"))
    registry.register(_reader("web.browse", "url", host_of))
    return registry


class Asker:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def __call__(self, request):
        self.asked.append(request)
        return self.answers.pop(0) if self.answers else NO


def context_for(policy, asker=None):
    return ToolContext(policy=policy, audit=AuditLog(), secrets=SecretStore(), actor="researcher",
                       ask_scope=asker)


def web_policy():
    policy = Policy()
    policy.grant("net.http", ("en.wikipedia.org",))
    return policy


PAGE = "https://www.bbc.co.uk/news/science-12345"


def test_an_address_the_model_made_up_is_refused_without_asking(registry):
    asker = Asker(ONCE)
    context = context_for(web_policy(), asker)
    result = registry.invoke("read_net_http", {"url": PAGE}, context)
    assert not result.ok and SEARCH_FIRST in result.content
    assert asker.asked == []


def test_a_site_from_a_search_result_is_asked_about_and_allowed_once(registry):
    asker = Asker(ONCE)
    policy = web_policy()
    context = context_for(policy, asker)
    note_seen(context, f"1. BBC science\n   {PAGE}\n")

    result = registry.invoke("read_net_http", {"url": PAGE}, context)
    assert result.ok, result.content
    (request,) = asker.asked
    assert (request.scope, request.always, request.detail) == ("www.bbc.co.uk", "bbc.co.uk", PAGE)
    assert request.title == "Read a page on www.bbc.co.uk?"

    # Once covers the rest of this piece of work, and is saved nowhere.
    other = "https://www.bbc.co.uk/news/other"
    assert registry.invoke("read_net_http", {"url": other}, context).ok
    assert len(asker.asked) == 1
    assert isinstance(context.policy, Allowances)
    assert not policy.allows("net.http", "www.bbc.co.uk")
    assert not context_for(policy).policy.allows("net.http", "www.bbc.co.uk")


def test_an_address_the_person_gave_counts_as_seen(registry):
    from akira.core.agents import loop  # the loop notes the task's addresses
    asker = Asker(ONCE)
    context = context_for(web_policy(), asker)
    loop.note_seen(context, f"Summarise {PAGE} for me")
    assert registry.invoke("read_net_http", {"url": PAGE + "#top"}, context).ok


def test_no_is_final_and_not_asked_again(registry):
    asker = Asker(NO, ONCE)
    context = context_for(web_policy(), asker)
    note_seen(context, PAGE)
    first = registry.invoke("read_net_http", {"url": PAGE}, context)
    assert not first.ok and "the person said no" in first.content
    second = registry.invoke("read_net_http", {"url": PAGE}, context)
    assert not second.ok and len(asker.asked) == 1


def test_without_a_way_to_ask_it_is_refused_as_before(registry):
    context = context_for(web_policy(), None)
    note_seen(context, PAGE)
    result = registry.invoke("read_net_http", {"url": PAGE}, context)
    assert not result.ok and "Settings" in result.content


def test_only_reading_what_is_granted_somewhere_is_asked_about(registry):
    asker = Asker(ONCE, ONCE)
    policy = web_policy()
    policy.grant("web.browse", ("en.wikipedia.org",))
    context = context_for(policy, asker)
    note_seen(context, PAGE)
    # Driving a browser is not asked about.
    assert not registry.invoke("read_web_browse", {"url": PAGE}, context).ok
    # Nor is reading files when no folder is allowed at all.
    assert not registry.invoke("read_files_read", {"path": str(Path.cwd())}, context).ok
    assert asker.asked == []


def test_a_piece_of_work_asks_only_a_few_times(registry):
    asker = Asker(*[NO] * (MAX_ASKS + 3))
    context = context_for(web_policy(), asker)
    pages = [f"https://site{i}.example.org/page" for i in range(MAX_ASKS + 2)]
    note_seen(context, "\n".join(pages))
    for page in pages:
        registry.invoke("read_net_http", {"url": page}, context)
    assert len(asker.asked) == MAX_ASKS


def test_a_folder_is_asked_about_and_always_names_its_folder(registry, tmp_path, monkeypatch):
    # The test's own folder is in application data, which is never asked about.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    allowed = tmp_path / "allowed"
    other = tmp_path / "other"
    allowed.mkdir(); other.mkdir()
    (other / "notes.txt").write_text("x", encoding="utf-8")
    policy = Policy()
    policy.grant("files.read", (str(allowed),))
    asker = Asker(ONCE)
    context = context_for(policy, asker)

    assert registry.invoke("read_files_read", {"path": str(other / "notes.txt")}, context).ok
    (request,) = asker.asked
    assert request.always == str(other)
    assert request.title == "Read notes.txt?"


@pytest.mark.parametrize("where", [
    lambda: str(Path.home() / ".ssh" / "id_rsa"),
    lambda: str(Path.home() / "AppData" / "Local" / "Google"),
    lambda: str(Path.home()),
    lambda: str(Path(Path.home().anchor)),
    lambda: str(config_dir() / "permissions.json"),
])
def test_secret_places_are_never_asked_about(registry, tmp_path, where):
    path = where()
    assert secret_place(path)
    policy = Policy()
    policy.grant("files.read", (str(tmp_path),))
    asker = Asker(ONCE)
    result = registry.invoke("read_files_read", {"path": path}, context_for(policy, asker))
    assert not result.ok and asker.asked == []


def test_always_widens_the_grant_and_keeps_its_expiry():
    policy = Policy()
    expires = time.time() + 3600
    policy.grant("net.http", ("en.wikipedia.org",), expires=expires, note="kept")
    widen(policy, "net.http", "bbc.co.uk")
    grant = policy.granted("net.http")
    assert grant.scopes == ("en.wikipedia.org", "bbc.co.uk") and grant.expires == expires
    assert policy.allows("net.http", "www.bbc.co.uk")
    with pytest.raises(ValueError):
        widen(policy, "files.read", "C:/")


def test_what_is_allowed_once_cannot_be_saved():
    overlay = Allowances(web_policy())
    with pytest.raises(RuntimeError):
        overlay.save()
    overlay.add("net.http", "www.bbc.co.uk")
    assert overlay.granted("net.http").scopes == ("en.wikipedia.org", "www.bbc.co.uk")


# -- the bridge ------------------------------------------------------------------------------


qt = pytest.importorskip("PySide6", reason="the Qt interface is optional")


def _request():
    return asking.Request("net.http", "www.bbc.co.uk", PAGE, "bbc.co.uk", "researcher",
                          "Read a web page.")


def _answer_from_ui(bridge, choice):
    """Ask on a worker, as agents do, and answer when the question arrives."""
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    got = []
    bridge.requested.connect(lambda token, request: (got.append(request),
                                                     bridge.answer(token, choice)))
    result = []
    worker = threading.Thread(target=lambda: result.append(bridge.ask(_request())))
    worker.start()
    deadline = time.monotonic() + 5
    while worker.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    worker.join(1)
    return result[0], got


def test_the_bridge_saves_always_through_the_grant():
    from akira.ui.bridge.permissions import AllowBridge
    widened = []
    bridge = AllowBridge(extend=lambda capability, scope: widened.append((capability, scope)) or "")
    answer, got = _answer_from_ui(bridge, ALWAYS)
    assert answer == ALWAYS and widened == [("net.http", "bbc.co.uk")]
    assert got[0]["kind"] == "site" and got[0]["always"] == "bbc.co.uk"


def test_always_that_cannot_be_saved_is_once():
    from akira.ui.bridge.permissions import AllowBridge
    bridge = AllowBridge(extend=lambda capability, scope: "not granted there")
    assert _answer_from_ui(bridge, ALWAYS)[0] == ONCE


def test_the_bridge_answers_no_from_the_interface_thread_and_when_closing():
    from akira.ui.bridge.permissions import AllowBridge
    bridge = AllowBridge()
    assert bridge.ask(_request()) == NO
    bridge.close()
    assert _answer_from_ui(bridge, ONCE)[0] == NO


def test_the_permissions_bridge_widens_and_records_it(tmp_path, monkeypatch):
    from akira.ui.bridge.permissions import PermissionsBridge
    monkeypatch.setattr(Policy, "path", staticmethod(lambda: tmp_path / "permissions.json"))
    audit = AuditLog()
    bridge = PermissionsBridge(web_policy(), audit)
    assert bridge.widen("net.http", "bbc.co.uk") == ""
    assert Policy.load().allows("net.http", "news.bbc.co.uk")
    assert bridge.widen("files.read", "C:/") != ""


# -- in an agent's work ----------------------------------------------------------------------


def _agent(replies, context, registry):
    from akira.core.agents import Agent, AgentSpec, Trace
    from tests.test_agents import ScriptedRouter
    agent = Agent(AgentSpec(name="tester", role="You are a test agent."),
                  router=ScriptedRouter(replies), registry=registry, context=context,
                  trace=Trace())
    return agent


def _call(url):
    return '<tool_call>{"name": "read_net_http", "arguments": {"url": "%s"}}</tool_call>' % url


def test_an_agent_told_to_search_first_goes_on(registry, monkeypatch, tmp_path):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))
    context = context_for(web_policy(), Asker(ONCE))
    outcome = _agent([_call(PAGE), "I could not open it, so I will say so."], context,
                     registry).run("What is new in science?")
    # Not stopped at the refusal, as a final no would be: it went on to answer.
    assert outcome.steps > 1 and outcome.ok and "Not permitted" not in outcome.answer


def test_a_page_the_person_named_is_asked_about_in_an_agents_work(registry, monkeypatch, tmp_path):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))
    asker = Asker(ONCE)
    context = context_for(web_policy(), asker)
    outcome = _agent([_call(PAGE), "It says hello."], context, registry).run(
        f"Summarise {PAGE}")
    assert outcome.ok and len(asker.asked) == 1
