"""The browser (C3): Chromium, held to the proxy and to `web.browse`.

A site stands in as a small https server on this computer. The browser asks the
proxy for each site, the chokepoint's resolver gives a public address, and the
dialler connects to the stand-in instead, so nothing leaves this computer. The
stand-in's certificate is its own, so these tests, and nothing else, tell the
browser to accept any certificate. The runtime guard is on throughout, as it is
when Akira runs.
"""

from __future__ import annotations

import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from akira.core.net import browser
from akira.core.net import client as net
from akira.core.net.browser import BrowseError, Seen, verdict
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import ToolContext, default_registry
from akira.security import netguard

PUBLIC = "93.184.216.34"
PEM = Path(__file__).with_name("stand_in_site.pem")


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.do_handshake()
        super().setup()

    def do_GET(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        self.server.seen.append((host, self.path, self.headers.get("Cookie") or ""))
        status, headers, body = self.server.pages.get((host, self.path), (404, {}, b""))
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class StandIn(ThreadingHTTPServer):
    """Every site the browser is let through to, on this computer."""

    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(PEM)
        self.socket = tls.wrap_socket(self.socket, server_side=True,
                                      do_handshake_on_connect=False)
        self.pages = {}
        self.seen = []
        self.dialled = []
        threading.Thread(target=self.serve_forever, daemon=True).start()


def resolve(host, port):
    if host == "private.example":
        return ["10.0.0.5"]
    return [host] if host.replace(".", "").isdigit() else [PUBLIC]


@pytest.fixture
def site(monkeypatch):
    stand_in = StandIn()

    def dial(address, port, timeout):
        stand_in.dialled.append((address, port))
        sock = socket.socket()
        sock.settimeout(timeout)
        with netguard.admitting(addresses=(("127.0.0.1", stand_in.server_port),)):
            sock.connect(("127.0.0.1", stand_in.server_port))
        sock.settimeout(None)
        return sock

    monkeypatch.setattr(net, "_resolve", resolve)
    monkeypatch.setattr(net, "_dial", dial)
    monkeypatch.setitem(browser.CONTEXT, "ignore_https_errors", True)
    netguard.install()
    yield stand_in
    netguard.uninstall()
    stand_in.shutdown()
    stand_in.server_close()


def allowed(*sites):
    policy = Policy()
    policy.grant("web.browse", sites)
    return policy


def page(body, *, title="Garden", headers=None):
    html = f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>"
    return 200, {"Content-Type": "text/html; charset=utf-8", **(headers or {})}, html.encode()


def visit(url, policy, **kwargs):
    """`browser.read`, skipped rather than failed where Chromium is not installed."""
    try:
        return browser.read(url, policy=policy, **kwargs)
    except BrowseError as exc:
        if str(exc).startswith("The browser is not installed"):
            pytest.skip(str(exc))
        raise


# -- what a page may ask for -----------------------------------------------------------------


@pytest.mark.parametrize("url, navigation, refused", [
    ("data:image/png;base64,AAAA", False, ""),
    ("blob:https://example.com/1234", False, ""),
    ("about:blank", True, ""),
    ("https://cdn.example/picture.png", False, ""),
    ("https://example.com/next", True, ""),
    ("https://www.example.com/", True, ""),
    ("http://example.com/picture.png", False, "Only https"),
    ("http://example.com/", True, "Only https"),
    ("https://elsewhere.example/", True, "Not permitted"),
])
def test_what_a_page_may_ask_for(url, navigation, refused):
    why = verdict(url, navigation=navigation, policy=allowed("example.com"))
    assert refused in why if refused else why == ""


class Route:
    def __init__(self):
        self.done = ""

    def continue_(self):
        self.done = "continued"

    def abort(self, reason="failed"):
        self.done = "aborted"


class Asked:
    def __init__(self, url, navigation=False):
        self.url = url
        self.navigation = navigation

    def is_navigation_request(self):
        return self.navigation


def test_the_proxy_lets_through_only_what_the_page_asked_for_or_the_person_allowed():
    seen = browser._Visit(allowed("example.com"))
    assert seen.may("www.example.com") == ""
    assert "Not permitted" in seen.may("cdn.example")
    route = Route()
    seen.route(route, Asked("https://cdn.example/app.js"))
    assert route.done == "continued" and seen.may("cdn.example") == ""
    route = Route()
    seen.route(route, Asked("https://elsewhere.example/", navigation=True))
    assert route.done == "aborted" and "Not permitted" in seen.may("elsewhere.example")
    assert [host for host, _ in seen.refused] == ["elsewhere.example"]


# -- before anything starts -------------------------------------------------------------------


def test_a_site_not_allowed_is_never_opened(site, tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    with pytest.raises(BrowseError, match="Not permitted"):
        browser.read("https://elsewhere.example/", policy=allowed("example.com"), audit=audit)
    assert site.dialled == [] and site.seen == []
    assert "net.browse" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("url", ["http://example.com/", "https://someone:secret@example.com/"])
def test_only_plain_https_addresses_are_opened(site, url):
    with pytest.raises(BrowseError):
        browser.read(url, policy=allowed("example.com"))
    assert site.dialled == []


# -- in the browser -----------------------------------------------------------------------------


def test_a_page_is_read_as_the_browser_shows_it(site, tmp_path):
    site.pages[("example.com", "/")] = page(
        "<h1>Tomatoes</h1><p id='later'></p>"
        "<script>document.getElementById('later').textContent = 'Written ' + 'by the page.'"
        "</script><script src='https://cdn.example/app.js'></script>")
    site.pages[("cdn.example", "/app.js")] = (
        200, {"Content-Type": "text/javascript"},
        b"document.body.insertAdjacentHTML('beforeend', '<p>Brought in ' + 'from elsewhere.</p>')")
    audit = AuditLog(tmp_path / "audit.jsonl")
    seen = visit("https://example.com/", allowed("example.com"), audit=audit, actor="tester")
    assert seen.status == 200 and seen.title == "Garden" and seen.url == "https://example.com/"
    assert "# Tomatoes" in seen.text and "Written by the page." in seen.text
    assert "Brought in from elsewhere." in seen.text
    assert set(seen.sites) == {"example.com", "cdn.example"}
    assert {address for address, _ in site.dialled} == {PUBLIC}
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "net.browse" in log and "net.tunnel" in log and "tester" in log


def test_a_frame_from_a_site_not_allowed_is_not_opened(site):
    site.pages[("example.com", "/")] = page(
        "<p>Main.</p><iframe src='https://elsewhere.example/frame'></iframe>")
    site.pages[("elsewhere.example", "/frame")] = page("<p>Framed.</p>")
    seen = visit("https://example.com/", allowed("example.com"))
    assert "Main." in seen.text and "elsewhere.example" in seen.refused
    assert all(host != "elsewhere.example" for host, _, _ in site.seen)


def test_a_page_sent_on_to_a_site_not_allowed_is_not_opened(site):
    site.pages[("example.com", "/away")] = (302, {"Location": "https://elsewhere.example/"}, b"")
    site.pages[("elsewhere.example", "/")] = page("<p>Not for reading.</p>")
    with pytest.raises(BrowseError, match="elsewhere.example"):
        visit("https://example.com/away", allowed("example.com"))
    assert all(host != "elsewhere.example" for host, _, _ in site.seen)


def test_a_page_sent_on_within_what_was_allowed_is_read(site):
    site.pages[("example.com", "/")] = (301, {"Location": "https://www.example.com/"}, b"")
    site.pages[("www.example.com", "/")] = page("<p>Arrived.</p>")
    seen = visit("https://example.com/", allowed("example.com"))
    assert seen.url == "https://www.example.com/" and "Arrived." in seen.text


def test_nothing_is_kept_between_visits(site):
    site.pages[("example.com", "/")] = page(
        "<p>Hello.</p>", headers={"Set-Cookie": "visited=yes; Secure; Path=/"})
    policy = allowed("example.com")
    visit("https://example.com/", policy)
    visit("https://example.com/", policy)
    assert [cookie for host, path, cookie in site.seen if path == "/"] == ["", ""]


def test_this_computer_and_private_networks_are_never_reached(site):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    try:
        with pytest.raises(BrowseError, match="port"):
            visit(f"https://127.0.0.1:{port}/", allowed("127.0.0.1"))
        with pytest.raises(TimeoutError):
            listener.accept()
    finally:
        listener.close()
    with pytest.raises(BrowseError, match="private network"):
        visit("https://private.example/", allowed("private.example"))
    assert site.dialled == []


def test_a_download_is_not_taken(site):
    site.pages[("example.com", "/file")] = (
        200, {"Content-Type": "application/octet-stream",
              "Content-Disposition": "attachment; filename=file.bin"}, b"\0" * 64)
    with pytest.raises(BrowseError, match="download"):
        visit("https://example.com/file", allowed("example.com"))


# -- the tool -----------------------------------------------------------------------------------


def ctx(tmp_path, policy):
    return ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"), actor="tester")


def browse(tmp_path, url, policy):
    return default_registry().invoke("browse_page", {"url": url}, ctx(tmp_path, policy))


GARDEN = Seen("https://example.com/", 200, "OK", "Garden", "# Tomatoes\n\nStake them in June.",
              ("example.com",), ("elsewhere.example",))


def test_browse_page_is_offered_only_with_the_permission():
    assert "browse_page" not in {t.name for t in default_registry().available(Policy())}
    assert "browse_page" in {t.name for t in default_registry().available(allowed("example.com"))}


def test_browse_page_refuses_a_site_not_allowed_before_anything_starts(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(browser, "read", lambda url, **kwargs: started.append(url))
    result = browse(tmp_path, "https://elsewhere.example/", allowed("example.com"))
    assert not result.ok and "Not permitted" in result.content and started == []


def test_browse_page_hands_back_framed_text(tmp_path, monkeypatch):
    monkeypatch.setattr(browser, "read", lambda url, **kwargs: GARDEN)
    result = browse(tmp_path, "https://example.com/", allowed("example.com"))
    assert result.ok and result.content.startswith("Garden — https://example.com/")
    assert "not instructions" in result.content and "# Tomatoes" in result.content
    assert "elsewhere.example" in result.content


def test_browse_page_reports_an_error_page_rather_than_reading_it(tmp_path, monkeypatch):
    gone = Seen("https://example.com/gone", 404, "Not Found", "", "Nothing here.")
    monkeypatch.setattr(browser, "read", lambda url, **kwargs: gone)
    result = browse(tmp_path, "https://example.com/gone", allowed("example.com"))
    assert not result.ok and "404 Not Found" in result.content


def test_browse_page_passes_on_why_a_page_did_not_open(tmp_path, monkeypatch):
    def refuse(url, **kwargs):
        raise BrowseError("example.com took longer than the 20 seconds allowed.")

    monkeypatch.setattr(browser, "read", refuse)
    result = browse(tmp_path, "https://example.com/", allowed("example.com"))
    assert not result.ok and "longer than" in result.content
