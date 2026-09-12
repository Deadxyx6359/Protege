"""Connecting a Google address (C5): the client file, the sign-in, and the sealed sign-in.

Google is a fake: the resolver and connections are replaced, as in
test_net_call.py, and the person's browser is a thread that answers the
listener on 127.0.0.1 the way Google's page would send it back. Nothing leaves
this computer.
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import threading
from urllib.parse import parse_qs

import pytest

from akira.core.connect import google
from akira.core.connect.google import (AccountStore, ConnectError, GoogleAccounts, begin,
                                       read_client_file, refresh_name, sign_in)
from akira.core.net import client as net
from akira.core.net import query_value
from akira.core.net.loopback import HOST
from akira.core.permissions import AuditLog, Policy, SecretStore, secrets
from akira.core.review import secret_owner
from akira.security import netguard

pytestmark = pytest.mark.skipif(not secrets.available(), reason="needs DPAPI")

ADDRESS = "akira.helper@gmail.com"
GOOGLE = "142.250.180.10"
CLIENT_ID = "1234-abc.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-a-client-secret"
MAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class Reply:
    def __init__(self, status=200, body=b"", headers=None, reason="OK"):
        self.status, self.reason = status, reason
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self._headers = {"Content-Type": "application/json", **(headers or {})}

    def getheader(self, name, default=None):
        for key, value in self._headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def read(self, size):
        piece, self._body = self._body[:size], self._body[size:]
        return piece


class FakeGoogle:
    """Answers by site and path, from a reply or a function of the request."""

    def __init__(self, answers):
        self.answers, self.requests = answers, []

    def open(self, host, address, port, timeout):
        fake = self

        class Connection:
            def connect(self):
                pass

            def request(self, method, path, body=None, headers=None):
                sent = {"method": method, "host": host, "path": path,
                        "form": {k: v[0] for k, v in parse_qs((body or b"").decode()).items()},
                        "headers": {k.lower(): v for k, v in (headers or {}).items()}}
                fake.requests.append(sent)
                answer = fake.answers[(host, path.split("?", 1)[0])]
                self._reply = answer(sent) if callable(answer) else answer

            def getresponse(self):
                return self._reply

            def close(self):
                pass

        return Connection()

    def sent_to(self, path):
        return [r for r in self.requests if r["path"].split("?", 1)[0] == path]


@pytest.fixture
def fake_google(monkeypatch):
    def install(answers):
        fake = FakeGoogle(answers)
        monkeypatch.setattr(net, "_resolve", lambda host, port: [GOOGLE])
        monkeypatch.setattr(net, "_open", fake.open)
        return fake
    return install


@pytest.fixture(autouse=True)
def no_held_sign_ins():
    google._ACCESS.clear()
    yield
    google._ACCESS.clear()


@pytest.fixture
def vault(tmp_path):
    return SecretStore(tmp_path / "secrets")


@pytest.fixture
def accounts(vault, tmp_path):
    held = GoogleAccounts(vault=vault, store=AccountStore(tmp_path / "accounts.json"))
    client_file = tmp_path / "client_secret.json"
    client_file.write_text(json.dumps({"installed": {
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]}}), encoding="utf-8")
    held.set_client_file(client_file)
    return held


def allowed(*capabilities, address=ADDRESS) -> Policy:
    policy = Policy()
    for capability in capabilities:
        policy.grant(capability, (address,))
    return policy


def id_token(email, verified=True):
    claims = base64.urlsafe_b64encode(json.dumps(
        {"email": email, "email_verified": verified}).encode()).rstrip(b"=").decode()
    return f"header.{claims}.signature"


def tokens(email=ADDRESS, scope=f"openid email {MAIL_SCOPE}", lasting="1//lasting-sign-in"):
    body = {"access_token": "ya29.short", "expires_in": 3599, "scope": scope,
            "token_type": "Bearer", "id_token": id_token(email)}
    if lasting:
        body["refresh_token"] = lasting
    return Reply(200, body)


def browser(code="4/0-the-code", error=""):
    """Plays the person's browser: Google's page, then being sent back to the listener."""
    opened = []

    def open_page(url):
        opened.append(url)
        back = query_value(url, "redirect_uri")
        port = int(back.rsplit(":", 1)[1].strip("/"))
        answer = f"error={error}" if error else f"code={code.replace('/', '%2F')}"
        target = f"/?state={query_value(url, 'state')}&{answer}"

        def go():
            sock = socket.socket()
            sock.settimeout(5)
            with netguard.admitting(addresses=((HOST, port),)):
                sock.connect((HOST, port))
            sock.sendall(f"GET {target} HTTP/1.1\r\nHost: {HOST}\r\n\r\n".encode())
            while sock.recv(4096):
                pass
            sock.close()

        threading.Thread(target=go, daemon=True).start()

    return open_page, opened


# -- the client file -------------------------------------------------------------------------


def test_a_desktop_client_file_is_read_and_sealed(accounts, vault):
    assert accounts.client().client_id == CLIENT_ID
    assert "google.client" in vault.names()
    assert CLIENT_SECRET.encode() not in (vault.directory / "google.client.dpapi").read_bytes()


@pytest.mark.parametrize("content, reason", [
    ({"web": {"client_id": CLIENT_ID, "client_secret": "s"}}, "web application"),
    ({"hello": "world"}, "not a Google client file"),
    ({"installed": {"client_id": "someone", "client_secret": "s"}}, "not a Google client file"),
    ({"installed": {"client_id": CLIENT_ID, "client_secret": "s",
                    "token_uri": "https://collector.example/token"}}, "not to Google"),
])
def test_anything_else_is_refused_with_a_reason(tmp_path, content, reason):
    path = tmp_path / "client.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ConnectError, match=reason):
        read_client_file(path)


# -- the page ----------------------------------------------------------------------------------


def test_the_page_asks_google_for_reading_only_with_pkce_and_a_state(accounts):
    pending = begin(accounts.client(), ADDRESS, ("mail", "calendar"), "http://127.0.0.1:5555/")
    assert pending.url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    scopes = query_value(pending.url, "scope").split()
    assert scopes == ["openid", "email", MAIL_SCOPE,
                      "https://www.googleapis.com/auth/calendar.readonly"]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(pending.verifier.encode()).digest()).rstrip(b"=").decode()
    assert query_value(pending.url, "code_challenge") == challenge
    assert query_value(pending.url, "code_challenge_method") == "S256"
    assert query_value(pending.url, "state") == pending.state and len(pending.state) >= 24
    assert query_value(pending.url, "login_hint") == ADDRESS
    assert pending.verifier not in pending.url


# -- connecting ----------------------------------------------------------------------------------


def test_connecting_seals_the_lasting_sign_in_and_logs_none_of_it(accounts, vault, fake_google,
                                                                  tmp_path):
    fake = fake_google({("oauth2.googleapis.com", "/token"): tokens()})
    audit = AuditLog(tmp_path / "audit.jsonl")
    open_page, opened = browser()
    account = sign_in(accounts, "Akira.Helper@gmail.com", ["mail"], policy=allowed("mail.read"),
                      audit=audit, open_page=open_page, wait_s=10)
    assert account.address == ADDRESS and account.services == ("mail",)
    assert accounts.account(ADDRESS) is not None

    [exchange] = fake.sent_to("/token")
    assert exchange["form"]["grant_type"] == "authorization_code"
    assert exchange["form"]["code"] == "4/0-the-code"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(
        exchange["form"]["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == query_value(opened[0], "code_challenge"), "the verifier was not the page's"

    name = refresh_name(ADDRESS)
    assert vault.get(name) == "1//lasting-sign-in" and "gmail" not in name and "@" not in name
    assert secret_owner(name) == "Google accounts"
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "connect_account" in log
    for secret in ("1//lasting", "ya29", "4/0-the-code", CLIENT_SECRET):
        assert secret not in log, f"{secret} reached the activity log"


def test_nothing_happens_for_an_address_nobody_allowed(accounts, fake_google):
    fake = fake_google({})
    open_page, opened = browser()
    with pytest.raises(ConnectError, match="Not permitted"):
        sign_in(accounts, ADDRESS, ["mail", "calendar"], policy=allowed("mail.read"),
                audit=None, open_page=open_page)
    assert opened == [] and fake.requests == []


def test_signing_in_as_someone_else_connects_nothing_and_hands_it_back(accounts, vault,
                                                                       fake_google):
    fake = fake_google({("oauth2.googleapis.com", "/token"): tokens(email="someone@gmail.com"),
                        ("oauth2.googleapis.com", "/revoke"): Reply(200, {})})
    open_page, _ = browser()
    with pytest.raises(ConnectError, match="You signed in as someone@gmail.com"):
        sign_in(accounts, ADDRESS, ["mail"], policy=allowed("mail.read"), audit=None,
                open_page=open_page, wait_s=10)
    assert accounts.accounts() == [] and not vault.has(refresh_name(ADDRESS))
    [revoke] = fake.sent_to("/revoke")
    assert revoke["form"]["token"] == "1//lasting-sign-in"


def test_reading_unticked_on_googles_page_connects_nothing(accounts, fake_google):
    fake = fake_google({("oauth2.googleapis.com", "/token"): tokens(scope="openid email"),
                        ("oauth2.googleapis.com", "/revoke"): Reply(200, {})})
    open_page, _ = browser()
    with pytest.raises(ConnectError, match="not given permission to read"):
        sign_in(accounts, ADDRESS, ["mail"], policy=allowed("mail.read"), audit=None,
                open_page=open_page, wait_s=10)
    assert accounts.accounts() == [] and fake.sent_to("/revoke")


def test_a_refusal_on_googles_page_connects_nothing(accounts, fake_google):
    fake = fake_google({})
    open_page, _ = browser(error="access_denied")
    with pytest.raises(ConnectError, match="access_denied"):
        sign_in(accounts, ADDRESS, ["mail"], policy=allowed("mail.read"), audit=None,
                open_page=open_page, wait_s=10)
    assert fake.requests == [] and accounts.accounts() == []


# -- using it ------------------------------------------------------------------------------------


def connected(accounts, vault, services=("mail",)):
    vault.put(refresh_name(ADDRESS), "1//lasting-sign-in")
    accounts._store.save(google.Account(ADDRESS, tuple(services), 1.0))


def test_a_held_sign_in_is_used_and_renewed_only_when_it_runs_out(accounts, vault, fake_google):
    connected(accounts, vault)
    fake = fake_google({("oauth2.googleapis.com", "/token"):
                        lambda sent: Reply(200, {"access_token": "ya29.renewed", "expires_in": 3599})})
    now = [1000.0]
    accounts._clock = lambda: now[0]
    policy = allowed("mail.read")
    assert accounts.token(ADDRESS, "mail", policy=policy, audit=None, actor="t") == "ya29.renewed"
    assert accounts.token(ADDRESS, "mail", policy=policy, audit=None, actor="t") == "ya29.renewed"
    assert len(fake.sent_to("/token")) == 1, "a held sign-in was renewed anyway"
    [renewal] = fake.sent_to("/token")
    assert renewal["form"]["grant_type"] == "refresh_token"
    assert renewal["form"]["refresh_token"] == "1//lasting-sign-in"
    now[0] += 3600
    accounts.token(ADDRESS, "mail", policy=policy, audit=None, actor="t")
    assert len(fake.sent_to("/token")) == 2


def test_a_withdrawn_sign_in_asks_the_person_to_connect_again(accounts, vault, fake_google):
    connected(accounts, vault)
    fake_google({("oauth2.googleapis.com", "/token"):
                 Reply(400, {"error": "invalid_grant", "error_description": "Token has been expired"})})
    with pytest.raises(ConnectError, match="Connect it again"):
        accounts.token(ADDRESS, "mail", policy=allowed("mail.read"), audit=None, actor="t")
    assert "Connect it again" in accounts.account(ADDRESS).needs_sign_in


def test_a_stale_sign_in_is_renewed_once_and_the_read_goes_through(accounts, vault, fake_google):
    connected(accounts, vault)
    google._ACCESS[ADDRESS] = ("ya29.stale", 10**12)
    answers = iter([Reply(401, {"error": {"message": "Invalid Credentials"}}),
                    Reply(200, {"messages": []})])
    fake = fake_google({("oauth2.googleapis.com", "/token"):
                        Reply(200, {"access_token": "ya29.fresh", "expires_in": 3599}),
                        ("gmail.googleapis.com", "/gmail/v1/users/me/messages"):
                        lambda sent: next(answers)})
    data = accounts.get(ADDRESS, "mail", "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                        policy=allowed("mail.read"), audit=None, actor="t")
    assert data == {"messages": []}
    reads = fake.sent_to("/gmail/v1/users/me/messages")
    assert [r["headers"]["authorization"] for r in reads] == ["Bearer ya29.stale", "Bearer ya29.fresh"]


# -- disconnecting ---------------------------------------------------------------------------------


def test_disconnecting_hands_the_sign_in_back_and_forgets_it(accounts, vault, fake_google):
    connected(accounts, vault)
    fake = fake_google({("oauth2.googleapis.com", "/revoke"): Reply(200, {})})
    assert accounts.disconnect(ADDRESS, policy=allowed("mail.read"), audit=None) == ""
    assert fake.sent_to("/revoke")[0]["form"]["token"] == "1//lasting-sign-in"
    assert not vault.has(refresh_name(ADDRESS)) and accounts.accounts() == []


def test_when_google_cannot_be_told_it_is_still_forgotten_here(accounts, vault, fake_google):
    connected(accounts, vault)
    fake = fake_google({})
    note = accounts.disconnect(ADDRESS, policy=Policy(), audit=None)
    assert "myaccount.google.com" in note and fake.requests == []
    assert not vault.has(refresh_name(ADDRESS)) and accounts.accounts() == []
