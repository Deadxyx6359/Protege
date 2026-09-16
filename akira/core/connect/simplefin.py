"""Bank accounts, read through SimpleFIN (C5). Balances and transactions; money never moves.

The person chose SimpleFIN: a service that connects to their banks and hands
out read-only access. There is no request in its protocol that moves money, and
none in Akira either — `bank.read` has no `bank.write` beside it, anywhere.

Connecting follows the protocol. The person makes a setup token in SimpleFIN
Bridge and gives it to Akira. The token is a claim address, written in base64;
Akira claims it once, with a POST, and SimpleFIN answers with an access address
that carries a name and password. That address is sealed with DPAPI
(`bank.<hash>.access`) and never shown to a model; `bank.json` keeps only which
bridge it is and when it was connected. A setup token can be claimed only once,
so when a claim is refused the person is told plainly that someone else may have
claimed it, as the protocol asks.

Reading holds to:
- **SimpleFIN's own bridges only.** A token whose claim address is anywhere else
  is refused before anything is sent, so a token made to look like SimpleFIN's
  cannot send the claim somewhere of its choosing.
- **`bank.read` for the bridge**, checked before anything is sent.
- **The name and password in a header**, never in the address, and never
  written to the activity log.
- **An hour's memory.** SimpleFIN refreshes a bank once a day and limits how
  often it is asked, so what one look returns is kept in memory for an hour and
  given again. Nothing from a bank is written to disk.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from akira.core import files
from akira.core.config import config_dir
from akira.core.net import NetError, call, host_of, split_sign_in, with_query
from akira.core.permissions import AuditLog, SecretStore
from akira.core.permissions.secrets import SecretError
from akira.core.review import declare_secret_owner

from .google import ConnectError

#: What reading a bank needs, for the bridge.
CAPABILITY = "bank.read"

#: Who connects and disconnects: always the person, never an agent.
ACTOR = "person"

#: SimpleFIN's own bridges. A claim or an access address anywhere else is refused.
BRIDGES = frozenset({"bridge.simplefin.org", "beta-bridge.simplefin.org"})

#: How long one look at a bank is given again, rather than asked for again.
KEEP_S = 60 * 60

#: The longest look back for transactions. SimpleFIN keeps about ninety days.
MAX_DAYS = 90

#: The most transactions one look returns.
MAX_TRANSACTIONS = 200

#: For the person: where a setup token comes from.
TOKEN_HELP = ("In SimpleFIN Bridge, connect your banks, then make a new setup token for Akira "
              "and paste it here. SimpleFIN can read balances and transactions and cannot move "
              "money, and neither can Akira.")

#: For the person: what a refused claim may mean.
CLAIM_REFUSED = ("SimpleFIN refused that setup token: it has already been claimed, or it is not "
                 "valid. If you did not use it yourself, someone else may have. Make a new one "
                 "in SimpleFIN Bridge, and check its list of apps for any you do not recognise.")

declare_secret_owner("bank.", "Bank accounts (SimpleFIN)")


@dataclass(frozen=True)
class BankConnection:
    bridge: str
    connected: float = 0.0


@dataclass(frozen=True)
class BankAccount:
    id: str
    name: str
    bank: str
    currency: str
    balance: str
    available: str
    as_of: float


@dataclass(frozen=True)
class Transaction:
    id: str
    account: str
    """The account's name, with its bank's."""
    posted: float
    amount: str
    description: str
    pending: bool


@dataclass(frozen=True)
class Look:
    accounts: tuple[BankAccount, ...]
    transactions: tuple[Transaction, ...]
    problems: tuple[str, ...]
    """What SimpleFIN said went wrong with a bank, such as needing to sign in again there."""
    fetched: float


def access_name(bridge: str) -> str:
    """Where a bridge's access is sealed. The bridge itself is not in the name."""
    return f"bank.{hashlib.sha256(bridge.encode('utf-8')).hexdigest()[:16]}.access"


def claim_address(setup_token: str) -> str:
    """The claim address a setup token holds. Raises `ConnectError` if it holds none."""
    text = "".join(str(setup_token).split())
    if not text:
        raise ConnectError(f"Paste the setup token. {TOKEN_HELP}")
    try:
        decoded = base64.b64decode(text + "=" * (-len(text) % 4), validate=False).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ConnectError("That is not a SimpleFIN setup token.") from None
    bridge = host_of(decoded)
    if bridge not in BRIDGES or "/claim/" not in decoded:
        raise ConnectError("That token does not point to SimpleFIN's own bridge, so nothing was "
                           "sent. Make a setup token in SimpleFIN Bridge itself.")
    return decoded.strip()


def bridge_of(setup_token: str) -> str:
    """The bridge a setup token belongs to, or "" when it is not one."""
    try:
        return host_of(claim_address(setup_token))
    except ConnectError:
        return ""


class BankStore:
    """Which bridges are connected. Holds nothing secret."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_dir() / "bank.json"
        self._lock = threading.Lock()

    def all(self) -> list[BankConnection]:
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return []
        return [BankConnection(str(entry["bridge"]), float(entry.get("connected", 0.0)))
                for entry in (raw.get("bank", []) if isinstance(raw, dict) else [])
                if isinstance(entry, dict) and entry.get("bridge") in BRIDGES]

    def _write(self, connections: list[BankConnection]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".bank-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"bank": [asdict(c) for c in connections]}, stream, indent=1)
            files.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def save(self, connection: BankConnection) -> None:
        kept = [c for c in self.all() if c.bridge != connection.bridge]
        with self._lock:
            self._write(kept + [connection])

    def remove(self, bridge: str) -> None:
        kept = [c for c in self.all() if c.bridge != bridge]
        with self._lock:
            self._write(kept)

    def only(self) -> str:
        having = self.all()
        return having[0].bridge if len(having) == 1 else ""


#: What was last read, by bridge and what was asked. In memory only.
_KEPT: dict[tuple, Look] = {}
_KEPT_LOCK = threading.Lock()


def _forget_kept(bridge: str) -> None:
    with _KEPT_LOCK:
        for key in [k for k in _KEPT if k[0] == bridge]:
            del _KEPT[key]


class Bank:
    """Connected SimpleFIN bridges: connecting one, reading it, and forgetting it."""

    def __init__(self, *, vault: SecretStore, store: BankStore | None = None) -> None:
        self._vault = vault
        self._store = store if store is not None else BankStore()

    def connections(self) -> list[BankConnection]:
        return self._store.all()

    def only(self) -> str:
        return self._store.only()

    def connect(self, setup_token: str, *, policy, audit: AuditLog | None,
                actor: str = ACTOR) -> BankConnection:
        """Claim \a setup_token, once, and seal the access SimpleFIN gives for it."""
        claim = claim_address(setup_token)
        bridge = host_of(claim)
        try:
            # The claim link is itself the secret, so the log keeps only the site.
            response = call("POST", claim, policy=policy, capability=CAPABILITY, scope=bridge,
                            hosts=(bridge,), audit=audit, actor=actor, form={}, accept="*/*",
                            max_bytes=4096, secret_path=True)
        except NetError as exc:
            raise ConnectError(str(exc)) from None
        if response.status == 403:
            raise ConnectError(CLAIM_REFUSED)
        if not response.ok:
            raise ConnectError(f"SimpleFIN answered {response.status} {response.reason}, so "
                               "nothing was connected.")
        access = response.text().strip()
        try:
            where, _, _ = split_sign_in(access)
        except NetError:
            raise ConnectError("SimpleFIN did not answer with access, so nothing was "
                               "connected.") from None
        if host_of(where) != bridge:
            raise ConnectError("SimpleFIN gave access somewhere other than its own bridge, so "
                               "it was not kept.")
        self._vault.put(access_name(bridge), access)
        connection = BankConnection(bridge, time.time())
        self._store.save(connection)
        _forget_kept(bridge)
        return connection

    def disconnect(self, bridge: str) -> str:
        """Forget a bridge's access here. Returns what the person should also do there."""
        try:
            self._vault.delete(access_name(bridge))
        except SecretError:
            pass
        self._store.remove(bridge)
        _forget_kept(bridge)
        return ("Akira has forgotten its access to your banks. Remove Akira in SimpleFIN Bridge "
                "as well, under Apps, so the access stops working everywhere.")

    def look(self, bridge: str, *, days: int, balances_only: bool, policy,
             audit: AuditLog | None, actor: str, now: float | None = None) -> Look:
        """Balances, and transactions for the last \a days unless \a balances_only.

        Given again from memory for an hour. Raises `ConnectError`.
        """
        if bridge not in {c.bridge for c in self._store.all()}:
            raise ConnectError("No bank is connected. The person connects SimpleFIN in "
                               "Settings, Accounts.")
        decision = policy.allows(CAPABILITY, bridge)
        if not decision:
            # Checked here as well as by `call`, so a look kept in memory is not
            # handed back once the permission has gone.
            raise ConnectError(f"Not permitted: {decision.reason}.")
        days = max(1, min(int(days), MAX_DAYS))
        moment = time.time() if now is None else now
        key = (bridge, days, balances_only)
        with _KEPT_LOCK:
            kept = _KEPT.get(key)
        if kept is not None and moment - kept.fetched < KEEP_S:
            return kept
        try:
            access = self._vault.get(access_name(bridge))
            where, name, password = split_sign_in(access)
        except (SecretError, NetError):
            raise ConnectError("The access to SimpleFIN could not be read. Connect it again "
                               "with a new setup token.") from None
        asked = {"version": "2"}
        if balances_only:
            asked["balances-only"] = "1"
        else:
            asked.update({"start-date": str(int(moment - days * 86_400)), "pending": "1"})
        try:
            response = call("GET", with_query(f"{where}/accounts", asked), policy=policy,
                            capability=CAPABILITY, scope=bridge, hosts=(bridge,), audit=audit,
                            actor=actor, basic=lambda: (name, password))
        except NetError as exc:
            raise ConnectError(str(exc)) from None
        if response.status in (401, 402, 403):
            raise ConnectError("SimpleFIN no longer accepts Akira's access: it may have been "
                               "removed, or the subscription has lapsed. Connect it again with "
                               "a new setup token.")
        if not response.ok:
            raise ConnectError(f"SimpleFIN answered {response.status} {response.reason}.")
        try:
            data = json.loads(response.text() or "{}")
        except ValueError:
            raise ConnectError("SimpleFIN answered with something that could not be read.") from None
        found = _read(data if isinstance(data, dict) else {}, moment)
        with _KEPT_LOCK:
            _KEPT[key] = found
        return found


def _plain(value, limit: int = 300) -> str:
    return " ".join(str(value if value is not None else "").split())[:limit]


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _read(data: dict, fetched: float) -> Look:
    banks = {str(c.get("conn_id")): _plain(c.get("name"), 120)
             for c in data.get("connections") or [] if isinstance(c, dict)}
    accounts, transactions = [], []
    for item in data.get("accounts") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        org = item.get("org") if isinstance(item.get("org"), dict) else {}
        bank = banks.get(str(item.get("conn_id")), "") or _plain(org.get("name"), 120)
        account = BankAccount(_plain(item["id"], 120), _plain(item.get("name"), 120) or "Account",
                              bank, _plain(item.get("currency"), 12),
                              _plain(item.get("balance"), 32),
                              _plain(item.get("available-balance"), 32),
                              _number(item.get("balance-date")))
        accounts.append(account)
        label = f"{account.bank} {account.name}".strip()
        for entry in item.get("transactions") or []:
            if isinstance(entry, dict) and entry.get("id"):
                transactions.append(Transaction(
                    _plain(entry["id"], 120), label,
                    _number(entry.get("transacted_at") or entry.get("posted")),
                    _plain(entry.get("amount"), 32), _plain(entry.get("description")),
                    bool(entry.get("pending"))))
    said = data.get("errlist") if isinstance(data.get("errlist"), list) else data.get("errors")
    problems = [_plain(e.get("msg") if isinstance(e, dict) else e) for e in said or []]
    transactions.sort(key=lambda t: t.posted, reverse=True)
    return Look(tuple(accounts), tuple(transactions[:MAX_TRANSACTIONS]),
                tuple(p for p in problems if p), fetched)
