"""Handing a page to the person (C8): a window of their own, and nothing read from it.

When what is left is the person's to do — paying, signing in — the page opens in
a window on their screen, carrying what Akira's browser held for the page's
sites, such as a cart. Akira's own browser closes first. The window may reach
any site on the open internet, since every page in it is one the person chose,
but still only through the proxy, over https. It outlives the agent's work and
closes when the person closes it, or when Akira closes.

The site is the stand-in from test_browser.py, reached through the proxy, so
nothing leaves this computer. Here the "window" is headless, so a test run puts
no window in front of anyone.
"""

from __future__ import annotations

import socket
import time

import pytest

from akira.core.agents.roles import ERRANDS
from akira.core.net import browser
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import ToolContext, default_registry
from akira.security import netguard

from test_browser import page, site  # noqa: F401 - `site` is the stand-in fixture

SHOP = page(
    "<h1>Your basket</h1><p>3 lamps, 45.00</p>"
    "<iframe src='https://payments.example/checkout'></iframe>"
    "<iframe src='https://private.example/'></iframe>",
    title="Basket", headers={"Set-Cookie": "basket=3-lamps; Secure; Path=/"})


@pytest.fixture
def shop(site, tmp_path, monkeypatch):  # noqa: F811 - the stand-in fixture, used by name
    monkeypatch.setattr(browser, "HANDOVER_WINDOW", False)
    site.pages[("example.com", "/basket")] = SHOP
    site.pages[("payments.example", "/checkout")] = page("<p>Pay here</p>", title="Pay")
    made = []

    def context():
        policy = Policy()
        policy.grant("web.browse", ("example.com",))
        policy.grant("web.submit", ("example.com",))
        ctx = ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                          secrets=SecretStore(tmp_path / "secrets"), actor="errands")
        made.append(ctx)
        return ctx

    yield site, context
    for ctx in made:
        ctx.finish()
    browser.close_handed_over()


def use(name, arguments, ctx):
    return default_registry().invoke(name, arguments, ctx)


def seen_eventually(stand_in, wanted, seconds=8.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = [entry for entry in stand_in.seen if wanted(entry)]
        if found:
            return found
        time.sleep(0.1)
    return []


def handed(ctx):
    opened = use("open_page", {"url": "https://example.com/basket"}, ctx)
    if not opened.ok and opened.content.startswith("The browser is not installed"):
        pytest.skip(opened.content)
    assert opened.ok, opened.content
    return use("hand_over_page", {"site": "example.com"}, ctx)


def test_the_page_goes_to_the_person_with_its_basket_and_akiras_browser_closes(shop):
    stand_in, context = shop
    ctx = context()
    result = handed(ctx)
    assert result.ok, result.content
    assert "open in a window on the person's screen" in result.content
    assert "Nothing more is read from that window" in result.content
    assert "3 lamps" not in result.content, "the window was read after it was handed over"
    assert ctx.extra["browser"].closed, "Akira's own browser stayed open beside the person's"
    carried = seen_eventually(stand_in, lambda e: e[1] == "/basket" and "basket=3-lamps" in e[2])
    assert carried, "the window did not carry the basket"


def test_the_window_reaches_what_the_person_chooses_but_only_through_the_proxy(shop):
    stand_in, context = shop
    ctx = context()
    assert not [e for e in stand_in.seen if e[0] == "payments.example"]
    assert handed(ctx).ok
    assert seen_eventually(stand_in, lambda e: e[0] == "payments.example"), \
        "a payment page the person would go to was refused"
    assert ("10.0.0.5", 443) not in stand_in.dialled, "the window reached a private network"


def test_akira_reads_nothing_from_the_window_and_cannot_use_it(shop):
    _, context = shop
    ctx = context()
    assert handed(ctx).ok
    for name, arguments in [("fill_in", {"site": "example.com", "entries": ["1: x"]}),
                            ("press_button", {"site": "example.com", "number": 1}),
                            ("hand_over_page", {"site": "example.com"})]:
        refused = use(name, arguments, ctx)
        assert not refused.ok and "No page is open" in refused.content, name


def test_the_window_outlives_the_work_and_closes_with_akira(shop):
    _, context = shop
    ctx = context()
    assert handed(ctx).ok
    [window] = list(browser._HANDED_OVER)
    ctx.finish()
    assert window.open, "the person's window closed when the agent's work ended"
    port = window.proxy_port
    browser.close_handed_over()
    assert not window.open and browser._HANDED_OVER == []
    probe = socket.socket()
    probe.settimeout(1)
    try:
        with netguard.admitting(addresses=(("127.0.0.1", port),)):
            with pytest.raises(OSError):
                probe.connect(("127.0.0.1", port))
    finally:
        probe.close()


def test_nothing_is_handed_over_without_a_page_open_on_that_site(shop):
    _, context = shop
    ctx = context()
    refused = use("hand_over_page", {"site": "example.com"}, ctx)
    assert not refused.ok and "No page is open" in refused.content
    assert browser._HANDED_OVER == []


def test_the_errands_role_hands_over_what_is_the_persons_to_do():
    assert "hand_over_page" in ERRANDS.tools
    assert "hand it over with hand_over_page, and stop" in ERRANDS.role
