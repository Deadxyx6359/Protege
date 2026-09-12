"""The one way back in: a sign-in's return to this computer (C5).

A desktop app signs in to Google by opening the person's own browser at
Google's page, and asking Google to send the browser back to this computer once
they have agreed: to `http://127.0.0.1:<port>/`, with a one-time code in the
address. Something has to be listening for that one request, and this is it. It
is held to very little:

- **This computer only.** It listens on 127.0.0.1, which nothing off this
  machine can reach. The runtime guard refuses any other bind, and
  `verify_offline.py` checks that this module binds nothing else, never
  connects and never looks a name up.
- **One answer, then gone.** It returns the first request carrying this
  sign-in's `state`, a random value nobody else knows, and closes. Anything
  else is told "not here" and ignored, and nothing a request says is repeated
  back. It gives up after five minutes, or when told to stop.
- **Only what it needs.** It reads the request line, at most 8 KB, and keeps
  the code or the refusal in it and nothing else. The code goes back to the
  caller, which exchanges it through the chokepoint; it is never written down.

Plain http, because that is what the browser is sent back with, and it never
leaves this computer.
"""

from __future__ import annotations

import hmac
import html
import socket
import threading
import time
from dataclasses import dataclass

from .client import query_value

#: This computer, and nothing another machine could reach.
HOST = "127.0.0.1"

#: How long a person has to finish signing in.
WAIT_S = 300.0

#: The most of a request that is read.
MAX_REQUEST = 8192

#: How often a waiting listener checks whether it has been told to stop.
TICK_S = 0.25

_REASONS = {200: "OK", 400: "Bad Request", 404: "Not Found"}

_PAGE = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>Akira</title></head>"
         "<body style=\"font-family: system-ui, sans-serif; margin: 4em auto; max-width: 32em\">"
         "<h1>{heading}</h1><p>{text}</p></body></html>")

_ELSEWHERE = "This address is only for signing Akira in."


class LoopbackError(RuntimeError):
    """No answer came back, with a reason for the person."""


@dataclass(frozen=True)
class Answer:
    code: str = ""
    """The one-time code, when the person agreed."""

    error: str = ""
    """What the provider said instead, such as `access_denied`."""


def _request_line(conn: socket.socket) -> str:
    data = b""
    while b"\r\n" not in data:
        if len(data) >= MAX_REQUEST:
            return ""
        piece = conn.recv(1024)
        if not piece:
            break
        data += piece
    return data.split(b"\r\n", 1)[0].decode("latin-1")


def _reply(conn: socket.socket, status: int, heading: str, text: str) -> None:
    body = _PAGE.format(heading=html.escape(heading), text=html.escape(text)).encode("utf-8")
    head = (f"HTTP/1.1 {status} {_REASONS[status]}\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            # The address carried a code: no copy kept, and none passed on.
            "Cache-Control: no-store\r\n"
            "Referrer-Policy: no-referrer\r\n"
            "Connection: close\r\n\r\n")
    try:
        conn.sendall(head.encode("ascii") + body)
    except OSError:
        pass


class Receiver:
    """Listens on this computer for one sign-in's answer."""

    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._listener.bind((HOST, 0))
            self._listener.listen(4)
            self._listener.settimeout(TICK_S)
        except OSError:
            self._listener.close()
            raise
        self.port: int = self._listener.getsockname()[1]
        self._stopped = threading.Event()

    @property
    def redirect_uri(self) -> str:
        """Where the provider is asked to send the browser back to."""
        return f"http://{HOST}:{self.port}/"

    def stop(self) -> None:
        """Stop waiting. Safe from any thread."""
        self._stopped.set()

    def close(self) -> None:
        self._listener.close()

    def wait(self, state: str, *, wait_s: float = WAIT_S) -> Answer:
        """The answer carrying \a state, then closed. Raises `LoopbackError` if none comes."""
        if not state:
            raise ValueError("a sign-in's answer is matched by its state, so it needs one")
        deadline = time.monotonic() + wait_s
        try:
            while not self._stopped.is_set():
                if time.monotonic() > deadline:
                    raise LoopbackError("No answer came back from the sign-in in time. "
                                        "Try again when you are ready.")
                try:
                    conn, _ = self._listener.accept()
                except TimeoutError:
                    continue
                with conn:
                    answer = self._take(conn, state)
                if answer is not None:
                    return answer
            raise LoopbackError("The sign-in was stopped before it finished.")
        finally:
            self.close()

    @staticmethod
    def _take(conn: socket.socket, state: str) -> Answer | None:
        conn.settimeout(5.0)
        try:
            line = _request_line(conn)
        except OSError:
            return None
        method, _, rest = line.partition(" ")
        target, _, version = rest.partition(" ")
        if method != "GET" or not target.startswith("/") or not version.startswith("HTTP/"):
            _reply(conn, 400, "Not here", _ELSEWHERE)
            return None
        if target.split("?", 1)[0] != "/":
            _reply(conn, 404, "Not here", _ELSEWHERE)
            return None
        address = f"http://{HOST}{target}"
        if not hmac.compare_digest(query_value(address, "state"), state):
            _reply(conn, 400, "Not this sign-in", "Akira is not waiting for this answer. "
                                                  "Start again from Akira.")
            return None
        error = query_value(address, "error")
        if error:
            _reply(conn, 200, "Not signed in", "Nothing was connected. You can close this tab "
                                               "and go back to Akira.")
            return Answer(error=error)
        code = query_value(address, "code")
        if not code:
            _reply(conn, 400, "Not signed in", "The answer carried no sign-in. Start again "
                                               "from Akira.")
            return None
        _reply(conn, 200, "Signed in", "You can close this tab and go back to Akira.")
        return Answer(code=code)
