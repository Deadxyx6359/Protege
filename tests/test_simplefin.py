"""Bank accounts through SimpleFIN (C5): claimed once, sealed, read only, and money never moves.

A setup token is claimed with one POST to SimpleFIN's own bridge; the access it
gives carries a name and password, which are sealed and sent only in a header.
A refused claim warns that the token may have been taken. What a bank says is
kept in memory for an hour, and not given once the permission has gone.
SimpleFIN is a fake; nothing leaves this computer.
"""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs

import pytest

from akira.core.agents.roles import FINANCES
from akira.core.connect import simplefin
from akira.core.connect.google import ConnectError
from akira.core.connect.simplefin import Bank, BankStore, access_name, bridge_of, claim_address
from akira.core.net import client as net
from akira.core.permissions import AuditLog, Policy, SecretStore, secrets
from akira.core.permissions.capabilities import CATALOGUE, Direction
from akira.core.tools import default_registry
from akira.core.tools.schema import ToolContext

pytestmark = pytest.mark.skipif(not secrets.available(), reason="needs DPAPI")

BRIDGE = "beta-bridge.simplefin.org"
CLAIM = f"https://{BRIDGE}/simplefin/claim/demo-claim-123"
SETUP = base64.b64encode(CLAIM.encode()).decode()
ACCESS = f"https://user9:s3cret-pass@{BRIDGE}/simplefin"
NOW = 1_790_000_000.0

LOOK = {
    "errlist": [{"code": "con.auth", "msg": "Chase needs you to sign in again at SimpleFIN."}],
    "connections": [{"conn_id": "c1", "name": "Chase", "org_id": "chase"}],
    "accounts": [
        {"id": "a1", "name": "Checking", "conn_id": "c1", "currency": "USD", "balance": "1234.56",
         "available-balance": "1200.00", "balance-date": NOW - 3600,
         "transactions": [
             {"id": "t1", "posted": NOW - 86_400, "amount": "-45.00", "description": "COFFEE CO"},
             {"id": "t2", "posted": NOW - 3 * 86_400, "amount": "2000.00",
              "description": "PAYROLL"}]},
        {"id": "a2", "name": "Savings", "conn_id": "c1", "currency": "USD", "balance": "5000.00",
         "balance-date": NOW - 3600,
         "transactions": [{"id": "t3", "posted": NOW - 2 * 86_400, "amount": "100.00",
                           "description": "TRANSFER IN", "pending": True}]},
    ],
}


class Reply:
    def __init__(self, body, status=200, kind="application/json"):
        self.status, self.reason = status, "OK" if status < 400 else "Forbidden"
        self._kind = kind
        self._body = body.encode() if isinstance(body, str) else json.dumps(body).encode()

    def getheader(self, name, default=None):
        return self._kind if name.lower() == "content-type" else default

    def read(self, size):
        piece, self._body = self._body[:size], self._body[size:]
        return piece


@pytest.fixture
def wire(monkeypatch):
    sent = []

    def install(answers):
        def open_(host, address, port, timeout):
            class Connection:
                def connect(self):
                    pass

                def request(self, method, path, body=None, headers=None):
                    where, _, query = path.partition("?")
                    sent.append({"host": host, "method": method, "path": path, "where": where,
                                 "query": parse_qs(query),
                                 "headers": {k.lower(): v for k, v in (headers or {}).items()}})
                    answer = answers[(method, where)]
                    self._reply = answer if isinstance(answer, Reply) else Reply(answer)

                def getresponse(self):
                    return self._reply

                def close(self):
                    pass

            return Connection()

        monkeypatch.setattr(net, "_resolve", lambda host, port: ["104.21.1.1"])
        monkeypatch.setattr(net, "_open", open_)
        return sent
    return install


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))
    simplefin._KEPT.clear()
    vault = SecretStore(tmp_path / "secrets")
    yield vault, Bank(vault=vault, store=BankStore())
    simplefin._KEPT.clear()


def allowed(*capabilities) -> Policy:
    policy = Policy()
    for capability in capabilities:
        policy.grant(capability, (BRIDGE,))
    return policy


def connected(vault):
    vault.put(access_name(BRIDGE), ACCESS)
    BankStore().save(simplefin.BankConnection(BRIDGE, 1.0))


def context(vault, tmp_path, *capabilities):
    return ToolContext(policy=allowed(*capabilities), audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=vault, actor="finances")


# -- the setup token --------------------------------------------------------------------------------


def test_a_setup_token_holds_a_claim_address_on_simplefins_own_bridge():
    assert claim_address(f"  {SETUP}\n") == CLAIM and bridge_of(SETUP) == BRIDGE


@pytest.mark.parametrize("token, reason", [
    (base64.b64encode(b"https://bridge.simplefin.example/simplefin/claim/x").decode(),
     "own bridge"),
    (base64.b64encode(f"http://{BRIDGE}/simplefin/claim/x".encode()).decode(), "own bridge"),
    (base64.b64encode(f"https://{BRIDGE}/simplefin/accounts".encode()).decode(), "own bridge"),
    ("", "Paste the setup token"),
    ("%%%not base64%%%", "not a SimpleFIN setup token"),
])
def test_a_token_that_is_not_simplefins_is_refused(token, reason):
    with pytest.raises(ConnectError, match=reason):
        claim_address(token)
    assert bridge_of(token) == ""


# -- claiming -------------------------------------------------------------------------------------


def test_claiming_is_one_post_and_the_access_is_sealed_never_written_down(home, wire, tmp_path):
    vault, bank = home
    sent = wire({("POST", "/simplefin/claim/demo-claim-123"): Reply(ACCESS, kind="text/plain")})
    audit = AuditLog(tmp_path / "audit.jsonl")
    connection = bank.connect(SETUP, policy=allowed("bank.read"), audit=audit)
    assert connection.bridge == BRIDGE
    [request] = sent
    assert (request["host"], request["method"]) == (BRIDGE, "POST")
    assert vault.get(access_name(BRIDGE)) == ACCESS and BRIDGE not in access_name(BRIDGE)
    kept = (tmp_path / "cfg" / "bank.json").read_text(encoding="utf-8")
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    for place in (kept, log):
        assert "s3cret-pass" not in place and "demo-claim-123" not in place


def test_a_refused_claim_warns_that_the_token_may_have_been_taken(home, wire):
    vault, bank = home
    wire({("POST", "/simplefin/claim/demo-claim-123"): Reply("Forbidden", 403, "text/plain")})
    with pytest.raises(ConnectError, match="someone else may have"):
        bank.connect(SETUP, policy=allowed("bank.read"), audit=None)
    assert not vault.has(access_name(BRIDGE)) and bank.connections() == []


def test_connecting_needs_bank_read_and_sends_nothing_without_it(home, wire):
    vault, bank = home
    sent = wire({("POST", "/simplefin/claim/demo-claim-123"): Reply(ACCESS, kind="text/plain")})
    with pytest.raises(ConnectError, match="Not permitted"):
        bank.connect(SETUP, policy=allowed("mail.read"), audit=None)
    assert sent == [] and not vault.has(access_name(BRIDGE))


def test_access_anywhere_but_the_bridge_is_not_kept(home, wire):
    vault, bank = home
    wire({("POST", "/simplefin/claim/demo-claim-123"):
          Reply("https://user9:s3cret-pass@collector.example/simplefin", kind="text/plain")})
    with pytest.raises(ConnectError, match="somewhere other than its own bridge"):
        bank.connect(SETUP, policy=allowed("bank.read"), audit=None)
    assert not vault.has(access_name(BRIDGE))


# -- reading --------------------------------------------------------------------------------------


def test_balances_are_read_with_the_sign_in_in_a_header_never_the_address(home, wire, tmp_path):
    vault, _ = home
    connected(vault)
    sent = wire({("GET", "/simplefin/accounts"): LOOK})
    result = default_registry().invoke("list_bank_accounts", {},
                                       context(vault, tmp_path, "bank.read"))
    assert result.ok, result.content
    assert "Chase Checking: 1234.56 USD, 1200.00 available" in result.content
    assert "Chase Savings: 5000.00 USD" in result.content
    assert "Nothing here can move money" in result.content
    assert "Chase needs you to sign in again at SimpleFIN." in result.content
    [request] = sent
    assert "s3cret" not in request["path"] and "user9" not in request["path"]
    expected = base64.b64encode(b"user9:s3cret-pass").decode()
    assert request["headers"]["authorization"] == f"Basic {expected}"
    assert request["query"]["balances-only"] == ["1"]
    assert "s3cret-pass" not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "s3cret-pass" not in result.content


def test_transactions_come_newest_first_and_can_be_narrowed_to_an_account(home, wire, tmp_path,
                                                                        monkeypatch):
    vault, _ = home
    connected(vault)
    monkeypatch.setattr(simplefin.time, "time", lambda: NOW)
    sent = wire({("GET", "/simplefin/accounts"): LOOK})
    result = default_registry().invoke("list_transactions", {"days": 30},
                                       context(vault, tmp_path, "bank.read"))
    assert result.ok, result.content
    coffee, transfer, payroll = (result.content.index(word)
                                 for word in ("COFFEE CO", "TRANSFER IN", "PAYROLL"))
    assert coffee < transfer < payroll, "transactions were not newest first"
    assert "TRANSFER IN (Chase Savings), pending" in result.content
    assert sent[0]["query"]["start-date"] == [str(int(NOW - 30 * 86_400))]
    narrowed = default_registry().invoke("list_transactions", {"days": 30, "account": "savings"},
                                         context(vault, tmp_path, "bank.read"))
    assert "TRANSFER IN" in narrowed.content and "COFFEE" not in narrowed.content


def test_a_look_is_kept_for_an_hour_and_asked_for_again_after(home, wire):
    vault, bank = home
    connected(vault)
    sent = wire({("GET", "/simplefin/accounts"): LOOK})
    policy = allowed("bank.read")
    first = bank.look(BRIDGE, days=1, balances_only=True, policy=policy, audit=None, actor="t",
                      now=NOW)
    again = bank.look(BRIDGE, days=1, balances_only=True, policy=policy, audit=None, actor="t",
                      now=NOW + 60)
    assert again is first and len(sent) == 1
    bank.look(BRIDGE, days=1, balances_only=True, policy=policy, audit=None, actor="t",
              now=NOW + simplefin.KEEP_S + 1)
    assert len(sent) == 2


def test_a_kept_look_is_not_given_once_the_permission_is_gone(home, wire):
    vault, bank = home
    connected(vault)
    sent = wire({("GET", "/simplefin/accounts"): LOOK})
    bank.look(BRIDGE, days=1, balances_only=True, policy=allowed("bank.read"), audit=None,
              actor="t", now=NOW)
    with pytest.raises(ConnectError, match="Not permitted"):
        bank.look(BRIDGE, days=1, balances_only=True, policy=Policy(), audit=None, actor="t",
                  now=NOW + 60)
    assert len(sent) == 1


def test_access_simplefin_no_longer_accepts_asks_to_connect_again(home, wire, tmp_path):
    vault, _ = home
    connected(vault)
    wire({("GET", "/simplefin/accounts"): Reply("Forbidden", 403, "text/plain")})
    result = default_registry().invoke("list_bank_accounts", {},
                                       context(vault, tmp_path, "bank.read"))
    assert not result.ok and "Connect it again with a new setup token" in result.content


def test_disconnecting_forgets_the_access_and_what_was_kept(home, wire):
    vault, bank = home
    connected(vault)
    wire({("GET", "/simplefin/accounts"): LOOK})
    bank.look(BRIDGE, days=1, balances_only=True, policy=allowed("bank.read"), audit=None,
              actor="t", now=NOW)
    note = bank.disconnect(BRIDGE)
    assert not vault.has(access_name(BRIDGE)) and bank.connections() == []
    assert simplefin._KEPT == {} and "under Apps" in note


# -- who reads it -------------------------------------------------------------------------------------


def test_money_can_never_move():
    assert "bank.read" in CATALOGUE and not any(c.startswith("bank.") and c != "bank.read"
                                                for c in CATALOGUE)
    registry = default_registry()
    for name in FINANCES.tools:
        tool = registry.get(name)
        assert tool is not None and tool.reversible, name
        assert all(CATALOGUE[r.capability].direction is Direction.READ for r in tool.requires)
    assert "not a financial adviser" in FINANCES.role
    assert "nothing in Akira, can move money" in FINANCES.role


# -- the Accounts bridge ----------------------------------------------------------------------------


@pytest.fixture
def bridge(home, tmp_path):
    pytest.importorskip("PySide6.QtCore")
    from PySide6.QtCore import QCoreApplication

    from akira.ui.bridge.accounts import AccountsBridge

    QCoreApplication.instance() or QCoreApplication([])
    vault, bank = home
    holder = {"policy": Policy()}
    made = AccountsBridge(vault=vault, policy=lambda: holder["policy"],
                          audit=AuditLog(tmp_path / "audit.jsonl"), banks=bank)
    return made, holder, vault


def test_the_bridge_never_shows_the_access_and_asks_for_the_permission_first(bridge, wire):
    made, holder, vault = bridge
    sent = wire({("POST", "/simplefin/claim/demo-claim-123"): Reply(ACCESS, kind="text/plain")})
    assert made.bankBridge(SETUP) == BRIDGE and made.bankBridge("nonsense") == ""
    assert made.bankMissing(BRIDGE) == [{"capability": "bank.read",
                                         "title": "Read account balances"}]
    assert made.connectBank(SETUP).startswith("Not permitted") and sent == []
    assert "cannot move money" in made.bankHelp
    connected(vault)
    assert "s3cret" not in json.dumps(made.bankConnections)
    assert made.bankConnections[0]["bridge"] == BRIDGE
