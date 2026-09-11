"""The one way out: every request Protégé makes to the network goes through here (C1).

Until this module, nothing in Protégé could connect, and `verify_offline.py`
proved it. Now one thing can, and the proof is that nothing else can: this is
the only module allowed to import the network, and the only one the runtime
guard lets through.

Every request, and every redirect it leads to, is held to:

- **`net.http` for its site**, granted by the person. Nothing is fetched from a
  site nobody allowed, and a redirect to another site needs that site allowed
  too. A grant for `example.com` covers its subdomains.
- **`https://` only**, certificates verified, TLS 1.2 or later. A page fetched
  over plain http can be read or rewritten by anyone along the way.
- **The open internet only.** A site whose name leads to this computer, the
  local network or any other private address is refused, so a public name
  cannot be pointed back at a router's admin page or a service on this machine.
  The address that was checked is the address connected to: the name is never
  looked up a second time, which is how that check is usually dodged.
- **Nothing of the person's.** No cookies, no credentials, no stored logins,
  and addresses with a name or password in them are refused. A fixed
  User-Agent says what is asking.
- **Limits.** At most 5 MB of body, 20 seconds in all, 5 redirects.
- **A record.** Each fetch goes into the activity log with its site, status and
  size. The query string is left out, since that is where addresses carry
  tokens.

Only `GET`: reading. Sending anything, such as forms, posts or purchases, is a
different capability (`web.submit`), irreversible, and not here.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
import zlib
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from protege import __version__
from protege.core.permissions import AuditLog
from protege.security import netguard

MAX_BYTES = 5_000_000
TIMEOUT_S = 20.0
MAX_REDIRECTS = 5
READ_CHUNK = 65_536
REDIRECTS = frozenset({301, 302, 303, 307, 308})
USER_AGENT = f"Protege/{__version__} (a personal assistant, fetching for its owner)"
ACCEPT = "text/html, application/xhtml+xml, text/plain;q=0.9, application/pdf;q=0.8, */*;q=0.5"

#: Who the activity log records when no actor is named.
ACTOR = "assistant"


class NetError(RuntimeError):
    """A request that was refused or failed, with a reason for the person."""


@dataclass(frozen=True)
class Response:
    url: str
    """Where the page finally came from, after any redirects."""

    status: int
    reason: str
    content_type: str
    body: bytes
    truncated: bool = False
    """The body stopped at the size limit."""

    hops: tuple[str, ...] = ()
    """The addresses redirected through on the way, as the log keeps them."""

    @property
    def media_type(self) -> str:
        return self.content_type.split(";", 1)[0].strip().lower()

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def text(self) -> str:
        charset = "utf-8"
        for part in self.content_type.split(";")[1:]:
            key, _, value = part.partition("=")
            if key.strip().lower() == "charset" and value.strip():
                charset = value.strip().strip("\"'")
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def host_of(url: str) -> str:
    """The site an https address would reach, in lower case, or "" if it is not one."""
    try:
        parts = urlsplit(str(url).strip())
        host = parts.hostname or ""
    except ValueError:
        return ""
    if parts.scheme.lower() != "https":
        return ""
    return host.lower().rstrip(".")


def fetchable(url: str) -> str:
    """\a url as it would be fetched, without its fragment, which is never sent.

    Raises `NetError` if it would be refused before any lookup: not https, no
    site, a name or password in it. Nothing is looked up or sent.
    """
    return _target(url).url.split("#", 1)[0]


def redact(url: str) -> str:
    """An address as the log keeps it: no query string, fragment or credentials."""
    try:
        parts = urlsplit(str(url).strip())
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "(an address that could not be read)"
    query = "?…" if parts.query else ""
    return f"{parts.scheme}://{host}{port}{parts.path or '/'}{query}"


def is_public(address: str) -> bool:
    """Whether \a address is on the open internet: not this computer, not a
    private network, not reserved, not multicast."""
    try:
        ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


# -- one hop ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Target:
    url: str
    host: str
    port: int
    path: str


def _target(url: str) -> _Target:
    text = str(url).strip()
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port or 443
    except ValueError:
        raise NetError(f"{text!r} is not an address that can be fetched.") from None
    if parts.scheme.lower() != "https":
        raise NetError("Only https:// addresses are fetched. A page sent over plain http can "
                       "be read or changed by anyone along the way.")
    if parts.username is not None or parts.password is not None:
        raise NetError("Addresses with a name or password in them are not fetched.")
    if not host:
        raise NetError(f"{text!r} does not name a site.")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return _Target(text, host, port, path)


def _resolve(host: str, port: int) -> list[str]:
    """The addresses \a host has: the only lookup Protégé makes, let through the guard."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    with netguard.admitting(hosts=(host,)):
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in found))


def _checked(target: _Target) -> list[str]:
    try:
        found = _resolve(target.host, target.port)
    except OSError as exc:
        raise NetError(f"Could not find {target.host}: {exc}") from None
    if not found:
        raise NetError(f"Could not find {target.host}.")
    private = [address for address in found if not is_public(address)]
    if private:
        raise NetError(f"{target.host} leads to {private[0]}, an address on this computer or a "
                       "private network, so nothing was fetched.")
    return found


def _tls() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class _Pinned(http.client.HTTPSConnection):
    """HTTPS to one checked address, never looked up again, verified against the site's name."""

    def __init__(self, host: str, address: str, port: int, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout, context=_tls())
        self._address = address

    def connect(self) -> None:
        family = socket.AF_INET6 if ":" in self._address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            with netguard.admitting(addresses=((self._address, self.port),)):
                sock.connect((self._address, self.port))
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _open(host: str, address: str, port: int, timeout: float):
    return _Pinned(host, address, port, timeout)


@dataclass(frozen=True)
class _Reply:
    status: int
    reason: str
    content_type: str
    location: str
    body: bytes
    truncated: bool


def _read(reply, host: str, deadline: float, max_bytes: int, limit_s: float) -> tuple[bytes, bool]:
    pieces: list[bytes] = []
    size = 0
    while True:
        if time.monotonic() > deadline:
            raise NetError(f"{host} took longer than the {limit_s:g} seconds allowed.")
        piece = reply.read(min(READ_CHUNK, max_bytes + 1 - size))
        if not piece:
            return b"".join(pieces), False
        pieces.append(piece)
        size += len(piece)
        if size > max_bytes:
            return b"".join(pieces)[:max_bytes], True


def _unpacked(body: bytes, encoding: str, max_bytes: int) -> tuple[bytes, bool]:
    """A compressed body opened, never past \a max_bytes, however small it was packed."""
    name = encoding.strip().lower()
    if name not in ("gzip", "x-gzip", "deflate"):
        raise NetError(f"The site sent the page encoded as {encoding!r}, which is not read.")
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS if "gzip" in name else zlib.MAX_WBITS)
    try:
        out = inflater.decompress(body, max_bytes + 1)
    except zlib.error as exc:
        raise NetError(f"The page could not be unpacked: {exc}") from None
    return out[:max_bytes], len(out) > max_bytes


def _exchange(target: _Target, addresses: list[str], deadline: float, max_bytes: int,
              limit_s: float) -> _Reply:
    problem: Exception | None = None
    for address in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        connection = _open(target.host, address, target.port, remaining)
        try:
            connection.request("GET", target.path, headers={
                "User-Agent": USER_AGENT, "Accept": ACCEPT,
                "Accept-Encoding": "identity", "Connection": "close"})
            reply = connection.getresponse()
            location = reply.getheader("Location") or ""
            if reply.status in REDIRECTS and location:
                return _Reply(reply.status, reply.reason, "", location, b"", False)
            body, truncated = _read(reply, target.host, deadline, max_bytes, limit_s)
            encoding = reply.getheader("Content-Encoding") or ""
            if encoding.strip().lower() not in ("", "identity"):
                body, cut = _unpacked(body, encoding, max_bytes)
                truncated = truncated or cut
            return _Reply(reply.status, reply.reason, reply.getheader("Content-Type") or "",
                          "", body, truncated)
        except ssl.SSLCertVerificationError as exc:
            raise NetError(f"{target.host}'s certificate could not be verified "
                           f"({exc.verify_message}), so nothing was fetched.") from None
        except (OSError, http.client.HTTPException) as exc:
            problem = exc
        finally:
            connection.close()
    if problem is None:
        raise NetError(f"{target.host} took longer than the {limit_s:g} seconds allowed.")
    raise NetError(f"Could not reach {target.host}: {problem}")


# -- a whole fetch -------------------------------------------------------------------------


def _record(audit: AuditLog | None, actor: str, url: str, started: float, *,
            response: Response | None = None, error: str = "") -> None:
    if audit is None:
        return
    result = None
    if response is not None:
        result = {"status": response.status, "bytes": len(response.body),
                  "final": redact(response.url), "redirects": len(response.hops),
                  "truncated": response.truncated}
    audit.tool_call(actor, "net.fetch", {"url": redact(url)}, allowed=response is not None,
                    capability="net.http", scope=host_of(url),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error=error, result=result)


def fetch(url: str, *, policy, audit: AuditLog | None = None, actor: str = ACTOR,
          max_bytes: int = MAX_BYTES, timeout_s: float = TIMEOUT_S) -> Response:
    """Fetch \a url for \a actor, held to \a policy's `net.http`.

    Raises `NetError` with a reason written for the person. Every outcome,
    refusals included, goes into \a audit.
    """
    started = time.monotonic()
    deadline = started + timeout_s
    hops: list[str] = []
    current = str(url)
    try:
        for _ in range(MAX_REDIRECTS + 1):
            target = _target(current)
            decision = policy.allows("net.http", target.host)
            if not decision:
                via = f" It was redirected there from {hops[-1]}." if hops else ""
                raise NetError(f"Not permitted: {decision.reason}.{via}")
            reply = _exchange(target, _checked(target), deadline, max_bytes, timeout_s)
            if reply.location:
                hops.append(redact(target.url))
                current = urljoin(target.url, reply.location)
                continue
            response = Response(target.url, reply.status, reply.reason, reply.content_type,
                                reply.body, reply.truncated, tuple(hops))
            _record(audit, actor, url, started, response=response)
            return response
        raise NetError(f"The address redirected more than {MAX_REDIRECTS} times, so it was left.")
    except NetError as exc:
        _record(audit, actor, url, started, error=str(exc))
        raise
