"""A real browser, held to the one door (C3).

`fetch_page` reads what a site sends. Many pages are only there once a browser
has run their scripts, so `browse_page` opens the page in Chromium, Playwright's
headless build, and reads what it shows. The browser is a program of its own,
in a process of its own, out of the runtime guard's sight, so it is held from
outside:

- **Everything through the proxy.** It is started with every request sent to
  Akira's proxy on 127.0.0.1 (`proxy.py`), which asks the chokepoint's `tunnel`
  for each connection: https on port 443 only, to the open internet only, each
  logged with its site. Behind a proxy the browser looks no names up itself.
  QUIC, which a proxy cannot carry, is off, and WebRTC may not go around it.
- **Only sites the person allowed.** Every page the browser opens, in the tab
  or in a frame, needs `web.browse` for its site, checked here before the
  request is sent. A page the site sends the browser on to is read only if its
  site is allowed too. What a page loads to show itself, its pictures, styles,
  scripts and data, comes from wherever the page says, as in any browser, but
  over https and from the open internet only.
- **Nothing the page did not ask for.** The proxy lets a connection through
  only to a site the page asked for or the person allowed, so nothing Chromium
  would do by itself gets out.
- **Nothing of the person's.** Each visit is a new browser with an empty
  profile: no cookies, logins or history, and nothing kept afterwards. No
  downloads, no service workers, no pop-ups, no permissions, and Chromium's own
  sandbox on.
- **Reading only.** A page is opened and read. Typing into it, clicking and
  submitting are `web.submit`, irreversible, and not here.

`verify_offline.py` checks that only this module imports Playwright, that every
browser it starts is given the proxy, and that nothing here attaches to a
browser started elsewhere or makes a request from Playwright's own driver,
which the proxy would never see.

Chromium is installed once, beside Playwright, like a package:
`python -m playwright install --only-shell chromium`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from akira.core.permissions import AuditLog

from .client import ACTOR, TIMEOUT_S, NetError, fetchable, host_of, redact
from .page import readable
from .proxy import Proxy

#: What a page needs, for its site.
CAPABILITY = "web.browse"

#: Addresses that go nowhere: a picture written into the page, something the
#: page made itself, an empty frame.
LOCAL_SCHEMES = frozenset({"data", "blob", "about"})

#: How long a page has to arrive.
LOAD_S = TIMEOUT_S

#: How long, once it has arrived, its scripts have to finish fetching.
SETTLE_S = 3.0

#: The most of a page's HTML, as the browser has it, that is read.
MAX_HTML = 5_000_000

#: How the browser is installed, once, beside Playwright.
INSTALL = "python -m playwright install --only-shell chromium"

#: Chromium's switches, beyond Playwright's own, which already turn off
#: background networking, updates, sync and crash reports.
ARGS = (
    "--disable-quic",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--dns-prefetch-disable",
    "--no-pings",
    "--disable-domain-reliability",
)

#: Playwright's switches left off: this one lets pages open pop-ups.
DROPPED_ARGS = ("--disable-popup-blocking",)

#: Each visit's browser context: nothing of the person's, nothing kept.
CONTEXT: dict = {"accept_downloads": False, "service_workers": "block"}


class BrowseError(RuntimeError):
    """A page that could not be opened or read, with a reason for the person."""


@dataclass(frozen=True)
class Seen:
    """A page, as the browser showed it."""

    url: str
    """Where the page ended up, after any redirects."""

    status: int
    reason: str
    title: str
    text: str

    sites: tuple[str, ...] = ()
    """Every site the browser connected to, in order."""

    refused: tuple[str, ...] = ()
    """Sites the page asked for and was not let through to."""


def verdict(url: str, *, navigation: bool, policy) -> str:
    """Why a request a page makes is refused, or "" to let it through.

    A page, in the tab or a frame, needs `web.browse` for its site. Anything
    else a page asks for goes over https; the proxy and the chokepoint still
    hold it to the open internet.
    """
    scheme = str(url).split(":", 1)[0].lower()
    if scheme in LOCAL_SCHEMES:
        return ""
    host = host_of(url)
    if not host:
        return f"Only https is let through, not {redact(url)}."
    if navigation:
        decision = policy.allows(CAPABILITY, host)
        if not decision:
            return f"Not permitted: {decision.reason}."
    return ""


class _Visit:
    """One visit: what its page asked for, and what was refused."""

    def __init__(self, policy) -> None:
        self.policy = policy
        self._lock = threading.Lock()
        self._asked: set[str] = set()
        self.refused: list[tuple[str, str]] = []

    def may(self, host: str) -> str:
        """For the proxy: "" for a site the page asked for or the person allowed, or why not."""
        with self._lock:
            if host in self._asked:
                return ""
        decision = self.policy.allows(CAPABILITY, host)
        return "" if decision else f"Not permitted: {decision.reason}."

    def route(self, route, request) -> None:
        """Every request the page makes, before it is sent."""
        url = request.url
        why = verdict(url, navigation=request.is_navigation_request(), policy=self.policy)
        host = host_of(url)
        with self._lock:
            if why:
                self.refused.append((host or redact(url), why))
            elif host:
                self._asked.add(host)
        if why:
            route.abort("blockedbyclient")
        else:
            route.continue_()


def _plain(exc: Exception) -> str:
    """Playwright's message: its first line, without the call it came from."""
    lines = str(exc).strip().splitlines()
    first = lines[0] if lines else type(exc).__name__
    call, sep, rest = first.partition(": ")
    return rest if sep and "." in call and " " not in call else first


def _not_started(exc: Exception) -> str:
    if "Executable doesn't exist" in str(exc):
        return f"The browser is not installed. It is installed once, like a package: {INSTALL}"
    return f"The browser could not be started: {_plain(exc)}"


def _failure(exc: Exception, address: str, start: str, visit: _Visit,
             proxy: Proxy) -> BrowseError:
    """Why a page did not open, as the person should hear it."""
    for host, why in visit.refused + proxy.refused:
        if host == start:
            return BrowseError(why)
    message = _plain(exc)
    if "ERR_TUNNEL_CONNECTION_FAILED" in message and proxy.refused:
        host, why = proxy.refused[-1]
        return BrowseError(f"{start} sent the browser on to {host}, which was not let through. "
                           f"{why}")
    if "Download is starting" in message:
        return BrowseError(f"{redact(address)} is a download, and the browser takes none.")
    if isinstance(exc, PlaywrightTimeout):
        return BrowseError(f"{start} took longer than the {LOAD_S:g} seconds allowed.")
    return BrowseError(f"The browser could not open {redact(address)}: {message}")


def _content(page) -> str:
    """The page's HTML as the browser has it now, its scripts' changes included."""
    try:
        return page.content()
    except PlaywrightError:
        # It was moving on by itself; read it once it has arrived.
        page.wait_for_load_state("domcontentloaded")
        return page.content()


def _open(address: str, visit: _Visit, proxy: Proxy) -> Seen:
    start = host_of(address)
    try:
        driver = sync_playwright().start()
    except PlaywrightError as exc:
        raise BrowseError(f"The browser could not be started: {_plain(exc)}") from None
    try:
        try:
            chromium = driver.chromium.launch(headless=True, chromium_sandbox=True,
                                              proxy={"server": proxy.server}, args=list(ARGS),
                                              ignore_default_args=list(DROPPED_ARGS))
        except PlaywrightError as exc:
            raise BrowseError(_not_started(exc)) from None
        try:
            context = chromium.new_context(**CONTEXT)
            context.route("**/*", visit.route)
            page = context.new_page()
            page.set_default_timeout(LOAD_S * 1000)
            try:
                response = page.goto(address, wait_until="domcontentloaded")
            except PlaywrightError as exc:
                raise _failure(exc, address, start, visit, proxy) from None
            try:
                page.wait_for_load_state("networkidle", timeout=SETTLE_S * 1000)
            except PlaywrightTimeout:
                pass  # a page still fetching is read as it stands
            final = page.url
            if host_of(final) != start and verdict(final, navigation=True, policy=visit.policy):
                raise BrowseError(f"{start} sent the browser on to {redact(final)}, which is not "
                                  "a site allowed for browsing, so nothing from it was read.")
            html = _content(page)
        except PlaywrightError as exc:
            raise BrowseError(f"The browser could not read {redact(address)}: "
                              f"{_plain(exc)}") from None
        finally:
            chromium.close()
    finally:
        driver.stop()
    title, text = readable(html[:MAX_HTML])
    return Seen(final, response.status if response else 0,
                response.status_text if response else "", title, text,
                tuple(dict.fromkeys(proxy.reached)),
                tuple(dict.fromkeys(host for host, _ in visit.refused + proxy.refused)))


def _record(audit: AuditLog | None, actor: str, url: str, started: float, *,
            seen: Seen | None = None, error: str = "") -> None:
    if audit is None:
        return
    result = None
    if seen is not None:
        result = {"status": seen.status, "final": redact(seen.url), "sites": len(seen.sites),
                  "refused": len(seen.refused)}
    audit.tool_call(actor, "net.browse", {"url": redact(url)}, allowed=seen is not None,
                    capability=CAPABILITY, scope=host_of(url),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error=error, result=result)


def read(url: str, *, policy, audit: AuditLog | None = None, actor: str = ACTOR) -> Seen:
    """Open \a url in a new browser, held to \a policy, and read what it shows.

    Raises `BrowseError` with a reason written for the person. The visit goes
    into \a audit, and so does each connection the browser made.
    """
    started = time.monotonic()
    try:
        try:
            address = fetchable(url)
        except NetError as exc:
            raise BrowseError(str(exc)) from None
        why = verdict(address, navigation=True, policy=policy)
        if why:
            raise BrowseError(why)
        visit = _Visit(policy)
        proxy = Proxy(visit.may, audit=audit, actor=actor)
        try:
            seen = _open(address, visit, proxy)
        finally:
            proxy.close()
    except BrowseError as exc:
        _record(audit, actor, url, started, error=str(exc))
        raise
    _record(audit, actor, url, started, seen=seen)
    return seen
