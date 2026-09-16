"""The signed-in path (C5): the one request that carries anything of the person's.

`fetch` carries nothing of theirs. `call` carries a connected account's sign-in,
so it is held tighter: the account's own permission, only the hosts named, no
redirect followed, the sign-in asked for only when everything else has passed,
a form sent at most once, and nothing of either in the activity log.

No test touches the network. The resolver and the connection are fakes.
"""

from __future__ import annotations

import json

import pytest

from akira.core.net import NetError
from akira.core.net import client as net
from akira.core.permissions import AuditLog, Policy

GOOGLE = "142.250.180.10"
SECOND = "142.250.180.11"
ACCOUNT = "akira.helper@gmail.com"
MAIL = ("gmail.googleapis.com",)
TOKEN = ("oauth2.googleapis.com",)
LIST = "/gmail/v1/users/me/messages?q=from%3Abank"


class Reply:
    def __init__(self, status=200, body=b"", headers=None, reason="OK"):
        self.status, self.reason = status, reason
        self._body, self._headers = body, dict(headers or {})

    def getheader(self, name, default=None):
        for key, value in self._headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def read(self, size):
        piece, self._body = self._body[:size], self._body[size:]
        return piece


class Wire:
    """Fake connections that keep what was sent, and can fail on cue."""

    def __init__(self, replies, unreachable=(), drop=False):
        self.replies, self.unreachable, self.drop = replies, set(unreachable), drop
        self.requests = []

    def open(self, host, address, port, timeout):
        wire = self

        class Connection:
            def connect(self):
                if address in wire.unreachable:
                    raise OSError(f"{address} unreachable")

            def request(self, method, path, body=None, headers=None):
                if address in wire.unreachable:
                    raise OSError(f"{address} unreachable")
                wire.requests.append({"method": method, "host": host, "address": address,
                                      "path": path, "body": body,
                                      "headers": {k.lower(): v for k, v in (headers or {}).items()}})
                if wire.drop:
                    raise ConnectionResetError("the connection dropped")
                self._reply = wire.replies[(host, path)]

            def getresponse(self):
                return self._reply

            def close(self):
                pass

        return Connection()


@pytest.fixture
def wire(monkeypatch):
    def install(replies, found=None, **options):
        cable = Wire(replies, **options)
        monkeypatch.setattr(net, "_resolve", lambda host, port: (found or {}).get(host, [GOOGLE]))
        monkeypatch.setattr(net, "_open", cable.open)
        return cable
    return install


def mailbox(*accounts) -> Policy:
    policy = Policy()
    policy.grant("mail.read", accounts)
    return policy


def json_reply(body=b'{"messages": []}', status=200, **headers):
    return Reply(status, body, {"Content-Type": "application/json", **headers})


def read_mail(policy, *, url=f"https://gmail.googleapis.com{LIST}", audit=None, bearer=None):
    return net.call("GET", url, policy=policy, capability="mail.read", scope=ACCOUNT,
                    hosts=MAIL, audit=audit, actor="tester",
                    bearer=bearer or (lambda: "ya29.a-secret-sign-in"))


def test_a_signed_in_read_carries_the_sign_in_and_the_log_keeps_none_of_it(wire, tmp_path):
    cable = wire({("gmail.googleapis.com", LIST): json_reply()})
    audit = AuditLog(tmp_path / "audit.jsonl")
    reply = read_mail(mailbox(ACCOUNT), audit=audit)
    assert reply.ok and reply.text() == '{"messages": []}'

    [sent] = cable.requests
    assert (sent["method"], sent["address"], sent["body"]) == ("GET", GOOGLE, None)
    assert sent["headers"]["authorization"] == "Bearer ya29.a-secret-sign-in"
    assert "cookie" not in sent["headers"]

    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "net.call" in log and "https://gmail.googleapis.com/gmail/v1/users/me/messages?…" in log
    assert ACCOUNT in log, "the log should say which account was used"
    assert "ya29" not in log and "bank" not in log, "the sign-in or the query reached the log"


def test_without_the_account_allowed_nothing_is_sent_and_no_sign_in_is_fetched(wire):
    cable = wire({("gmail.googleapis.com", LIST): json_reply()})
    asked = []
    with pytest.raises(NetError, match="Not permitted"):
        read_mail(mailbox("someone.else@gmail.com"), bearer=lambda: asked.append(1) or "t")
    assert cable.requests == [] and asked == []


def test_a_site_grant_is_not_an_account_grant(wire):
    wire({("gmail.googleapis.com", LIST): json_reply()})
    policy = Policy()
    policy.grant("net.http", ("googleapis.com",))
    with pytest.raises(NetError, match="Not permitted"):
        read_mail(policy)


def test_only_the_hosts_named_are_reached(wire):
    cable = wire({("evil.example.com", "/collect"): json_reply()})
    asked = []
    with pytest.raises(NetError, match="not where mail.read sends anything"):
        read_mail(mailbox(ACCOUNT), url="https://evil.example.com/collect",
                  bearer=lambda: asked.append(1) or "t")
    assert cable.requests == [] and asked == []


def test_a_redirect_is_never_followed_with_the_sign_in(wire, tmp_path):
    cable = wire({("gmail.googleapis.com", LIST):
                  json_reply(b"", 302, Location="https://gmail.googleapis.com.evil.example/take")})
    audit = AuditLog(tmp_path / "audit.jsonl")
    with pytest.raises(NetError, match="never followed"):
        read_mail(mailbox(ACCOUNT), audit=audit)
    assert len(cable.requests) == 1, "the sign-in was carried on to where it was sent"
    assert "ya29" not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_the_sign_in_never_goes_to_this_computer_or_its_network(wire):
    cable = wire({("gmail.googleapis.com", LIST): json_reply()},
                 found={"gmail.googleapis.com": ["127.0.0.1"]})
    asked = []
    with pytest.raises(NetError, match="private network"):
        read_mail(mailbox(ACCOUNT), bearer=lambda: asked.append(1) or "t")
    assert cable.requests == [] and asked == []


def test_only_https(wire):
    wire({})
    with pytest.raises(NetError, match="Only https"):
        read_mail(mailbox(ACCOUNT), url=f"http://gmail.googleapis.com{LIST}")


def exchange(policy, audit=None):
    return net.call("POST", "https://oauth2.googleapis.com/token", policy=policy,
                    capability="mail.read", scope=ACCOUNT, hosts=TOKEN, audit=audit,
                    form={"code": "4/0-a-code", "client_secret": "GOCSPX-shh",
                          "grant_type": "authorization_code"})


def test_a_form_is_posted_and_the_log_keeps_none_of_it(wire, tmp_path):
    cable = wire({("oauth2.googleapis.com", "/token"): json_reply(b'{"access_token": "ya29.x"}')})
    audit = AuditLog(tmp_path / "audit.jsonl")
    assert exchange(mailbox(ACCOUNT), audit).ok
    [sent] = cable.requests
    assert sent["method"] == "POST"
    assert sent["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert b"client_secret=GOCSPX-shh" in sent["body"] and b"code=4%2F0-a-code" in sent["body"]
    assert "authorization" not in sent["headers"]
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "GOCSPX" not in log and "4/0-a-code" not in log and "ya29" not in log


def test_a_post_that_may_have_arrived_is_not_sent_again(wire):
    cable = wire({("oauth2.googleapis.com", "/token"): json_reply()},
                 found={"oauth2.googleapis.com": [GOOGLE, SECOND]}, drop=True)
    with pytest.raises(NetError, match="not sent again"):
        exchange(mailbox(ACCOUNT))
    assert len(cable.requests) == 1, "a form that may have arrived was sent a second time"


def test_a_post_moves_on_from_an_address_it_could_not_reach(wire):
    cable = wire({("oauth2.googleapis.com", "/token"): json_reply()},
                 found={"oauth2.googleapis.com": [GOOGLE, SECOND]}, unreachable={GOOGLE})
    assert exchange(mailbox(ACCOUNT)).ok
    assert [sent["address"] for sent in cable.requests] == [SECOND]


def test_a_document_is_posted_as_json_and_never_logged(wire, tmp_path):
    cable = wire({("gmail.googleapis.com", "/gmail/v1/users/me/messages/send"):
                  json_reply(b'{"id": "18a9"}')})
    audit = AuditLog(tmp_path / "audit.jsonl")
    policy = Policy()
    policy.grant("mail.send", (ACCOUNT,))
    reply = net.call("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                     policy=policy, capability="mail.send", scope=ACCOUNT, hosts=MAIL,
                     audit=audit, bearer=lambda: "ya29.x", payload={"raw": "a-private-message"})
    assert reply.ok
    [sent] = cable.requests
    assert sent["headers"]["content-type"].startswith("application/json")
    assert sent["body"] == b'{"raw": "a-private-message"}'
    assert "a-private-message" not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_a_delete_is_sent_once_however_the_line_behaves(wire):
    path = "/calendar/v3/calendars/primary/events/abc"
    cable = wire({("www.googleapis.com", path): json_reply(b"", 204)},
                 found={"www.googleapis.com": [GOOGLE, SECOND]}, drop=True)
    policy = Policy()
    policy.grant("calendar.write", (ACCOUNT,))
    with pytest.raises(NetError, match="not sent again"):
        net.call("DELETE", f"https://www.googleapis.com{path}", policy=policy,
                 capability="calendar.write", scope=ACCOUNT, hosts=("www.googleapis.com",))
    assert len(cable.requests) == 1


def test_a_patch_carries_only_what_changes_and_is_sent_once(wire, tmp_path):
    path = "/calendar/v3/calendars/primary/events/abc"
    cable = wire({("www.googleapis.com", path): json_reply(b'{"id": "abc"}')},
                 found={"www.googleapis.com": [GOOGLE, SECOND]}, drop=True)
    policy = Policy()
    policy.grant("calendar.write", (ACCOUNT,))
    audit = AuditLog(tmp_path / "audit.jsonl")
    change = {"start": {"dateTime": "2026-09-18T16:00:00+01:00"}}
    with pytest.raises(NetError, match="not sent again"):
        net.call("PATCH", f"https://www.googleapis.com{path}", policy=policy,
                 capability="calendar.write", scope=ACCOUNT, hosts=("www.googleapis.com",),
                 audit=audit, bearer=lambda: "ya29.x", payload=change)
    [sent] = cable.requests
    assert sent["method"] == "PATCH" and sent["body"] == json.dumps(change).encode("utf-8")
    assert "2026-09-18T16" not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("method, hosts, form, payload, reason", [
    ("PUT", MAIL, None, None, "GET, POST, PATCH or DELETE"),
    ("PATCH", MAIL, None, None, "carries a form or a payload"),
    ("GET", (), None, None, "must name the hosts"),
    ("POST", MAIL, None, None, "carries a form or a payload"),
    ("GET", MAIL, {"a": "b"}, None, "carries a form or a payload"),
    ("DELETE", MAIL, None, {"a": "b"}, "carries a form or a payload"),
    ("POST", MAIL, {"a": "b"}, {"c": "d"}, "carries a form or a payload"),
])
def test_what_a_signed_in_request_may_be(method, hosts, form, payload, reason):
    with pytest.raises(ValueError, match=reason):
        net.call(method, f"https://gmail.googleapis.com{LIST}", policy=mailbox(ACCOUNT),
                 capability="mail.read", scope=ACCOUNT, hosts=hosts, form=form, payload=payload)
