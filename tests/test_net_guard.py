"""The guard's one door (C1): `admitting` lets only this thread, only inside the
block, connect only to the named address or look up only the named site.

These use a listener on 127.0.0.1, which never leaves the machine: the guard
refuses every connect, loopback included, unless it has been admitted.
"""

from __future__ import annotations

import socket
import threading

import pytest

from akira.security import netguard


@pytest.fixture
def guard():
    netguard.install()
    yield
    netguard.uninstall()


@pytest.fixture
def listener():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    yield server.getsockname()
    server.close()


def attempt(address):
    sock = socket.socket()
    try:
        sock.connect(address)
        return None
    except Exception as exc:  # noqa: BLE001 - the tests look at what was raised
        return exc
    finally:
        sock.close()


def test_outside_the_block_nothing_connects(guard, listener):
    assert isinstance(attempt(listener), netguard.NetworkAccessBlocked)


def test_inside_the_block_only_the_named_address_connects(guard, listener):
    other = (listener[0], listener[1] - 1 if listener[1] > 1 else listener[1] + 1)
    with netguard.admitting(addresses=(listener,)):
        assert attempt(listener) is None
        assert isinstance(attempt(other), netguard.NetworkAccessBlocked)
    assert isinstance(attempt(listener), netguard.NetworkAccessBlocked), "the door stayed open"


def test_the_door_is_open_only_on_the_thread_that_opened_it(guard, listener):
    seen = {}
    with netguard.admitting(addresses=(listener,)):
        worker = threading.Thread(target=lambda: seen.update(result=attempt(listener)))
        worker.start()
        worker.join()
    assert isinstance(seen["result"], netguard.NetworkAccessBlocked)


def test_only_the_named_site_is_looked_up(guard, monkeypatch):
    asked = []
    monkeypatch.setitem(netguard._original, "getaddrinfo",
                        lambda host, *args, **kwargs: asked.append(host) or [("answer",)])
    with pytest.raises(netguard.NetworkAccessBlocked):
        socket.getaddrinfo("example.com", 443)
    with netguard.admitting(hosts=("example.com",)):
        assert socket.getaddrinfo("Example.com", 443) == [("answer",)]
        with pytest.raises(netguard.NetworkAccessBlocked):
            socket.getaddrinfo("other.net", 443)
    with pytest.raises(netguard.NetworkAccessBlocked):
        socket.getaddrinfo("example.com", 443)
    assert asked == ["Example.com"]


def test_blocks_nest_and_restore(guard, listener):
    with netguard.admitting(addresses=(listener,)):
        with netguard.admitting(hosts=("example.com",)):
            assert isinstance(attempt(listener), netguard.NetworkAccessBlocked)
        assert attempt(listener) is None
