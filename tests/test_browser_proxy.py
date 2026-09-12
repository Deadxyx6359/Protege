"""The browser's only way out (C3): the chokepoint's tunnel, and the proxy on 127.0.0.1.

The browser runs in its own process, so everything it sends goes to the proxy,
which asks `client.tunnel` for each connection. A site stands in as a small
server on this computer; the resolver says a public address and the dialler
connects to the stand-in instead. Nothing leaves this computer.
"""

from __future__ import annotations

import socket
import threading

import pytest

from akira.core.net import NetError
from akira.core.net import client as net
from akira.core.net.proxy import HOST, Proxy
from akira.core.permissions import AuditLog
from akira.security import netguard

PUBLIC = "93.184.216.34"


class Site:
    """A stand-in site: answers whatever it is sent with "echo:" and the same bytes."""

    def __init__(self):
        self.server = socket.socket()
        self.server.bind((HOST, 0))
        self.server.listen(4)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = conn.recv(4096)
                if data:
                    conn.sendall(b"echo:" + data)


@pytest.fixture
def site(monkeypatch):
    stand_in = Site()
    dialled = []

    def dial(address, port, timeout):
        dialled.append((address, port))
        sock = socket.socket()
        sock.settimeout(timeout)
        with netguard.admitting(addresses=((HOST, stand_in.port),)):
            sock.connect((HOST, stand_in.port))
        return sock

    monkeypatch.setattr(net, "_resolve", lambda host, port: {"private.example": ["10.0.0.5"]}
                        .get(host, [PUBLIC]))
    monkeypatch.setattr(net, "_dial", dial)
    yield dialled
    stand_in.server.close()


def allow(*hosts):
    return lambda host: "" if host in hosts else f"Not permitted: browsing {host} is not allowed."


# -- the tunnel ---------------------------------------------------------------------------------


def test_a_tunnel_goes_to_the_checked_address_and_is_logged(site, tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    with net.tunnel("Example.com", 443, may=allow("example.com"), audit=audit, actor="browser"):
        pass
    assert site == [(PUBLIC, 443)]
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "net.tunnel" in log and "example.com" in log


@pytest.mark.parametrize("host, port, reason", [
    ("example.com", 80, "Only https"),
    ("elsewhere.example", 443, "Not permitted"),
    ("private.example", 443, "private network"),
    ("user@example.com", 443, "not a site"),
])
def test_a_tunnel_is_refused_before_anything_is_dialled(site, host, port, reason):
    with pytest.raises(NetError, match=reason):
        net.tunnel(host, port, may=allow("example.com", "private.example", "user@example.com"))
    assert site == []


# -- the proxy ------------------------------------------------------------------------------------


def ask(proxy, request: bytes, then: bytes = b"") -> bytes:
    """What a browser does: one request to the proxy, perhaps some bytes after, and the answer."""
    sock = socket.socket()
    sock.settimeout(5)
    with netguard.admitting(addresses=((HOST, proxy.port),)):
        sock.connect((HOST, proxy.port))
    sock.sendall(request)
    answer = b""
    try:
        while b"\r\n\r\n" not in answer:
            answer += sock.recv(4096)
        if then:
            sock.sendall(then)
            answer += sock.recv(4096)
        else:
            while chunk := sock.recv(4096):
                answer += chunk
    except OSError:
        pass
    finally:
        sock.close()
    return answer


@pytest.fixture
def proxy(tmp_path):
    running = Proxy(allow("example.com"), audit=AuditLog(tmp_path / "audit.jsonl"))
    yield running
    running.close()


def test_it_listens_on_this_computer_only(proxy):
    assert proxy._listener.getsockname()[0] == "127.0.0.1"
    assert proxy.server == f"http://127.0.0.1:{proxy.port}"


def test_an_allowed_tunnel_carries_bytes_both_ways_unread(site, proxy):
    answer = ask(proxy, b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n",
                 then=b"\x16\x03\x01 a client hello")
    assert answer.startswith(b"HTTP/1.1 200 Connection established")
    assert answer.endswith(b"echo:\x16\x03\x01 a client hello")
    assert proxy.reached == ["example.com"] and site == [(PUBLIC, 443)]


def test_a_site_not_allowed_is_refused_with_why(site, proxy):
    answer = ask(proxy, b"CONNECT elsewhere.example:443 HTTP/1.1\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 403") and b"browsing elsewhere.example is not allowed" in answer
    assert site == [] and proxy.refused[0][0] == "elsewhere.example"


def test_plain_http_is_refused(site, proxy):
    answer = ask(proxy, b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 403") and b"Only https" in answer
    assert site == []


def test_another_port_is_refused(site, proxy):
    answer = ask(proxy, b"CONNECT example.com:8443 HTTP/1.1\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 403") and b"Only https" in answer
    assert site == []


def test_after_closing_nothing_is_listening(proxy):
    port = proxy.port
    proxy.close()
    with pytest.raises(OSError):
        sock = socket.socket()
        sock.settimeout(2)
        try:
            with netguard.admitting(addresses=((HOST, port),)):
                sock.connect((HOST, port))
        finally:
            sock.close()
