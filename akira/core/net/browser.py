"""A real browser, held to the one door (C3).

`fetch_page` reads what a site sends. Many pages are only there once a browser
has run their scripts, so `browse_page` opens the page in Chromium, Playwright's
headless build, and reads what it shows; and a `Session` keeps the browser open
across the steps of one piece of work, so a page can be used as a person uses
it: typed into, and its buttons pressed. The browser is a program of its own, in
a process of its own, out of the runtime guard's sight, so it is held from
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
- **Nothing of the person's.** Each browser starts with an empty profile: no
  cookies, logins or history, and nothing is kept once it closes. No downloads,
  no service workers, no pop-ups, no permissions, and Chromium's own sandbox on.
- **Acting is asked for, and some of it never happens.** Typing and pressing
  are the tools' to check, under `web.submit`, and the person's to approve,
  every time (`akira.core.tools.builtin.browsing`). Here, whatever the caller:
  nothing is typed into a field recognisably for a password, a card or account
  number, a code or an identity number; nothing is pressed that pays for
  something; a link is never clicked, only opened by its address, so no script
  of the page's runs because of it; and nothing is done to an element that has
  changed since the page was read.
- **What only the person should do is handed to them** (`Handover`, C8). A page
  ready to pay for, or to sign in to, opens in a window on the person's screen,
  carrying what Akira's browser held for its sites, such as a cart, in memory
  only. Akira's own browser closes first, and nothing is ever read from the
  window. Because every page in it is one the person chose, it may go to any
  site on the open internet — a payment page, a bank's check — but still only
  through the proxy, over https, and logged. It stays open until the person
  closes it, even once the agent's work is over.

`verify_offline.py` checks that only this module imports Playwright, that every
browser it starts is given the proxy, and that nothing here attaches to a
browser started elsewhere or makes a request from Playwright's own driver,
which the proxy would never see.

Chromium is installed once, beside Playwright, like a package:
`python -m playwright install --only-shell chromium`.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from secrets import token_hex

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

#: How long typing into one field, or choosing one option, may take.
FILL_S = 5.0

#: The most of a page's HTML, as the browser has it, that is read.
MAX_HTML = 5_000_000

#: The most controls one look at a page numbers.
MAX_CONTROLS = 150

#: The most of a control's label that is kept.
MAX_LABEL = 120

#: The most fields of a form that are shown before pressing its button.
MAX_FORM_FIELDS = 30

#: How the browser is installed, once, beside Playwright.
INSTALL = "python -m playwright install --only-shell chromium"

#: How the browser with a window, for a page handed to the person, is installed.
INSTALL_WINDOW = "python -m playwright install chromium"

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

#: Each browser's context: nothing of the person's, nothing kept.
CONTEXT: dict = {"accept_downloads": False, "service_workers": "block"}

#: Why a field is not typed into.
SECRET = ("Akira does not type passwords, card or account numbers, codes or identity numbers. "
          "That field is for you to fill in yourself.")

#: Why a button is not pressed.
SPENDING = ("Akira does not press a button that pays for something. That one is for you to "
            "press yourself, when you have checked what it buys.")

#: Why nothing was done to a page that moved on.
CHANGED = ("The page has changed since it was read, so nothing was done. Read it again with "
           "open_page.")


class BrowseError(RuntimeError):
    """A page that could not be opened, read or used, with a reason for the person."""


# -- what can be used on a page ---------------------------------------------------------------

_BUTTON_TYPES = frozenset({"submit", "button", "reset", "image"})
_CHECK_TYPES = frozenset({"checkbox", "radio"})
_FIELD_TYPES = frozenset({"", "text", "email", "search", "tel", "url", "number", "date",
                          "datetime-local", "month", "week", "time", "password"})

#: What a field's `autocomplete` says it is for, when that is a secret.
_SECRET_AUTOCOMPLETE = re.compile(r"(^|\s)(cc-[a-z-]+|current-password|new-password|"
                                  r"one-time-code)(\s|$)")

#: What a field's name, id or label says it is for, when that is a secret.
_SECRET_WORDS = re.compile(
    r"\b(pass ?(word|code|phrase)?|pin|otp|cvv2?|cvc|csc|card ?(number|no)|credit ?card|"
    r"debit ?card|security ?code|verification ?code|iban|swift|routing ?number|"
    r"account ?number|sort ?code|ssn|social ?security|national ?insurance|passport|"
    r"tax ?(id|number)|driv(er'?s|ing) ?licen[cs]e)\b", re.IGNORECASE)

#: What a card field says it is, for telling a form that pays.
_CARD_WORDS = re.compile(r"\b(card ?(number|no)|credit ?card|debit ?card|cvv2?|cvc|csc|"
                         r"expir(y|ation))\b", re.IGNORECASE)

#: What a button that pays says. "Subscribe" and "Donate" are not here: a
#: newsletter says the first, and a form that takes money has a card field, which
#: is caught by what the form holds rather than by what its button says.
_SPENDING_WORDS = re.compile(
    r"\b(pay|pay now|buy|buy now|purchase|place (my |your |the )?order|"
    r"complete (my |your |the )?(order|purchase|payment)|confirm (and |& )?pay|"
    r"checkout and pay)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Control:
    """Something on a page that can be used, as it was when the page was read."""

    number: int
    kind: str
    """`link`, `button`, `field`, `choice` (a list to pick from), `check` (a box or
    a round button), or `other`, which Akira does not use, such as a file picker."""
    label: str
    href: str = ""
    """Where a link goes."""
    action: str = ""
    """Where the form it belongs to sends, when it is in one."""
    secret: bool = False
    """A field for something only the person types."""
    spends: bool = False
    """A button that pays for something."""


@dataclass(frozen=True)
class Field:
    """One of a form's fields, as it stands before its button is pressed."""

    label: str
    value: str
    secret: bool = False
    card: bool = False


def _words(item: dict) -> str:
    return " ".join(str(item.get(key) or "") for key in ("name", "id", "label")) \
        .replace("_", " ").replace("-", " ")


def _is_secret(item: dict) -> bool:
    return (str(item.get("type") or "") == "password"
            or bool(_SECRET_AUTOCOMPLETE.search(str(item.get("autocomplete") or "")))
            or bool(_SECRET_WORDS.search(_words(item))))


def _is_card(item: dict) -> bool:
    return (str(item.get("autocomplete") or "").startswith("cc-")
            or bool(_CARD_WORDS.search(_words(item))))


def _kind(item: dict) -> str:
    tag, kind, role = (str(item.get(key) or "").lower() for key in ("tag", "type", "role"))
    if tag == "a" or role == "link":
        return "link"
    if tag == "button" or role == "button" or (tag == "input" and kind in _BUTTON_TYPES):
        return "button"
    if tag == "select":
        return "choice"
    if tag == "input" and kind in _CHECK_TYPES:
        return "check"
    if tag == "textarea" or item.get("editable") or (tag == "input" and kind in _FIELD_TYPES):
        return "field"
    return "other"


def control(item: dict) -> Control:
    """A control, from what the page said about one."""
    kind = _kind(item)
    label = " ".join(str(item.get("label") or "").split())[:MAX_LABEL]
    return Control(int(item["number"]), kind, label,
                   href=str(item.get("href") or "") if kind == "link" else "",
                   action=str(item.get("action") or ""),
                   secret=kind in ("field", "choice") and _is_secret(item),
                   spends=kind == "button" and bool(_SPENDING_WORDS.search(label)))


#: A control's label, as the person would read it. A field's is what it is for,
#: never what is typed in it, so the label stays the same once it is filled.
_LABEL_OF = r"""
(el) => {
  const tag = el.tagName;
  const type = (el.getAttribute('type') || '').toLowerCase();
  const field = tag === 'TEXTAREA' || tag === 'SELECT'
    || (tag === 'INPUT' && !['submit', 'button', 'reset', 'image'].includes(type));
  const named = (el.labels && el.labels.length ? el.labels[0].innerText : '')
    || el.getAttribute('aria-label') || el.getAttribute('placeholder')
    || el.getAttribute('title') || el.getAttribute('alt')
    || (field ? '' : (tag === 'INPUT' ? el.value : el.innerText))
    || el.getAttribute('name') || '';
  return String(named || '').replace(/\s+/g, ' ').trim();
}
""".strip()

#: Numbers what can be used on the page under an attribute named for this look
#: alone, and says what each is. Runs in the page.
_CONTROLS = r"""
([mark, most, longest]) => {
  const labelOf = LABEL_OF;
  const found = [];
  const picks = 'a[href], button, input, select, textarea, [role="button"], [role="link"], '
    + '[contenteditable="true"]';
  for (const el of document.querySelectorAll(picks)) {
    if (found.length >= most) break;
    const type = (el.getAttribute('type') || '').toLowerCase();
    const box = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (type === 'hidden' || box.width === 0 || box.height === 0
        || style.visibility === 'hidden' || style.display === 'none') continue;
    const number = found.length + 1;
    el.setAttribute(mark, String(number));
    found.push({
      number, tag: el.tagName.toLowerCase(), type,
      role: (el.getAttribute('role') || '').toLowerCase(),
      editable: el.getAttribute('contenteditable') === 'true',
      label: labelOf(el).slice(0, longest),
      href: el.tagName === 'A' ? el.href : '',
      name: el.getAttribute('name') || '', id: el.id || '',
      autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
      action: el.form ? (el.form.action || '') : '',
    });
  }
  return found;
}
""".strip().replace("LABEL_OF", _LABEL_OF)

#: What the form a control belongs to holds right now. Runs in the page.
_FORM = r"""
([mark, number, most]) => {
  const labelOf = LABEL_OF;
  const el = document.querySelector('[' + mark + '="' + number + '"]');
  if (!el || !el.form) return [];
  const out = [];
  for (const f of Array.from(el.form.elements)) {
    const type = (f.getAttribute('type') || '').toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image', 'file'].includes(type)
        || f.tagName === 'BUTTON' || f.tagName === 'FIELDSET' || f.tagName === 'OUTPUT') continue;
    let value = f.value || '';
    if (type === 'checkbox' || type === 'radio') {
      if (!f.checked) continue;
      value = value === 'on' ? 'yes' : value;
    }
    if (f.tagName === 'SELECT') value = f.selectedOptions.length ? f.selectedOptions[0].text : '';
    out.push({label: labelOf(f), value: String(value).slice(0, 2000), type,
              name: f.getAttribute('name') || '', id: f.id || '',
              autocomplete: (f.getAttribute('autocomplete') || '').toLowerCase()});
    if (out.length >= most) break;
  }
  return out;
}
""".strip().replace("LABEL_OF", _LABEL_OF)


# -- a page, as the browser showed it -----------------------------------------------------------


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
    """Every site the browser connected to, in order, for this look."""

    refused: tuple[str, ...] = ()
    """Sites the page asked for and was not let through to, for this look."""

    controls: tuple[Control, ...] = ()
    """What can be used on the page, numbered, until it is read again."""


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
    """What a browser's pages asked for, and what was refused."""

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


def _not_started(exc: Exception, install: str = INSTALL) -> str:
    if "Executable doesn't exist" in str(exc):
        return f"The browser is not installed. It is installed once, like a package: {install}"
    return f"The browser could not be started: {_plain(exc)}"


def _failure(exc: Exception, address: str, start: str, refused: list[tuple[str, str]],
             tunnels_refused: list[tuple[str, str]]) -> BrowseError:
    """Why a page did not open, as the person should hear it."""
    for host, why in refused + tunnels_refused:
        if host == start:
            return BrowseError(why)
    message = _plain(exc)
    if "ERR_TUNNEL_CONNECTION_FAILED" in message and tunnels_refused:
        host, why = tunnels_refused[-1]
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


def _settle(page) -> None:
    """Wait for a page to arrive, and a little for its scripts, without failing if they don't."""
    for state, limit in (("domcontentloaded", LOAD_S), ("networkidle", SETTLE_S)):
        try:
            page.wait_for_load_state(state, timeout=limit * 1000)
        except PlaywrightTimeout:
            pass  # a page still fetching is read as it stands


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


def _yes(text: str) -> bool:
    return str(text).strip().lower() in {"yes", "y", "true", "on", "checked", "ticked", "1"}


# -- a browser kept open -------------------------------------------------------------------------


class Session:
    """A browser kept open across the steps of one piece of work.

    Started on the first page opened and closed by `close`, which whoever holds
    it must call when the work ends. Used only from the thread that started it:
    Playwright's browser belongs to that thread.
    """

    def __init__(self, policy, *, audit: AuditLog | None = None, actor: str = ACTOR) -> None:
        self.policy = policy
        self._audit, self._actor = audit, actor
        self._visit: _Visit | None = None
        self._proxy: Proxy | None = None
        self._driver = None
        self._chromium = None
        self._page = None
        self._thread = 0
        self._mark = ""
        self._controls: dict[int, Control] = {}
        self._status, self._reason, self._title = 0, "", ""
        self.closed = False

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- where it is ----------------------------------------------------------------------------

    @property
    def site(self) -> str:
        """The site the page open is on, or "" before one is."""
        return host_of(self._page.url) if self._page is not None else ""

    @property
    def url(self) -> str:
        return self._page.url if self._page is not None else ""

    @property
    def title(self) -> str:
        return self._title

    def control(self, number: int) -> Control:
        """What the page numbered \a number when it was last read. Raises `BrowseError`."""
        found = self._controls.get(int(number))
        if found is None:
            raise BrowseError(f"Nothing on the page was numbered {number} when it was last "
                              "read. Read it again with open_page.")
        return found

    def form(self, number: int) -> list[Field]:
        """What the form holding control \a number holds now; empty when it is in none."""
        page = self._running()
        try:
            found = page.evaluate(_FORM, [self._mark, int(number), MAX_FORM_FIELDS])
        except PlaywrightError as exc:
            raise BrowseError(f"The form could not be read: {_plain(exc)}") from None
        return [Field(" ".join(str(item.get("label") or "").split())[:MAX_LABEL],
                      str(item.get("value") or ""), _is_secret(item), _is_card(item))
                for item in found if isinstance(item, dict)]

    # -- using it -------------------------------------------------------------------------------

    def open(self, url: str) -> Seen:
        """Open \a url, held to `web.browse` for its site, and read it."""
        started = time.monotonic()
        try:
            try:
                address = fetchable(url)
            except NetError as exc:
                raise BrowseError(str(exc)) from None
            why = verdict(address, navigation=True, policy=self.policy)
            if why:
                raise BrowseError(why)
            page = self._started()
            start, since = host_of(address), self._since()
            try:
                response = page.goto(address, wait_until="domcontentloaded")
            except PlaywrightError as exc:
                self._forget()
                raise _failure(exc, address, start, self._visit.refused[since[0]:],
                               self._proxy.refused[since[1]:]) from None
            self._status = response.status if response else 0
            self._reason = response.status_text if response else ""
            seen = self._look(start, since)
        except BrowseError as exc:
            _record(self._audit, self._actor, url, started, error=str(exc))
            raise
        _record(self._audit, self._actor, url, started, seen=seen)
        return seen

    def fill(self, entries: dict[int, str]) -> Seen:
        """Type each entry into the field it names, and read the page again."""
        self._running()
        start, since = self.site, self._since()
        for number, text in entries.items():
            found = self.control(number)
            if found.secret:
                raise BrowseError(SECRET)
            if found.kind not in ("field", "choice", "check"):
                raise BrowseError(f"Number {number} is a {found.kind}, not something to type into.")
            locator = self._located(found)
            try:
                if found.kind == "field":
                    locator.fill(str(text), timeout=FILL_S * 1000)
                elif found.kind == "choice":
                    locator.select_option(label=str(text), timeout=FILL_S * 1000)
                else:
                    locator.set_checked(_yes(text), timeout=FILL_S * 1000)
            except PlaywrightTimeout:
                raise BrowseError(f"{found.label or f'Number {number}'} could not be filled in "
                                  f"with {text!r}. For a list, give one of its choices exactly."
                                  ) from None
            except PlaywrightError as exc:
                raise BrowseError(f"{found.label or f'Number {number}'} could not be filled in: "
                                  f"{_plain(exc)}") from None
        return self._look(start, since)

    def press(self, number: int) -> Seen:
        """Press the button \a number names, and read what the page became."""
        self._running()
        found = self.control(number)
        if found.kind != "button":
            raise BrowseError(f"Number {number} is a {found.kind}, not a button.")
        if found.spends or any(field.card for field in self.form(number)):
            raise BrowseError(SPENDING)
        start, since = self.site, self._since()
        locator = self._located(found)
        try:
            locator.click(timeout=LOAD_S * 1000)
        except PlaywrightTimeout:
            raise BrowseError(f"{found.label or 'The button'!r} could not be pressed in time."
                              ) from None
        except PlaywrightError as exc:
            raise BrowseError(f"Pressing {found.label or 'the button'!r} did not work: "
                              f"{_plain(exc)}") from None
        self._status, self._reason = 0, ""
        return self._look(start, since)

    def hand_over(self) -> "Handover":
        """Give the page open to the person, in a window of their own, and close this browser.

        What this browser held for the page's sites, such as a cart, goes with
        it, in memory only. From then on Akira reads nothing from the window.
        Raises `BrowseError`.
        """
        page = self._running()
        url = page.url
        if not host_of(url):
            raise BrowseError("Only an https page is handed over.")
        try:
            state = page.context.storage_state()
        except PlaywrightError as exc:
            raise BrowseError(f"The page could not be handed over: {_plain(exc)}") from None
        # Akira's own browser closes first, so it cannot go on using what the
        # person has been given.
        self.close()
        handover = Handover(state, url, audit=self._audit)
        handover.start()
        if self._audit is not None:
            self._audit.tool_call(self._actor, "net.handover", {"url": redact(url)},
                                  allowed=True, capability=CAPABILITY, scope=host_of(url))
        return handover

    def close(self) -> None:
        """Close the browser and the proxy. Safe to call more than once."""
        self.closed = True
        for step in (lambda: self._chromium is not None and self._chromium.close(),
                     lambda: self._driver is not None and self._driver.stop(),
                     lambda: self._proxy is not None and self._proxy.close()):
            try:
                step()
            except Exception:  # noqa: BLE001 - one part failing to close must not keep the rest open
                pass
        self._chromium = self._driver = self._proxy = self._page = None
        self._controls = {}

    # -- inside ---------------------------------------------------------------------------------

    def _started(self):
        if self.closed:
            raise BrowseError("This browser has been closed.")
        if self._page is not None:
            return self._running()
        self._thread = threading.get_ident()
        self._visit = _Visit(self.policy)
        self._proxy = Proxy(self._visit.may, audit=self._audit, actor=self._actor)
        try:
            self._driver = sync_playwright().start()
        except PlaywrightError as exc:
            self.close()
            raise BrowseError(f"The browser could not be started: {_plain(exc)}") from None
        try:
            self._chromium = self._driver.chromium.launch(
                headless=True, chromium_sandbox=True, proxy={"server": self._proxy.server},
                args=list(ARGS), ignore_default_args=list(DROPPED_ARGS))
        except PlaywrightError as exc:
            self.close()
            raise BrowseError(_not_started(exc)) from None
        try:
            context = self._chromium.new_context(**CONTEXT)
            context.route("**/*", self._visit.route)
            self._page = context.new_page()
            self._page.set_default_timeout(LOAD_S * 1000)
        except PlaywrightError as exc:
            self.close()
            raise BrowseError(f"The browser could not be started: {_plain(exc)}") from None
        return self._page

    def _running(self):
        if self.closed or self._page is None:
            raise BrowseError("No page is open. Open one with open_page first.")
        if threading.get_ident() != self._thread:
            raise BrowseError("A browser is used only from the thread that opened it.")
        return self._page

    def _since(self) -> tuple[int, int, int]:
        return (len(self._visit.refused), len(self._proxy.refused), len(self._proxy.reached))

    def _forget(self) -> None:
        """Nothing on a page that could not be read may be used."""
        self._controls, self._mark, self._title = {}, "", ""

    def _located(self, found: Control):
        """The element numbered as \a found was, if it is still what it was."""
        locator = self._page.locator(f'[{self._mark}="{found.number}"]')
        try:
            if locator.count() != 1:
                raise BrowseError(CHANGED)
            now = " ".join(str(locator.evaluate(_LABEL_OF)).split())[:MAX_LABEL]
        except PlaywrightError:
            raise BrowseError(CHANGED) from None
        if now != found.label:
            raise BrowseError(CHANGED)
        return locator

    def _look(self, start: str, since: tuple[int, int, int]) -> Seen:
        page = self._page
        _settle(page)
        final = page.url
        if host_of(final) != start and verdict(final, navigation=True, policy=self.policy):
            self._forget()
            try:
                page.goto("about:blank")
            except PlaywrightError:
                pass
            raise BrowseError(f"{start} sent the browser on to {redact(final)}, which is not a "
                              "site allowed for browsing, so nothing from it was read.")
        try:
            html = _content(page)
            mark = f"data-akira-{token_hex(6)}"
            found = page.evaluate(_CONTROLS, [mark, MAX_CONTROLS, MAX_LABEL])
        except PlaywrightError as exc:
            self._forget()
            raise BrowseError(f"The page could not be read: {_plain(exc)}") from None
        self._mark = mark
        self._controls = {}
        for item in found:
            if isinstance(item, dict):
                try:
                    made = control(item)
                except (KeyError, TypeError, ValueError):
                    continue
                self._controls[made.number] = made
        title, text = readable(html[:MAX_HTML])
        self._title = title
        refused = [host for host, _ in self._visit.refused[since[0]:]]
        refused += [host for host, _ in self._proxy.refused[since[1]:]]
        return Seen(final, self._status, self._reason, title, text,
                    tuple(dict.fromkeys(self._proxy.reached[since[2]:])),
                    tuple(dict.fromkeys(refused)), tuple(self._controls.values()))


# -- a page handed to the person -----------------------------------------------------------------

#: Whether a page handed over opens in a window on the person's screen. Only
#: tests turn it off, so a test run does not put windows in front of anyone.
HANDOVER_WINDOW = True

#: The longest a window handed over stays open. Past this it is closed.
HANDOVER_MAX_S = 4 * 60 * 60

#: How often a window's thread looks up from waiting, to see whether Akira is closing.
_HANDOVER_TICK_S = 1.0

#: Windows handed over and still open.
_HANDED_OVER: list["Handover"] = []
_HANDED_OVER_LOCK = threading.Lock()


class _PersonDriving:
    """The rules for a window the person drives: any site on the open internet, over https.

    Relaxed from `_Visit` because every page in it is one the person chose to go
    to: a payment page, a bank's check, a sign-in. Still through the proxy, so
    still https on port 443 only, still the open internet only, still logged.
    """

    def may(self, host: str) -> str:
        return ""

    def route(self, route, request) -> None:
        url = request.url
        if str(url).split(":", 1)[0].lower() in LOCAL_SCHEMES or host_of(url):
            route.continue_()
        else:
            route.abort("blockedbyclient")


class Handover:
    """A page given to the person, in a window of its own that Akira reads nothing from.

    It carries what Akira's own browser held for the page's sites, such as a
    cart, and nothing else. It runs on a thread of its own, which owns the
    window, so the window outlives the agent that handed it over: the person
    may still be paying when the agent's work has ended. It closes when the
    person closes it, when Akira closes, or after `HANDOVER_MAX_S`.
    """

    def __init__(self, state: dict, url: str, *, audit: AuditLog | None = None) -> None:
        self.url = url
        self._state = state
        self._audit = audit
        self._opened = threading.Event()
        self._stop = threading.Event()
        self._error = ""
        self.proxy_port = 0
        self._thread = threading.Thread(target=self._run, name="handover", daemon=True)

    @property
    def open(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        """Open the window, and return once the page has arrived. Raises `BrowseError`."""
        self._thread.start()
        self._opened.wait(LOAD_S + 30)
        if self._error:
            raise BrowseError(self._error)
        if not self._opened.is_set():
            self.stop()
            raise BrowseError("The window took too long to open, so it was closed.")
        with _HANDED_OVER_LOCK:
            _HANDED_OVER.append(self)

    def stop(self, wait_s: float = 10.0) -> None:
        """Close the window from Akira's side."""
        self._stop.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(wait_s)

    def _run(self) -> None:
        # What was carried is the window's alone from here.
        state, self._state = self._state, {}
        driving = _PersonDriving()
        proxy = driver = chromium = None
        try:
            proxy = Proxy(driving.may, audit=self._audit, actor="person")
            self.proxy_port = proxy.port
            driver = sync_playwright().start()
            try:
                chromium = driver.chromium.launch(
                    headless=not HANDOVER_WINDOW, chromium_sandbox=True,
                    proxy={"server": proxy.server}, args=list(ARGS))
            except PlaywrightError as exc:
                self._error = _not_started(exc, INSTALL_WINDOW)
                return
            context = chromium.new_context(storage_state=state, **CONTEXT)
            context.route("**/*", driving.route)
            page = context.new_page()
            try:
                page.goto(self.url, wait_until="domcontentloaded", timeout=LOAD_S * 1000)
            except PlaywrightError as exc:
                self._error = f"The window could not open {redact(self.url)}: {_plain(exc)}"
                return
            self._opened.set()
            deadline = time.monotonic() + HANDOVER_MAX_S
            while not self._stop.is_set() and time.monotonic() < deadline:
                pages = [p for p in context.pages if not p.is_closed()]
                if not pages:
                    return  # the person closed it
                try:
                    pages[0].wait_for_event("close", timeout=_HANDOVER_TICK_S * 1000)
                except PlaywrightTimeout:
                    continue
                except PlaywrightError:
                    return
        except (PlaywrightError, OSError) as exc:
            self._error = self._error or f"The window could not be opened: {_plain(exc)}"
        finally:
            for step in (lambda: chromium is not None and chromium.close(),
                         lambda: driver is not None and driver.stop(),
                         lambda: proxy is not None and proxy.close()):
                try:
                    step()
                except Exception:  # noqa: BLE001 - one part failing to close must not keep the rest open
                    pass
            with _HANDED_OVER_LOCK:
                if self in _HANDED_OVER:
                    _HANDED_OVER.remove(self)


def close_handed_over() -> None:
    """Close every window handed over and still open. For Akira closing."""
    with _HANDED_OVER_LOCK:
        open_now = list(_HANDED_OVER)
    for handover in open_now:
        handover.stop()


def read(url: str, *, policy, audit: AuditLog | None = None, actor: str = ACTOR) -> Seen:
    """Open \a url in a new browser, held to \a policy, read what it shows, and close it.

    Raises `BrowseError` with a reason written for the person. The visit goes
    into \a audit, and so does each connection the browser made.
    """
    with Session(policy, audit=audit, actor=actor) as session:
        return session.open(url)
