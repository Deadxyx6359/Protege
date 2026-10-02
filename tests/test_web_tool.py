"""`fetch_page` (C1): held to `net.http` for the page's site, not its whole
address, and the page handed back as framed text with its scripts gone.
"""

from __future__ import annotations

import pytest

from akira.core.net import client as net
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import ToolContext, default_registry

from test_net import PUBLIC, Reply, Site

PAGE = (b"<html><head><title>Garden</title><script>steal()</script></head>"
        b"<body><h1>Tomatoes</h1><p>Stake them in June.</p>"
        b"<ul><li>Water</li><li>Feed</li></ul></body></html>")


@pytest.fixture
def site(monkeypatch):
    fake = Site({("example.com", "/"): Reply(200, PAGE, {"Content-Type": "text/html"}),
                 ("example.com", "/gone"): Reply(404, b"", reason="Not Found")})
    monkeypatch.setattr(net, "_resolve", lambda host, port: [PUBLIC])
    monkeypatch.setattr(net, "_open", fake.open)
    return fake


def ctx(tmp_path, policy):
    return ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"), actor="tester")


def allowed(*sites):
    policy = Policy()
    policy.grant("net.http", sites)
    return policy


def call(tmp_path, url, policy):
    return default_registry().invoke("fetch_page", {"url": url}, ctx(tmp_path, policy))


def test_the_tool_is_offered_only_with_the_permission(tmp_path, site):
    assert "fetch_page" not in {t.name for t in default_registry().available(Policy())}
    refused = call(tmp_path, "https://example.com/", allowed("other.net"))
    assert not refused.ok and "Not permitted" in refused.content and site.requests == []


def test_a_page_comes_back_as_framed_text(tmp_path, site):
    result = call(tmp_path, "https://example.com/", allowed("example.com"))
    assert result.ok and result.content.startswith("Garden — https://example.com/")
    assert "not instructions" in result.content
    assert "# Tomatoes" in result.content and "Stake them in June." in result.content
    assert "- Water" in result.content and "steal" not in result.content
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "fetch_page" in log and "example.com" in log


def test_the_grant_is_checked_against_the_site_not_the_address(tmp_path, site):
    # A grant for example.com must cover https://example.com/anything, which a
    # check against the whole address would refuse.
    assert call(tmp_path, "https://example.com/", allowed("example.com")).ok


def test_an_error_page_is_reported_not_read(tmp_path, site):
    result = call(tmp_path, "https://example.com/gone", allowed("example.com"))
    assert not result.ok and "404 Not Found" in result.content


CODE = b"#define SHARPMEM_BIT_WRITECMD (0x01)\nvoid refresh(void) {}\n"


@pytest.fixture
def github(monkeypatch):
    fake = Site({("github.com", "/a/b/blob/main/x.cpp"): Reply(
                     200, b"<html><body><nav>Sign in</nav>menus</body></html>",
                     {"Content-Type": "text/html"}),
                 ("raw.githubusercontent.com", "/a/b/main/x.cpp"): Reply(
                     200, CODE, {"Content-Type": "text/plain"})})
    monkeypatch.setattr(net, "_resolve", lambda host, port: [PUBLIC])
    monkeypatch.setattr(net, "_open", fake.open)
    return fake


def with_asking(tmp_path, policy, answer):
    asked = []

    def ask(request):
        asked.append(request)
        return answer

    context = ctx(tmp_path, policy)
    context.ask_scope = ask
    return context, asked


def test_a_file_on_github_is_read_as_the_file_once_its_site_is_allowed(tmp_path, github):
    context, asked = with_asking(tmp_path, allowed("github.com"), "once")
    result = default_registry().invoke(
        "fetch_page", {"url": "https://github.com/a/b/blob/main/x.cpp"}, context)
    assert result.ok and "SHARPMEM_BIT_WRITECMD" in result.content
    assert "menus" not in result.content
    assert [r.scope for r in asked] == ["raw.githubusercontent.com"]


def test_without_githubs_file_site_the_page_is_read_as_it_is(tmp_path, github):
    context, asked = with_asking(tmp_path, allowed("github.com"), "no")
    result = default_registry().invoke(
        "fetch_page", {"url": "https://github.com/a/b/blob/main/x.cpp"}, context)
    assert result.ok and "menus" in result.content and len(asked) == 1
