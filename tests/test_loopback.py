"""The sign-in's way back in (C5): a listener on this computer for one answer.

These use real sockets on 127.0.0.1, with the test playing the person's browser
being sent back by the provider. Nothing leaves this computer.
"""

from __future__ import annotations

import socket
import threading

import pytest

from akira.core.net.loopback import HOST, Answer, LoopbackError, Receiver
from akira.security import netguard


def browse(port: int, target: str) -> tuple[int, str]:
    """What the browser does when it is sent back: one GET, and the page it gets."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    try:
        with netguard.admitting(addresses=((HOST, port),)):
            sock.connect((HOST, port))
        sock.sendall(f"GET {target} HTTP/1.1\r\nHost: {HOST}:{port}\r\n\r\n".encode("latin-1"))
        data = b""
        while True:
            piece = sock.recv(4096)
            if not piece:
                break
            data += piece
    finally:
        sock.close()
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), body.decode("utf-8")


def waiting(receiver: Receiver, state: str, **options) -> tuple[threading.Thread, dict]:
    result: dict = {}

    def run():
        try:
            result["answer"] = receiver.wait(state, **options)
        except LoopbackError as exc:
            result["error"] = str(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, result


def test_it_listens_on_this_computer_only():
    receiver = Receiver()
    try:
        assert receiver._listener.getsockname()[0] == "127.0.0.1"
        assert receiver.redirect_uri == f"http://127.0.0.1:{receiver.port}/"
    finally:
        receiver.close()


def test_the_answer_for_this_sign_in_is_taken_and_then_it_is_gone():
    receiver = Receiver()
    thread, result = waiting(receiver, "a-random-state")
    status, page = browse(receiver.port, "/?state=a-random-state&code=4%2F0-a-code&scope=email")
    thread.join(5)
    assert result["answer"] == Answer(code="4/0-a-code")
    assert status == 200 and "Signed in" in page
    with pytest.raises(OSError):
        browse(receiver.port, "/?state=a-random-state&code=again")


def test_anything_else_is_turned_away_and_the_wait_goes_on():
    receiver = Receiver()
    thread, result = waiting(receiver, "right")
    assert browse(receiver.port, "/?state=wrong&code=forged")[0] == 400
    assert browse(receiver.port, "/favicon.ico")[0] == 404
    assert browse(receiver.port, "/?state=right")[0] == 400, "an answer with no code was taken"
    assert thread.is_alive() and not result, "a wrong answer ended the wait"
    assert browse(receiver.port, "/?state=right&code=real")[0] == 200
    thread.join(5)
    assert result["answer"].code == "real"


def test_a_refusal_comes_back_as_the_provider_said_it():
    receiver = Receiver()
    thread, result = waiting(receiver, "s")
    status, page = browse(receiver.port, "/?state=s&error=access_denied")
    thread.join(5)
    assert result["answer"] == Answer(error="access_denied")
    assert status == 200 and "Nothing was connected" in page


def test_nothing_a_request_says_is_repeated_back():
    receiver = Receiver()
    thread, result = waiting(receiver, "s")
    _, page = browse(receiver.port, "/?state=%3Cscript%3Ealert(1)%3C%2Fscript%3E")
    assert "<script>" not in page and "alert" not in page
    receiver.stop()
    thread.join(5)


def test_it_gives_up_in_time_and_when_told_to_stop():
    with pytest.raises(LoopbackError, match="in time"):
        Receiver().wait("s", wait_s=0.3)
    receiver = Receiver()
    thread, result = waiting(receiver, "s")
    receiver.stop()
    thread.join(5)
    assert "stopped" in result["error"]


def test_an_answer_is_matched_by_a_state_so_one_is_needed():
    receiver = Receiver()
    try:
        with pytest.raises(ValueError):
            receiver.wait("")
    finally:
        receiver.close()
