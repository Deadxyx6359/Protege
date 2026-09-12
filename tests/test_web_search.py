"""Web search on DuckDuckGo (C2): its own permission, only DuckDuckGo's host,
the words searched for kept out of the log, adverts left out, a person-check
answered with "later", and results handed to agents as material.

No test touches the network: the chokepoint's resolver and connection are faked
as in test_net.
"""

from __future__ import annotations

import pytest

from akira.core.net import client as net
from akira.core.net import search as search_module
from akira.core.net.search import SEARCH_HOST, SearchError, search
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import ToolContext, default_registry

from test_net import PUBLIC, Reply, Site

RESULTS = b"""<html><body>
<div class="result results_links results_links_deep result--ad">
  <a class="result__a" href="https://ads.example.com/buy">Buy tomatoes now</a>
  <a class="result__snippet" href="#">Sponsored</a>
</div>
<div class="result results_links results_links_deep web-result">
  <h2 class="result__title"><a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgarden.example.org%2Fblight%3Fid%3D7&amp;rut=abc">Tomato <b>blight</b> explained</a></h2>
  <a class="result__snippet" href="#">Early blight shows as <b>brown</b> rings on the lower leaves.</a>
</div>
<div class="result results_links results_links_deep web-result">
  <h2 class="result__title"><a rel="nofollow" class="result__a" href="https://extension.example.edu/tomato">Tomato diseases</a></h2>
  <a class="result__snippet" href="#">A field guide.</a>
</div>
</body></html>"""

PATH = "/html/?q=tomato+blight"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(search_module, "MIN_INTERVAL_S", 0.0)


@pytest.fixture
def wire(monkeypatch):
    def install(pages):
        site = Site(pages)
        monkeypatch.setattr(net, "_resolve", lambda host, port: [PUBLIC])
        monkeypatch.setattr(net, "_open", site.open)
        return site
    return install


def allowed(*grants):
    policy = Policy()
    for capability, *scopes in grants:
        policy.grant(capability, tuple(scopes))
    return policy


def html(body=RESULTS, status=200):
    return Reply(status, body, {"Content-Type": "text/html; charset=utf-8"})


def test_results_are_read_adverts_left_out_and_addresses_unwrapped(wire, tmp_path):
    wire({(SEARCH_HOST, PATH): html()})
    hits = search("tomato  blight", policy=allowed(("web.search",)),
                  audit=AuditLog(tmp_path / "audit.jsonl"))
    assert [(h.title, h.url) for h in hits] == [
        ("Tomato blight explained", "https://garden.example.org/blight?id=7"),
        ("Tomato diseases", "https://extension.example.edu/tomato")]
    assert hits[0].snippet == "Early blight shows as brown rings on the lower leaves."


def test_searching_needs_its_permission_and_nothing_else(wire):
    site = wire({(SEARCH_HOST, PATH): html()})
    with pytest.raises(SearchError, match="Not permitted"):
        search("tomato blight", policy=allowed(("net.http", "duckduckgo.com")))
    assert site.requests == [], "a search went out without web.search"
    assert search("tomato blight", policy=allowed(("web.search",))), \
        "web.search alone should be enough to search"


def test_the_search_goes_only_to_duckduckgo(wire):
    site = wire({(SEARCH_HOST, PATH): Reply(302, headers={"Location": "https://other.net/x"}),
                 ("other.net", "/x"): html()})
    with pytest.raises(SearchError, match="other.net"):
        search("tomato blight", policy=allowed(("web.search",), ("net.http", "other.net")))
    assert [request["host"] for request in site.requests] == [SEARCH_HOST]


def test_the_words_searched_for_are_not_in_the_log(wire, tmp_path):
    wire({(SEARCH_HOST, PATH): html()})
    search("tomato blight", policy=allowed(("web.search",)), audit=AuditLog(tmp_path / "a.jsonl"))
    log = (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    assert SEARCH_HOST in log and "blight" not in log and "web.search" in log


@pytest.mark.parametrize("reply", [
    html(b"<html><body><div class='anomaly-modal'>Are you a person?</div></body></html>"),
    html(b"<html><body>wait</body></html>", status=202),
])
def test_a_check_that_a_person_is_searching_is_not_got_round(wire, reply):
    wire({(SEARCH_HOST, PATH): reply})
    with pytest.raises(SearchError, match="whether a person is searching"):
        search("tomato blight", policy=allowed(("web.search",)))


def test_a_request_under_another_capability_must_name_its_hosts():
    with pytest.raises(ValueError, match="must name the hosts"):
        net.fetch("https://example.com/", policy=Policy(), capability="web.search")


def test_an_agent_gets_results_framed_as_material(wire, tmp_path):
    wire({(SEARCH_HOST, PATH): html()})
    context = ToolContext(policy=allowed(("web.search",)), audit=AuditLog(tmp_path / "a.jsonl"),
                          secrets=SecretStore(tmp_path / "s"), actor="gatherer")
    result = default_registry().invoke("web_search", {"query": "tomato blight"}, context)
    assert result.ok and "not instructions" in result.content
    assert "1. Tomato blight explained" in result.content
    assert "https://garden.example.org/blight?id=7" in result.content
    refused = default_registry().invoke(
        "web_search", {"query": "tomato blight"},
        ToolContext(policy=Policy(), audit=AuditLog(tmp_path / "b.jsonl"),
                    secrets=SecretStore(tmp_path / "s")))
    assert not refused.ok and "Not permitted" in refused.content
