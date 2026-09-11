"""The network chokepoint (C1): what is fetched, from where, and what is refused.

No test here touches the network. The resolver and the connection are replaced
with fakes, so every rule is checked without a packet leaving: the grant for each
site and each redirect, https only, no private addresses, the limits, what is
sent, and what is logged.
"""

from __future__ import annotations

import gzip
import time

import pytest

from protege.core.net import NetError, host_of, is_public, redact
from protege.core.net import client as net
from protege.core.permissions import AuditLog, Policy

PUBLIC = "93.184.216.34"


class Reply:
    def __init__(self, status=200, body=b"", headers=None, reason="OK", delay=0.0):
        self.status, self.reason = status, reason
        self._body, self._headers, self._delay = body, dict(headers or {}), delay

    def getheader(self, name, default=None):
        for key, value in self._headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def read(self, size):
        if self._delay:
            time.sleep(self._delay)
        piece, self._body = self._body[:size], self._body[size:]
        return piece


class Site:
    """Fake connections, answering by site and path, keeping what was asked."""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def open(self, host, address, port, timeout):
        site = self

        class Connection:
            def request(self, method, path, headers=None):
                site.requests.append({"method": method, "host": host, "address": address,
                                      "port": port, "path": path, "headers": dict(headers or {})})
                self._reply = site.pages[(host, path)]

            def getresponse(self):
                return self._reply

            def close(self):
                pass

        return Connection()


@pytest.fixture
def wire(monkeypatch):
    addresses = {"example.com": [PUBLIC], "docs.example.com": [PUBLIC], "other.net": [PUBLIC]}
    # An address written in the URL is its own answer, as in the real resolver.
    monkeypatch.setattr(net, "_resolve", lambda host, port: addresses.get(host, [host]))

    def install(pages, **resolve):
        site = Site(pages)
        monkeypatch.setattr(net, "_open", site.open)
        addresses.update({host.replace("_", "."): found for host, found in resolve.items()})
        return site

    return install


def allowed(*sites) -> Policy:
    policy = Policy()
    policy.grant("net.http", sites)
    return policy


def html(body=b"<p>Hello</p>"):
    return Reply(200, body, {"Content-Type": "text/html; charset=utf-8"})


# -- a page -----------------------------------------------------------------------------------


def test_a_granted_page_is_fetched_and_logged_without_its_query(wire, tmp_path):
    wire({("example.com", "/a?token=secret"): html()})
    audit = AuditLog(tmp_path / "audit.jsonl")
    page = net.fetch("https://example.com/a?token=secret", policy=allowed("example.com"),
                     audit=audit, actor="tester")
    assert (page.status, page.text(), page.media_type) == (200, "<p>Hello</p>", "text/html")
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "net.fetch" in log and "https://example.com/a?…" in log
    assert "secret" not in log, "the query string reached the log"


def test_what_is_sent_is_a_plain_get_to_the_checked_address(wire):
    site = wire({("example.com", "/"): html()})
    net.fetch("https://example.com", policy=allowed("example.com"))
    [sent] = site.requests
    assert (sent["method"], sent["path"], sent["address"], sent["port"]) == ("GET", "/", PUBLIC, 443)
    headers = {key.lower(): value for key, value in sent["headers"].items()}
    assert "protege" in headers["user-agent"].lower()
    assert headers["accept-encoding"] == "identity"
    assert not {"cookie", "authorization", "proxy-authorization"} & set(headers)


# -- refusals ---------------------------------------------------------------------------------


def test_nothing_is_fetched_from_a_site_nobody_allowed(wire, tmp_path):
    site = wire({("example.com", "/"): html()})
    audit = AuditLog(tmp_path / "audit.jsonl")
    with pytest.raises(NetError, match="Not permitted"):
        net.fetch("https://example.com/", policy=allowed("other.net"), audit=audit)
    assert site.requests == []
    assert '"net.fetch"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("url,reason", [
    ("http://example.com/", "Only https"),
    ("https://user:pw@example.com/", "name or password"),
    ("https:///nothing", "does not name a site"),
    ("https://example.com:notaport/", "not an address"),
    ("ftp://example.com/", "Only https"),
])
def test_only_plain_https_addresses_are_fetched(wire, url, reason):
    site = wire({("example.com", "/"): html()})
    with pytest.raises(NetError, match=reason):
        net.fetch(url, policy=allowed("example.com"))
    assert site.requests == []


@pytest.mark.parametrize("found", [
    ["192.168.1.1"], ["127.0.0.1"], ["10.0.0.5"], ["169.254.169.254"], ["::1"], ["fd00::1"],
    ["::ffff:10.0.0.1"], [PUBLIC, "127.0.0.1"], ["224.0.0.1"], ["0.0.0.0"],
])
def test_a_site_that_leads_home_or_to_a_private_network_is_refused(wire, found):
    site = wire({("example.com", "/"): html()}, example_com=found)
    with pytest.raises(NetError, match="private network"):
        net.fetch("https://example.com/", policy=allowed("example.com"))
    assert site.requests == []


def test_an_address_written_as_a_private_ip_is_refused(wire):
    site = wire({})
    with pytest.raises(NetError, match="private network"):
        net.fetch("https://10.0.0.1/", policy=allowed("10.0.0.1"))
    assert site.requests == []


# -- redirects -------------------------------------------------------------------------------


def test_a_redirect_is_followed_and_each_hop_checked(wire):
    wire({("example.com", "/"): Reply(302, headers={"Location": "https://docs.example.com/start"}),
          ("docs.example.com", "/start"): html(b"<p>Docs</p>")})
    page = net.fetch("https://example.com/", policy=allowed("example.com"))
    assert page.url == "https://docs.example.com/start" and page.hops == ("https://example.com/",)
    assert page.text() == "<p>Docs</p>"


def test_a_redirect_to_a_site_nobody_allowed_is_refused(wire):
    site = wire({("example.com", "/"): Reply(301, headers={"Location": "https://other.net/x"}),
                 ("other.net", "/x"): html()})
    with pytest.raises(NetError, match="redirected there from https://example.com/"):
        net.fetch("https://example.com/", policy=allowed("example.com"))
    assert [r["host"] for r in site.requests] == ["example.com"]


def test_a_redirect_down_to_http_is_refused(wire):
    wire({("example.com", "/"): Reply(302, headers={"Location": "http://example.com/plain"})})
    with pytest.raises(NetError, match="Only https"):
        net.fetch("https://example.com/", policy=allowed("example.com"))


def test_a_relative_redirect_stays_on_the_site(wire):
    wire({("example.com", "/old"): Reply(308, headers={"Location": "/new?x=1"}),
          ("example.com", "/new?x=1"): html()})
    assert net.fetch("https://example.com/old", policy=allowed("example.com")).url == \
        "https://example.com/new?x=1"


def test_a_redirect_loop_is_left(wire):
    wire({("example.com", "/"): Reply(302, headers={"Location": "/"})})
    with pytest.raises(NetError, match="more than 5 times"):
        net.fetch("https://example.com/", policy=allowed("example.com"))


# -- limits -----------------------------------------------------------------------------------


def test_a_page_past_the_size_limit_is_cut_and_says_so(wire):
    wire({("example.com", "/"): Reply(200, b"x" * 100, {"Content-Type": "text/plain"})})
    page = net.fetch("https://example.com/", policy=allowed("example.com"), max_bytes=10)
    assert page.truncated and page.body == b"x" * 10


def test_a_slow_site_is_left_at_the_time_limit(wire):
    wire({("example.com", "/"): Reply(200, b"x" * 300_000, {"Content-Type": "text/plain"},
                                      delay=0.05)})
    with pytest.raises(NetError, match="longer than"):
        net.fetch("https://example.com/", policy=allowed("example.com"), timeout_s=0.1)


def test_a_compressed_page_is_opened_but_never_past_the_limit(wire):
    wire({("example.com", "/small"): Reply(200, gzip.compress(b"<p>packed</p>"),
                                           {"Content-Encoding": "gzip"}),
          ("example.com", "/bomb"): Reply(200, gzip.compress(b"a" * 5_000_000),
                                          {"Content-Encoding": "gzip"})})
    policy = allowed("example.com")
    assert net.fetch("https://example.com/small", policy=policy).body == b"<p>packed</p>"
    bomb = net.fetch("https://example.com/bomb", policy=policy, max_bytes=1000)
    assert bomb.truncated and len(bomb.body) == 1000


# -- the pieces ------------------------------------------------------------------------------


def test_the_site_of_an_address_and_what_the_log_keeps():
    assert host_of("https://Docs.Example.com:8443/x?y=1") == "docs.example.com"
    assert host_of("http://example.com/") == "" and host_of("not a url") == ""
    assert redact("https://u:p@example.com/p?q=1#frag") == "https://example.com/p?…"


@pytest.mark.parametrize("address,public", [
    (PUBLIC, True), ("2606:2800:220:1:248:1893:25c8:1946", True), ("8.8.8.8", True),
    ("192.168.0.1", False), ("100.64.0.1", False), ("::ffff:127.0.0.1", False),
    ("fe80::1%eth0", False), ("not an address", False),
])
def test_what_counts_as_the_open_internet(address, public):
    assert is_public(address) is public
