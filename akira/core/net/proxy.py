"""The browser's only way out: a proxy on this computer, through the one door (C3).

The browser Akira drives is Firefox, in a process of its own, where the runtime
guard cannot see. So it is started with every request sent here (`browser.py`),
and this module holds each one to the chokepoint's rules by asking
`client.tunnel` for the connection:

- **Encrypted only.** A browser asks for a tunnel with CONNECT, and only to port
  443, where it speaks TLS to the site end to end; this proxy never sees inside.
  A plain http request is refused with a page that says why.
- **The open internet only**, each site's addresses checked by the chokepoint
  before connecting, as for every request Akira makes.
- **Only what the session allows**, by the rule it was given.
- **On this computer only.** It listens on 127.0.0.1, binds nothing else, and
  never connects or looks a name up itself; `verify_offline.py` checks all three.

Each connection is logged by the chokepoint with its site. What passes through
is copied, never read, and a connection left idle for a minute is closed.
"""

from __future__ import annotations

import html
import select
import socket
import threading
import time
from collections.abc import Callable

from akira.core.permissions import AuditLog

from .client import NetError, tunnel

#: This computer, and nothing another machine could reach.
HOST = "127.0.0.1"

#: The most of a request's head that is read.
MAX_HEAD = 8192

#: A tunnel with nothing passing for this long is closed.
IDLE_S = 60.0

#: Connections open at once, at most.
MAX_OPEN = 64

#: How often the proxy checks whether it has been told to stop.
TICK_S = 0.25

_REASONS = {400: "Bad Request", 403: "Forbidden", 503: "Service Unavailable"}


def _head(conn: socket.socket) -> tuple[bytes, bytes]:
    """A request's head, and whatever arrived after it."""
    data = b""
    while b"\r\n\r\n" not in data:
        if len(data) >= MAX_HEAD:
            return b"", b""
        piece = conn.recv(4096)
        if not piece:
            return b"", b""
        data += piece
    head, _, rest = data.partition(b"\r\n\r\n")
    return head, rest


def _refuse(conn: socket.socket, status: int, why: str) -> None:
    body = (f"<!doctype html><meta charset=\"utf-8\"><title>Not let through</title>"
            f"<p>{html.escape(why)}</p>").encode("utf-8")
    head = (f"HTTP/1.1 {status} {_REASONS[status]}\r\nContent-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n")
    try:
        conn.sendall(head.encode("ascii") + body)
    except OSError:
        pass


def _relay(browser: socket.socket, site: socket.socket, stopped: threading.Event) -> None:
    """Copy bytes both ways until either side closes, or nothing passes for a minute."""
    browser.settimeout(None)
    site.settimeout(None)
    other = {browser: site, site: browser}
    quiet_since = time.monotonic()
    while not stopped.is_set():
        ready, _, broken = select.select([browser, site], [], [browser, site], TICK_S)
        if broken:
            return
        if not ready:
            if time.monotonic() - quiet_since > IDLE_S:
                return
            continue
        quiet_since = time.monotonic()
        for sock in ready:
            data = sock.recv(65536)
            if not data:
                return
            other[sock].sendall(data)


class Proxy:
    """Listens on this computer for a browser's requests, and lets through what may pass."""

    def __init__(self, may: Callable[[str], str], *, audit: AuditLog | None = None,
                 actor: str = "browser") -> None:
        self._may = may
        self._audit = audit
        self._actor = actor
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._listener.bind((HOST, 0))
            self._listener.listen(32)
            self._listener.settimeout(TICK_S)
        except OSError:
            self._listener.close()
            raise
        self.port: int = self._listener.getsockname()[1]
        self._stopped = threading.Event()
        self._slots = threading.BoundedSemaphore(MAX_OPEN)
        self._lock = threading.Lock()
        self.reached: list[str] = []
        """Every site a tunnel was opened to, in order."""
        self.refused: list[tuple[str, str]] = []
        """Every site refused, with why."""
        self._thread = threading.Thread(target=self._serve, name="browser-proxy", daemon=True)
        self._thread.start()

    @property
    def server(self) -> str:
        """What the browser is told to send everything to."""
        return f"http://{HOST}:{self.port}"

    def close(self) -> None:
        self._stopped.set()
        self._thread.join(2)
        self._listener.close()

    def _serve(self) -> None:
        while not self._stopped.is_set():
            try:
                conn, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            if not self._slots.acquire(blocking=False):
                _refuse(conn, 503, "Too many connections at once.")
                conn.close()
                continue
            threading.Thread(target=self._handle, args=(conn,), name="browser-tunnel",
                             daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(10.0)
            head, early = _head(conn)
            method, _, rest = head.split(b"\r\n", 1)[0].decode("latin-1").partition(" ")
            target = rest.partition(" ")[0]
            if method != "CONNECT":
                _refuse(conn, 403, "Only https is let through. A page sent over plain http "
                                   "can be read or changed by anyone along the way.")
                return
            host, _, port = target.rpartition(":")
            if not host or not port.isdigit():
                _refuse(conn, 400, "That is not a site and a port.")
                return
            host = host.strip("[]").lower()
            try:
                site = tunnel(host, int(port), may=self._may, audit=self._audit,
                              actor=self._actor)
            except NetError as exc:
                with self._lock:
                    self.refused.append((host, str(exc)))
                _refuse(conn, 403, str(exc))
                return
            with self._lock:
                self.reached.append(host)
            with site:
                conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                if early:
                    site.sendall(early)
                _relay(conn, site, self._stopped)
        except OSError:
            pass
        finally:
            conn.close()
            self._slots.release()
