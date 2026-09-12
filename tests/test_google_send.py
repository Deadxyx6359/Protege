"""Sending from Gmail (C5): checked before anyone is asked, held to `mail.send`, sent once.

Google is a fake; nothing leaves this computer. What the person approves is
tested where it is decided, in the registry: see test_account_tools.py.
"""

from __future__ import annotations

import base64
import email
import json

import pytest

from akira.core.connect import gmail, google
from akira.core.connect.google import (SERVICES, AccountStore, ConnectError, GoogleAccounts,
                                       begin, refresh_name)
from akira.core.net import client as net
from akira.core.permissions import Policy, SecretStore, secrets

pytestmark = pytest.mark.skipif(not secrets.available(), reason="needs DPAPI")

ADDRESS = "akira.helper@gmail.com"
SEND = "/gmail/v1/users/me/messages/send"


class Reply:
    def __init__(self, body, status=200):
        self.status, self.reason = status, "OK"
        self._body = json.dumps(body).encode("utf-8")

    def getheader(self, name, default=None):
        return "application/json" if name.lower() == "content-type" else default

    def read(self, size):
        piece, self._body = self._body[:size], self._body[size:]
        return piece


@pytest.fixture
def fake_google(monkeypatch):
    sent = []

    def install(answers):
        def open_(host, address, port, timeout):
            class Connection:
                def connect(self):
                    pass

                def request(self, method, path, body=None, headers=None):
                    sent.append({"method": method, "path": path, "body": body,
                                 "headers": {k.lower(): v for k, v in (headers or {}).items()}})
                    self._reply = Reply(answers[(host, path.split("?", 1)[0])])

                def getresponse(self):
                    return self._reply

                def close(self):
                    pass

            return Connection()

        monkeypatch.setattr(net, "_resolve", lambda host, port: ["142.250.180.10"])
        monkeypatch.setattr(net, "_open", open_)
        return sent
    return install


@pytest.fixture
def accounts(tmp_path):
    vault = SecretStore(tmp_path / "secrets")
    store = AccountStore(tmp_path / "accounts.json")
    vault.put(refresh_name(ADDRESS), "1//lasting")
    store.save(google.Account(ADDRESS, ("mail", "send"), 1.0))
    google._ACCESS[ADDRESS] = ("ya29.held", 10**12)
    yield GoogleAccounts(vault=vault, store=store)
    google._ACCESS.clear()


def allowed(*capabilities) -> Policy:
    policy = Policy()
    for capability in capabilities:
        policy.grant(capability, (ADDRESS,))
    return policy


# -- checked before anyone is asked --------------------------------------------------------


def test_a_message_is_checked_before_anyone_is_asked():
    message = gmail.draft(ADDRESS, "Sam <SAM@example.com>, jo@example.org; sam@example.com",
                          "Lunch\non Friday", "  See you at one.\r\n")
    assert message.to == ("sam@example.com", "jo@example.org")
    assert message.subject == "Lunch on Friday", "a line break reached a header"
    assert message.body == "See you at one."


@pytest.mark.parametrize("to, subject, body, reason", [
    ("not-an-address", "Hi", "Text", "not an email address"),
    ("", "Hi", "Text", "who the message is for"),
    (",".join(f"p{i}@example.com" for i in range(11)), "Hi", "Text", "at most 10"),
    ("sam@example.com", "   ", "Text", "needs a subject"),
    ("sam@example.com", "Hi", "   ", "something to say"),
    ("sam@example.com", "Hi", "x" * 5001, "read all of it"),
])
def test_what_would_not_pass_is_refused_with_why(to, subject, body, reason):
    with pytest.raises(ConnectError, match=reason):
        gmail.draft(ADDRESS, to, subject, body)


def test_without_an_address_connected_for_sending_it_says_where_to_connect_one():
    with pytest.raises(ConnectError, match="Settings, Accounts"):
        gmail.draft("", "sam@example.com", "Hi", "Text")


# -- sent once, held to mail.send ----------------------------------------------------------------


def test_the_message_sent_is_the_one_checked(accounts, fake_google):
    sent = fake_google({("gmail.googleapis.com", SEND): {"id": "18a9", "threadId": "t"}})
    message = gmail.draft(ADDRESS, "sam@example.com", "Lunch", "See you at one.")
    assert gmail.send(accounts, message, policy=allowed("mail.send"), audit=None,
                      actor="secretary") == "18a9"
    [request] = sent
    assert (request["method"], request["path"]) == ("POST", SEND)
    assert request["headers"]["authorization"] == "Bearer ya29.held"
    raw = json.loads(request["body"])["raw"]
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(raw))
    assert (parsed["From"], parsed["To"], parsed["Subject"]) == \
        (ADDRESS, "sam@example.com", "Lunch")
    assert parsed.get_payload(decode=True).decode().strip() == "See you at one."


def test_reading_is_not_sending(accounts, fake_google):
    sent = fake_google({("gmail.googleapis.com", SEND): {"id": "x"}})
    message = gmail.draft(ADDRESS, "sam@example.com", "Lunch", "See you at one.")
    with pytest.raises(ConnectError, match="Not permitted"):
        gmail.send(accounts, message, policy=allowed("mail.read"), audit=None, actor="t")
    assert sent == []


def test_nothing_goes_for_a_service_the_address_is_not_connected_for(accounts, fake_google):
    sent = fake_google({("gmail.googleapis.com", SEND): {"id": "x"}})
    accounts._store.save(google.Account(ADDRESS, ("mail",), 1.0))
    message = gmail.draft(ADDRESS, "sam@example.com", "Lunch", "See you at one.")
    with pytest.raises(ConnectError, match="not connected for Sending from Gmail"):
        gmail.send(accounts, message, policy=allowed("mail.send"), audit=None, actor="t")
    assert sent == []


def test_sending_asks_google_for_sending_alone():
    client = google.Client("1-a.apps.googleusercontent.com", "s")
    pending = begin(client, ADDRESS, ("send",), "http://127.0.0.1:5555/")
    assert "gmail.send" in pending.url and "gmail.readonly" not in pending.url
    assert SERVICES["send"].capability == "mail.send"


def test_connecting_again_for_sending_keeps_reading(tmp_path, monkeypatch):
    vault = SecretStore(tmp_path / "secrets")
    held = GoogleAccounts(vault=vault, store=AccountStore(tmp_path / "accounts.json"))
    held._store.save(google.Account(ADDRESS, ("mail",), 1.0))
    claims = base64.urlsafe_b64encode(json.dumps({"email": ADDRESS}).encode()).rstrip(b"=")
    answers = {"access_token": "ya29.new", "expires_in": 3599, "refresh_token": "1//new",
               "id_token": f"h.{claims.decode()}.s",
               "scope": "openid email https://www.googleapis.com/auth/gmail.readonly "
                        "https://www.googleapis.com/auth/gmail.send"}
    monkeypatch.setattr(net, "_resolve", lambda host, port: ["142.250.180.10"])

    def open_(host, address, port, timeout):
        class Connection:
            def connect(self):
                pass

            def request(self, method, path, body=None, headers=None):
                self._reply = Reply(answers)

            def getresponse(self):
                return self._reply

            def close(self):
                pass

        return Connection()

    monkeypatch.setattr(net, "_open", open_)
    pending = begin(google.Client("1-a.apps.googleusercontent.com", "s"), ADDRESS, ("send",),
                    "http://127.0.0.1:5555/")
    account = held.finish(pending, "4/code", client=google.Client("1-a.apps.googleusercontent.com", "s"),
                          policy=allowed("mail.send"), audit=None)
    google._ACCESS.clear()
    assert set(account.services) == {"mail", "send"}, "connecting for sending dropped reading"
