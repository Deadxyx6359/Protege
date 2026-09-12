"""The `Accounts` bridge (C5): the client file, connecting on a worker, disconnecting.

Google is a fake and so is the browser, which answers the real listener on
127.0.0.1 the way Google's page would send it back. Nothing leaves this computer.
"""

from __future__ import annotations

import base64
import json
import socket
import threading
import time

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from akira.core.connect import google  # noqa: E402
from akira.core.connect.google import AccountStore, refresh_name  # noqa: E402
from akira.core.net import client as net  # noqa: E402
from akira.core.net import query_value  # noqa: E402
from akira.core.net.loopback import HOST  # noqa: E402
from akira.core.permissions import AuditLog, Policy, SecretStore, secrets  # noqa: E402
from akira.security import netguard  # noqa: E402
from akira.ui.bridge.accounts import AccountsBridge  # noqa: E402

pytestmark = pytest.mark.skipif(not secrets.available(), reason="needs DPAPI")

ADDRESS = "akira.helper@gmail.com"
MAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, predicate, timeout=10.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return predicate()


class Reply:
    def __init__(self, body, status=200):
        self.status, self.reason, self._body = status, "OK", json.dumps(body).encode("utf-8")

    def getheader(self, name, default=None):
        return "application/json" if name.lower() == "content-type" else default

    def read(self, size):
        piece, self._body = self._body[:size], self._body[size:]
        return piece


def claims(email):
    body = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).rstrip(b"=").decode()
    return f"h.{body}.s"


@pytest.fixture
def fake_google(monkeypatch):
    sent = []
    answers = {
        "/token": lambda: Reply({"access_token": "ya29.short", "expires_in": 3599,
                                 "refresh_token": "1//lasting", "id_token": claims(ADDRESS),
                                 "scope": f"openid email {MAIL_SCOPE}"}),
        "/revoke": lambda: Reply({})}

    def open_(host, address, port, timeout):
        class Connection:
            def connect(self):
                pass

            def request(self, method, path, body=None, headers=None):
                sent.append(path)
                self._reply = answers[path.split("?", 1)[0]]()

            def getresponse(self):
                return self._reply

            def close(self):
                pass

        return Connection()

    monkeypatch.setattr(net, "_resolve", lambda host, port: ["142.250.180.10"])
    monkeypatch.setattr(net, "_open", open_)
    return sent


def sent_back(url, code="4/0-code"):
    """The person agrees on Google's page, and their browser is sent back here."""
    port = int(query_value(url, "redirect_uri").rsplit(":", 1)[1].strip("/"))

    def go():
        sock = socket.socket()
        sock.settimeout(5)
        with netguard.admitting(addresses=((HOST, port),)):
            sock.connect((HOST, port))
        target = f"/?state={query_value(url, 'state')}&code={code.replace('/', '%2F')}"
        sock.sendall(f"GET {target} HTTP/1.1\r\nHost: {HOST}\r\n\r\n".encode())
        while sock.recv(4096):
            pass
        sock.close()

    threading.Thread(target=go, daemon=True).start()


@pytest.fixture
def made(app, tmp_path):
    google._ACCESS.clear()
    policy = Policy()
    opened = []

    def build(answer=True):
        def open_page(url):
            opened.append(url)
            if answer:
                sent_back(url)

        return AccountsBridge(vault=SecretStore(tmp_path / "secrets"), policy=lambda: policy,
                              audit=AuditLog(tmp_path / "audit.jsonl"),
                              store=AccountStore(tmp_path / "accounts.json"), open_page=open_page)

    yield build, policy, opened, tmp_path
    google._ACCESS.clear()


def client_file(tmp_path, kind="installed"):
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps({kind: {"client_id": "1-a.apps.googleusercontent.com",
                                       "client_secret": "GOCSPX-shh",
                                       "token_uri": "https://oauth2.googleapis.com/token"}}),
                    encoding="utf-8")
    return str(path)


def test_the_client_file_is_chosen_and_sealed(made):
    build, _, _, tmp_path = made
    bridge = build()
    assert not bridge.clientReady
    assert "web application" in bridge.chooseClientFile(client_file(tmp_path, kind="web"))
    assert bridge.chooseClientFile(client_file(tmp_path)) == "" and bridge.clientReady


def test_nothing_starts_before_the_address_is_allowed(made, fake_google):
    build, policy, opened, tmp_path = made
    bridge = build()
    bridge.chooseClientFile(client_file(tmp_path))
    assert bridge.missing(ADDRESS, ["mail", "calendar"]) == [
        {"capability": "mail.read", "title": "Gmail"},
        {"capability": "calendar.read", "title": "Google Calendar"}]
    assert "Not permitted" in bridge.connectAccount(ADDRESS, ["mail"])
    assert "not an email address" in bridge.connectAccount("akira", ["mail"])
    assert not bridge.busy and opened == [] and fake_google == []


def test_connecting_runs_on_a_worker_and_says_how_it_ended(app, made, fake_google):
    build, policy, opened, tmp_path = made
    bridge = build()
    bridge.chooseClientFile(client_file(tmp_path))
    policy.grant("mail.read", (ADDRESS,))
    endings = []
    bridge.finished.connect(lambda ok, message: endings.append((ok, message)))

    assert bridge.connectAccount("Akira.Helper@gmail.com", ["mail"]) == ""
    assert bridge.busy and bridge.connecting == ADDRESS
    assert pump_until(app, lambda: bool(endings)), "the sign-in never came back"
    assert endings == [(True, f"Connected {ADDRESS} for Gmail.")]
    assert not bridge.busy
    assert bridge.accounts == [{"address": ADDRESS, "services": ["mail"], "titles": ["Gmail"],
                                "connected": bridge.accounts[0]["connected"], "needsSignIn": ""}]
    assert opened[0].startswith("https://accounts.google.com/")


def test_one_sign_in_at_a_time_and_it_can_be_stopped(app, made, fake_google):
    build, policy, _, tmp_path = made
    bridge = build(answer=False)
    bridge.chooseClientFile(client_file(tmp_path))
    policy.grant("mail.read", (ADDRESS,))
    endings = []
    bridge.finished.connect(lambda ok, message: endings.append((ok, message)))
    assert bridge.connectAccount(ADDRESS, ["mail"]) == ""
    assert "Already signing in" in bridge.connectAccount(ADDRESS, ["mail"])
    bridge.cancel()
    assert pump_until(app, lambda: bool(endings))
    assert endings[0][0] is False and "stopped" in endings[0][1]
    assert bridge.accounts == [] and fake_google == []


def test_disconnecting_hands_it_back_and_forgets_it(made, fake_google):
    build, policy, _, tmp_path = made
    bridge = build()
    bridge.chooseClientFile(client_file(tmp_path))
    policy.grant("mail.read", (ADDRESS,))
    SecretStore(tmp_path / "secrets").put(refresh_name(ADDRESS), "1//lasting")
    AccountStore(tmp_path / "accounts.json").save(google.Account(ADDRESS, ("mail",), 1.0))
    assert bridge.disconnectAccount(ADDRESS) == ""
    assert fake_google == ["/revoke"] and bridge.accounts == []


def test_nothing_secret_crosses_to_the_view(made):
    build, _, _, tmp_path = made
    bridge = build()
    AccountStore(tmp_path / "accounts.json").save(google.Account(ADDRESS, ("mail",), 1.0))
    [row] = bridge.accounts
    assert set(row) == {"address", "services", "titles", "connected", "needsSignIn"}
