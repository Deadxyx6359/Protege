"""Runtime network guard.

The primary guarantee is structural: nothing in Akira imports a networking
module except the one chokepoint, `akira.core.net.client`, and
`verify_offline.py` proves that statically over the whole reachable import
graph.

This module is the belt to that suspenders. It patches the outbound entry
points of the stdlib `socket` module so that if some future edit, plugin, or
transitive dependency *does* reach for the network, the attempt raises loudly
instead of succeeding quietly. A static check catches what exists today; this
catches what someone adds tomorrow.

**One door, opened narrowly.** The chokepoint checks a request first: the grant
for its host, https, an address that is not this machine or its network. Then
it asks the guard to let exactly that through. `admitting` lets the calling
thread resolve the named hosts and connect to the named addresses, for the
length of a `with` block, and nothing else. Every other thread, and this one
outside the block, is still refused. `verify_offline.py` proves no other module
calls it.

**A socket pair, joined to itself.** asyncio wakes its own loop with two
sockets joined to each other, and Playwright, which drives the browser (C3),
runs on asyncio. On Windows, Python makes the pair by listening on 127.0.0.1
and connecting to that. So while `socket.socketpair` runs, and only on the
thread calling it, a connection to this computer is let through. Nothing
leaves the process, let alone the machine.

Deliberately narrow. We do not delete `socket` or block the module's import --
several innocuous stdlib paths touch `socket` for local reasons (hostname
lookup, Tk's internals on some platforms), and breaking those would produce
mystifying failures that push a future maintainer toward disabling the guard
entirely. We block exactly the operations that move bytes off this machine:
outbound connects, DNS resolution, and binds to anything but loopback.

Read the honest caveat in the README: this is an application-level control
inside the process it is protecting. Code that genuinely wants out can call the
OS directly via ctypes and never touch `socket`. An OS firewall rule denying
this binary egress is strictly stronger, and is what the README recommends.
"""

from __future__ import annotations

import socket
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "", None})

_installed = False
_original: dict[str, Any] = {}

#: What this thread may reach right now, set only inside `admitting`.
_admission = threading.local()


class NetworkAccessBlocked(RuntimeError):
    """Raised when any code in this process attempts to reach the network.

    This is never caught and converted into a warning anywhere in Akira. If
    you see it, something imported or invoked networking that should not exist
    in this application at all -- treat it as a bug in the code that called it,
    not as a guard to relax.
    """


@contextmanager
def admitting(*, hosts: Iterable[str] = (),
              addresses: Iterable[tuple[str, int]] = ()) -> Iterator[None]:
    """Let this thread resolve \a hosts and connect to \a addresses, for the block.

    For `akira.core.net.client` alone, which checks every request before it
    asks; `verify_offline.py` fails if any other module calls this. Nothing is
    admitted on any other thread, and nothing once the block ends.
    """
    previous = (getattr(_admission, "hosts", frozenset()),
                getattr(_admission, "addresses", frozenset()))
    _admission.hosts = frozenset(_host_key(h) for h in hosts)
    _admission.addresses = frozenset((str(ip).lower(), int(port)) for ip, port in addresses)
    try:
        yield
    finally:
        _admission.hosts, _admission.addresses = previous


def _host_key(host: Any) -> str:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    return str(host).lower().rstrip(".")


def _host_admitted(host: Any) -> bool:
    return host is not None and _host_key(host) in getattr(_admission, "hosts", frozenset())


def _address_admitted(address: Any) -> bool:
    allowed = getattr(_admission, "addresses", frozenset())
    if not allowed or not isinstance(address, (tuple, list)) or len(address) < 2:
        return False
    try:
        return (str(address[0]).lower(), int(address[1])) in allowed
    except (TypeError, ValueError):
        return False


#: Where `socket.socketpair` joins its two ends, on Windows.
_PAIR_HOSTS = frozenset({"127.0.0.1", "::1"})


def _pairing(address: Any) -> bool:
    """Whether this is the connection `socket.socketpair` makes to join its own two ends."""
    return (getattr(_admission, "pairing", False) and isinstance(address, tuple)
            and bool(address) and address[0] in _PAIR_HOSTS)


def _is_loopback(address: Any) -> bool:
    """True only for addresses that cannot leave the machine."""
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
    elif isinstance(address, (str, bytes)):
        # AF_UNIX path, or a bare hostname. AF_UNIX cannot leave the machine.
        return True
    else:
        return False
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    return host in _LOOPBACK_HOSTS


def _blocked(operation: str, detail: Any = None) -> NetworkAccessBlocked:
    suffix = f" ({detail!r})" if detail is not None else ""
    return NetworkAccessBlocked(
        f"Akira blocked a network operation: {operation}{suffix}. "
        "Akira reaches the network only through akira.core.net, and only to "
        "sites the person has allowed. If you are seeing this, something tried "
        "another way out -- report it rather than disabling the guard."
    )


def install() -> None:
    """Patch outbound socket operations. Idempotent.

    Call once, as early in startup as possible -- before any model backend or
    plugin is imported -- so that nothing gets a chance to capture an
    unpatched reference.
    """
    global _installed
    if _installed:
        return

    _original["connect"] = socket.socket.connect
    _original["connect_ex"] = socket.socket.connect_ex
    _original["bind"] = socket.socket.bind
    _original["create_connection"] = socket.create_connection
    _original["getaddrinfo"] = socket.getaddrinfo
    _original["gethostbyname"] = socket.gethostbyname
    _original["socketpair"] = socket.socketpair

    def guarded_connect(self: socket.socket, address: Any) -> None:
        if _address_admitted(address) or _pairing(address):
            return _original["connect"](self, address)
        raise _blocked("socket.connect", address)

    def guarded_socketpair(*args: Any, **kwargs: Any) -> Any:
        # Two ends joined to each other, in this process. See the module's note.
        previous = getattr(_admission, "pairing", False)
        _admission.pairing = True
        try:
            return _original["socketpair"](*args, **kwargs)
        finally:
            _admission.pairing = previous

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        raise _blocked("socket.connect_ex", address)

    def guarded_bind(self: socket.socket, address: Any) -> None:
        # A bind to loopback is harmless and unreachable from off-box. Akira
        # ships no local HTTP layer, but a plugin might legitimately want an
        # in-process IPC socket, and the brief permits 127.0.0.1 binds.
        if _is_loopback(address):
            return _original["bind"](self, address)
        raise _blocked("socket.bind to a non-loopback address", address)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        raise _blocked("socket.create_connection", address)

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        # DNS resolution is itself a network request and leaks the query to the
        # resolver, so it is blocked even though no connection follows.
        if host in _LOOPBACK_HOSTS or _host_admitted(host):
            return _original["getaddrinfo"](host, *args, **kwargs)
        raise _blocked("socket.getaddrinfo", host)

    def guarded_gethostbyname(host: Any) -> Any:
        if host in _LOOPBACK_HOSTS:
            return _original["gethostbyname"](host)
        raise _blocked("socket.gethostbyname", host)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.socket.bind = guarded_bind  # type: ignore[method-assign]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
    socket.gethostbyname = guarded_gethostbyname  # type: ignore[assignment]
    socket.socketpair = guarded_socketpair  # type: ignore[assignment]

    _installed = True


def uninstall() -> None:
    """Restore the original socket functions.

    Exists for tests only. Nothing in the application calls this, and there is
    no setting that reaches it.
    """
    global _installed
    if not _installed:
        return
    socket.socket.connect = _original["connect"]  # type: ignore[method-assign]
    socket.socket.connect_ex = _original["connect_ex"]  # type: ignore[method-assign]
    socket.socket.bind = _original["bind"]  # type: ignore[method-assign]
    socket.create_connection = _original["create_connection"]  # type: ignore[assignment]
    socket.getaddrinfo = _original["getaddrinfo"]  # type: ignore[assignment]
    socket.gethostbyname = _original["gethostbyname"]  # type: ignore[assignment]
    socket.socketpair = _original["socketpair"]  # type: ignore[assignment]
    _original.clear()
    _installed = False


def is_installed() -> bool:
    return _installed
