"""Google accounts: signing in, and the sign-in kept sealed (C5).

The person makes a Google Cloud OAuth client of the Desktop app kind, downloads
its file, and chooses it in Akira. The client's id and secret are sealed with
DPAPI (`google.client`) and never shown to a model. Connecting an address then:

1. Needs the permission for what is connected first: `mail.read` or
   `calendar.read` for that address, granted by the person. Nothing reaches
   Google for an address nobody allowed.
2. Opens the person's own browser at Google's page, with PKCE (a one-time
   secret whose hash goes to Google, so a code taken on its way back is useless
   to anyone else) and a random `state`, and asks Google to send the browser
   back to `loopback.Receiver` on this computer.
3. Exchanges the code, through `client.call`, for a lasting sign-in (Google's
   refresh token), sealed with DPAPI under a name that does not contain the
   address, and a short-lived one kept only in memory.
4. Checks the person signed in as the address they named. Signing in as
   someone else connects nothing: the sign-in is handed back and forgotten.

Google is asked only for what the person chose: reading (`gmail.readonly`,
`calendar.readonly`, `drive.readonly`), and sending (`gmail.send`) or changing
their own events (`calendar.events.owned`) only when they switch it on, each
needing its own permission for the address first. Google's page says exactly
what is asked. Connecting again for more keeps what was granted before.
Disconnecting hands the sign-in back to Google and forgets it here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from secrets import token_urlsafe

from akira.core.config import config_dir
from akira.core.net import MAX_BYTES, NetError, Response, call, with_query
from akira.core.net.client import JSON
from akira.core.net.loopback import WAIT_S, LoopbackError, Receiver
from akira.core.permissions import AuditLog, SecretStore
from akira.core.permissions.secrets import SecretError
from akira.core.review import declare_secret_owner
from akira.core import files

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
TOKEN_HOSTS = ("oauth2.googleapis.com",)

#: Asked for with every sign-in, so Google says which address signed in.
IDENTITY = ("openid", "email")

#: Where the person removes Akira's access from the Google side.
CONNECTIONS_PAGE = "https://myaccount.google.com/connections"

#: The sealed client file.
CLIENT_SECRET = "google.client"

#: Who signs in and out: always the person, never an agent.
ACTOR = "person"

#: A short-lived sign-in is renewed this long before Google would refuse it.
EARLY_S = 60

declare_secret_owner("google.", "Google accounts")

_ADDRESS = re.compile(r"\A[^@\s]+@[^@\s]+\.[^@\s]+\Z")


class ConnectError(RuntimeError):
    """Something about a connected account, with a reason for the person."""


@dataclass(frozen=True)
class Service:
    name: str
    title: str
    capability: str
    scope: str
    """What Google is asked for."""
    hosts: tuple[str, ...]
    """Where its requests go, and nowhere else."""
    detail: str = ""
    """What it does and does not do, in a sentence or two, for the person choosing."""


MAIL = Service("mail", "Gmail", "mail.read",
               "https://www.googleapis.com/auth/gmail.readonly", ("gmail.googleapis.com",),
               "Search and read messages. Nothing is deleted or marked read.")
CALENDAR = Service("calendar", "Google Calendar", "calendar.read",
                   "https://www.googleapis.com/auth/calendar.readonly", ("www.googleapis.com",),
                   "See events. Nothing is added, moved or cancelled.")
#: Sending only: `gmail.send` cannot read, change or delete anything.
SEND = Service("send", "Sending from Gmail", "mail.send",
               "https://www.googleapis.com/auth/gmail.send", ("gmail.googleapis.com",),
               "Send a message when you ask. Each one is shown to you whole, and goes only "
               "if you approve it.")
#: Changing events on calendars the person owns, and nothing else: not a calendar
#: shared with them, not who a calendar is shared with, not its settings.
#: `calendar.events.owned` is narrower than `calendar.events`, which reaches every
#: calendar the person can edit.
EVENTS = Service("events", "Changing Google Calendar events", "calendar.write",
                 "https://www.googleapis.com/auth/calendar.events.owned", ("www.googleapis.com",),
                 "Add, move and cancel events on your own calendar when you ask. Each change is "
                 "shown to you and happens only if you approve it, and nobody is invited or "
                 "told.")
#: Reading Drive: `drive.readonly` can open and list files, and cannot change,
#: move, share or delete any of them. Google's narrower scopes read only files
#: Akira itself made or was handed one at a time, which would read nothing the
#: person already has.
DRIVE = Service("drive", "Google Drive", "cloud.read",
                "https://www.googleapis.com/auth/drive.readonly", ("www.googleapis.com",),
                "Search and read your files. Nothing is changed, moved, shared or deleted.")
SERVICES = {service.name: service for service in (MAIL, CALENDAR, SEND, EVENTS, DRIVE)}


def address_of(text: str) -> str:
    """\a text as an address, in lower case. Raises `ConnectError` if it is not one."""
    address = str(text).strip().lower()
    if not _ADDRESS.match(address):
        raise ConnectError(f"{text!r} is not an email address.")
    return address


def refresh_name(address: str) -> str:
    """Where an address's lasting sign-in is sealed. The address itself is not in it."""
    digest = hashlib.sha256(address.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"google.{digest}.refresh"


# -- the client file ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Client:
    client_id: str
    client_secret: str


_NOT_A_CLIENT = ("This is not a Google client file. In Google Cloud, under Credentials, make an "
                 "OAuth client ID of the Desktop app kind and download its file.")


def read_client_file(path: str | Path) -> Client:
    """The client in a file downloaded from Google Cloud. Raises `ConnectError` if it is not one."""
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConnectError(f"{source.name} could not be read: {exc}") from None
    if not isinstance(raw, dict):
        raise ConnectError(_NOT_A_CLIENT)
    if "installed" not in raw and "web" in raw:
        raise ConnectError("This client is for a web application. Akira needs one of the "
                           "Desktop app kind: make one in Google Cloud and choose its file.")
    installed = raw.get("installed")
    if not isinstance(installed, dict):
        raise ConnectError(_NOT_A_CLIENT)
    client_id = str(installed.get("client_id") or "").strip()
    secret = str(installed.get("client_secret") or "").strip()
    if not client_id.endswith(".apps.googleusercontent.com") or not secret:
        raise ConnectError(_NOT_A_CLIENT)
    token_uri = str(installed.get("token_uri") or TOKEN_URL)
    if token_uri != TOKEN_URL:
        raise ConnectError(f"This file sends sign-ins to {token_uri}, not to Google, so it is "
                           "not used.")
    return Client(client_id, secret)


# -- which addresses are connected -------------------------------------------------------------


@dataclass(frozen=True)
class Account:
    address: str
    services: tuple[str, ...]
    connected: float = 0.0
    needs_sign_in: str = ""
    """Why the sign-in stopped working, for the person, or ""."""


class AccountStore:
    """Which Google addresses are connected, and for what. Holds nothing secret."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_dir() / "accounts.json"
        self._lock = threading.Lock()

    def all(self) -> list[Account]:
        with self._lock:
            return self._read()

    def _read(self) -> list[Account]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            return []
        found = []
        for entry in raw.get("google", []) if isinstance(raw, dict) else []:
            if isinstance(entry, dict) and entry.get("address"):
                found.append(Account(str(entry["address"]),
                                     tuple(s for s in entry.get("services", []) if s in SERVICES),
                                     float(entry.get("connected", 0.0)),
                                     str(entry.get("needs_sign_in", ""))))
        return found

    def _write(self, accounts: list[Account]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"google": [dict(asdict(a), services=list(a.services)) for a in accounts]}
        handle, temporary = tempfile.mkstemp(prefix=".accounts-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=1)
            files.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def get(self, address: str) -> Account | None:
        key = address.strip().lower()
        return next((a for a in self.all() if a.address == key), None)

    def save(self, account: Account) -> None:
        with self._lock:
            kept = [a for a in self._read() if a.address != account.address]
            self._write(kept + [account])

    def remove(self, address: str) -> bool:
        key = address.strip().lower()
        with self._lock:
            accounts = self._read()
            kept = [a for a in accounts if a.address != key]
            if len(kept) == len(accounts):
                return False
            self._write(kept)
            return True

    def default(self, service: str) -> str:
        """The one connected address for \a service, or "" when there is none or a choice."""
        having = [a.address for a in self.all() if service in a.services]
        return having[0] if len(having) == 1 else ""

    def only(self) -> str:
        """The one connected address, whatever it is connected for, or "".

        For naming an address in a refusal: "not connected for Google Drive"
        says what to do, where a permission for no address at all does not.
        """
        having = self.all()
        return having[0].address if len(having) == 1 else ""


# -- signing in ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pending:
    """A sign-in waiting for its answer. Held in memory only."""

    address: str
    services: tuple[str, ...]
    verifier: str
    state: str
    redirect_uri: str
    url: str
    """Google's page, to open in the person's browser."""


def begin(client: Client, address: str, services: tuple[str, ...], redirect_uri: str) -> Pending:
    """A sign-in's page, with its PKCE pair and state."""
    verifier = token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    state = token_urlsafe(24)
    scopes = " ".join([*IDENTITY, *(SERVICES[name].scope for name in services)])
    url = with_query(AUTH_URL, {
        "client_id": client.client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": scopes, "code_challenge": challenge.rstrip(b"=").decode("ascii"),
        "code_challenge_method": "S256", "state": state,
        # A lasting sign-in, so the person is not asked every hour; `consent`
        # so Google gives one even to an address that agreed before.
        "access_type": "offline", "prompt": "consent", "login_hint": address,
        "include_granted_scopes": "true"})
    return Pending(address, services, verifier, state, redirect_uri, url)


def _json(response: Response) -> dict:
    try:
        data = json.loads(response.text() or "{}")
    except ValueError:
        raise ConnectError(f"Google answered {response.status} with something that could not "
                           "be read.") from None
    return data if isinstance(data, dict) else {}


def _refusal(data: dict, response: Response) -> str:
    what = str(data.get("error_description") or data.get("error") or response.reason)
    if isinstance(data.get("error"), dict):
        what = str(data["error"].get("message") or response.reason)
    return f"Google refused ({response.status}): {what}"


def _email_of(id_token: object) -> str:
    """The address an ID token names.

    Its signature is not checked: it came straight from Google's token endpoint,
    over the verified connection the chokepoint makes, which is when Google says
    that check may be skipped.
    """
    try:
        payload = str(id_token).split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, TypeError):
        return ""
    if not isinstance(claims, dict) or claims.get("email_verified") is False:
        return ""
    return str(claims.get("email") or "").strip().lower()


# The short-lived sign-ins, by address, in memory only.
_ACCESS: dict[str, tuple[str, float]] = {}
_ACCESS_LOCK = threading.Lock()


def _forget_access(address: str) -> None:
    with _ACCESS_LOCK:
        _ACCESS.pop(address, None)


class GoogleAccounts:
    """The Google side of Akira: the client, the connected addresses, and their sign-ins."""

    def __init__(self, *, vault: SecretStore, store: AccountStore | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._vault = vault
        self._store = store if store is not None else AccountStore()
        self._clock = clock

    # -- the client ------------------------------------------------------------------------

    def client(self) -> Client | None:
        if not self._vault.has(CLIENT_SECRET):
            return None
        try:
            data = json.loads(self._vault.get(CLIENT_SECRET))
            return Client(str(data["client_id"]), str(data["client_secret"]))
        except (SecretError, ValueError, KeyError, TypeError):
            return None

    def set_client_file(self, path: str | Path) -> None:
        """Seal the client in a downloaded file. Raises `ConnectError` if it is not one."""
        client = read_client_file(path)
        self._vault.put(CLIENT_SECRET, json.dumps(asdict(client)))

    def forget_client(self) -> None:
        self._vault.delete(CLIENT_SECRET)

    # -- the addresses -----------------------------------------------------------------------

    def accounts(self) -> list[Account]:
        return self._store.all()

    def account(self, address: str) -> Account | None:
        return self._store.get(address)

    def default(self, service: str) -> str:
        return self._store.default(service)

    def finish(self, pending: Pending, code: str, *, client: Client, policy,
               audit: AuditLog | None, actor: str = ACTOR) -> Account:
        """Exchange a sign-in's code, check who signed in, and seal what Google gave."""
        service = SERVICES[pending.services[0]]
        form = {"code": code, "client_id": client.client_id, "client_secret": client.client_secret,
                "redirect_uri": pending.redirect_uri, "grant_type": "authorization_code",
                "code_verifier": pending.verifier}
        try:
            response = call("POST", TOKEN_URL, policy=policy, capability=service.capability,
                            scope=pending.address, hosts=TOKEN_HOSTS, audit=audit, actor=actor,
                            form=form)
        except NetError as exc:
            raise ConnectError(str(exc)) from None
        data = _json(response)
        if not response.ok:
            raise ConnectError(_refusal(data, response))
        lasting = str(data.get("refresh_token") or "")
        granted = set(str(data.get("scope") or "").split())
        who = _email_of(data.get("id_token"))
        # Everything the address has granted, not only what this sign-in asked
        # for: connecting again to add sending keeps reading.
        services = tuple(name for name, spec in SERVICES.items() if spec.scope in granted)
        problem = ""
        if who != pending.address:
            problem = (f"You signed in as {who or 'an address Google did not name'}, not "
                       f"{pending.address}, so nothing was connected. Sign in as "
                       f"{pending.address}, or connect the other address instead.")
        elif not set(pending.services) & set(services):
            problem = ("Google was not given permission to read anything, so nothing was "
                       "connected. Tick the boxes on Google's page to allow reading.")
        elif not lasting:
            problem = ("Google did not give a lasting sign-in, so nothing was connected. "
                       f"Remove Akira at {CONNECTIONS_PAGE} and connect again.")
        if problem:
            if lasting:
                self._hand_back(lasting, service, pending.address, policy=policy, audit=audit,
                                actor=actor)
            raise ConnectError(problem)
        self._vault.put(refresh_name(pending.address), lasting)
        access = str(data.get("access_token") or "")
        if access:
            with _ACCESS_LOCK:
                _ACCESS[pending.address] = (access, self._clock() + float(data.get("expires_in") or 0))
        account = Account(pending.address, services, self._clock())
        self._store.save(account)
        return account

    # -- using a sign-in ---------------------------------------------------------------------

    def token(self, address: str, service: str, *, policy, audit: AuditLog | None,
              actor: str) -> str:
        """A short-lived sign-in for \a address, renewed from the sealed one when needed."""
        with _ACCESS_LOCK:
            held = _ACCESS.get(address)
        if held and held[1] - EARLY_S > self._clock():
            return held[0]
        account = self._store.get(address)
        if account is None:
            raise ConnectError(f"{address} is not connected.")
        if account.needs_sign_in:
            raise ConnectError(account.needs_sign_in)
        client = self.client()
        if client is None:
            raise ConnectError("The Google client file has not been chosen, so Akira cannot "
                               "sign in. Choose it where accounts are connected.")
        try:
            lasting = self._vault.get(refresh_name(address))
        except SecretError:
            raise ConnectError(f"The sign-in for {address} is missing. Connect it again.") from None
        capability = SERVICES[service].capability
        try:
            response = call("POST", TOKEN_URL, policy=policy, capability=capability, scope=address,
                            hosts=TOKEN_HOSTS, audit=audit, actor=actor,
                            form={"client_id": client.client_id,
                                  "client_secret": client.client_secret,
                                  "refresh_token": lasting, "grant_type": "refresh_token"})
        except NetError as exc:
            raise ConnectError(str(exc)) from None
        data = _json(response)
        if not response.ok:
            if data.get("error") == "invalid_grant":
                reason = (f"Google no longer accepts Akira's sign-in for {address}: it was "
                          "withdrawn, or it expired. Connect it again.")
                self._store.save(replace(account, needs_sign_in=reason))
                _forget_access(address)
                raise ConnectError(reason)
            raise ConnectError(_refusal(data, response))
        access = str(data.get("access_token") or "")
        if not access:
            raise ConnectError("Google renewed the sign-in without one. Try again.")
        with _ACCESS_LOCK:
            _ACCESS[address] = (access, self._clock() + float(data.get("expires_in") or 0))
        return access

    def get(self, address: str, service: str, url: str, *, policy, audit: AuditLog | None,
            actor: str) -> dict:
        """Read \a url from \a service as \a address. Raises `ConnectError` with a reason."""
        return self._signed("GET", address, service, url, policy=policy, audit=audit,
                            actor=actor)

    def post(self, address: str, service: str, url: str, payload: dict, *, policy,
             audit: AuditLog | None, actor: str) -> dict:
        """Send \a payload to \a url as \a address, at most once. Raises `ConnectError`."""
        return self._signed("POST", address, service, url, payload=payload, policy=policy,
                            audit=audit, actor=actor)

    def patch(self, address: str, service: str, url: str, payload: dict, *, policy,
              audit: AuditLog | None, actor: str) -> dict:
        """Change the fields in \a payload at \a url, as \a address, at most once.

        Raises `ConnectError`.
        """
        return self._signed("PATCH", address, service, url, payload=payload, policy=policy,
                            audit=audit, actor=actor)

    def delete(self, address: str, service: str, url: str, *, policy, audit: AuditLog | None,
               actor: str) -> dict:
        """Remove what \a url names, as \a address, at most once. Raises `ConnectError`."""
        return self._signed("DELETE", address, service, url, policy=policy, audit=audit,
                            actor=actor)

    def download(self, address: str, service: str, url: str, *, policy,
                 audit: AuditLog | None, actor: str, max_bytes: int) -> Response:
        """Read the bytes at \a url from \a service as \a address: a file, not an answer.

        At most \a max_bytes. Raises `ConnectError`.
        """
        return self._answer("GET", address, service, url, policy=policy, audit=audit,
                            actor=actor, accept="*/*", max_bytes=max_bytes)

    def _signed(self, method: str, address: str, service: str, url: str, *,
                payload: dict | None = None, policy, audit: AuditLog | None,
                actor: str) -> dict:
        return _json(self._answer(method, address, service, url, payload=payload, policy=policy,
                                  audit=audit, actor=actor))

    def _answer(self, method: str, address: str, service: str, url: str, *,
                payload: dict | None = None, policy, audit: AuditLog | None, actor: str,
                accept: str = JSON, max_bytes: int = MAX_BYTES) -> Response:
        spec = SERVICES[service]
        account = self._store.get(address)
        if account is not None and service not in account.services:
            # Google would refuse it anyway, but only after a sign-in went to it.
            raise ConnectError(f"{address} is not connected for {spec.title}. Connect it again "
                               "with that switched on, in Settings, Accounts.")

        def signed_in() -> str:
            return self.token(address, service, policy=policy, audit=audit, actor=actor)

        for attempt in (1, 2):
            try:
                response = call(method, url, policy=policy, capability=spec.capability,
                                scope=address, hosts=spec.hosts, audit=audit, actor=actor,
                                bearer=signed_in, payload=payload, accept=accept,
                                max_bytes=max_bytes)
            except NetError as exc:
                raise ConnectError(str(exc)) from None
            if response.status == 401 and attempt == 1:
                # The short-lived sign-in went stale early: renew it once. A request
                # refused for its sign-in did nothing, so asking again cannot do it twice.
                _forget_access(address)
                continue
            if not response.ok:
                try:
                    said = _json(response)
                except ConnectError:
                    said = {}
                raise ConnectError(_refusal(said, response))
            return response
        raise ConnectError(f"Google did not accept the sign-in for {address}. Connect it again.")

    # -- signing out ---------------------------------------------------------------------------

    def _hand_back(self, lasting: str, service: Service, address: str, *, policy,
                   audit: AuditLog | None, actor: str) -> str:
        """Tell Google to forget a sign-in. Returns "" or why it could not be told."""
        try:
            response = call("POST", REVOKE_URL, policy=policy, capability=service.capability,
                            scope=address, hosts=TOKEN_HOSTS, audit=audit, actor=actor,
                            form={"token": lasting})
        except NetError as exc:
            return str(exc)
        return "" if response.ok else f"Google answered {response.status}"

    def disconnect(self, address: str, *, policy, audit: AuditLog | None,
                   actor: str = ACTOR) -> str:
        """Hand the sign-in back to Google and forget it here.

        Returns "" or a note for the person when Google could not be told, in
        which case they can remove Akira from their Google account themselves.
        It is forgotten here either way.
        """
        address = address.strip().lower()
        account = self._store.get(address)
        name = refresh_name(address)
        note = ""
        lasting = ""
        if self._vault.has(name):
            try:
                lasting = self._vault.get(name)
            except SecretError:
                lasting = ""
        if lasting and account is not None:
            usable = [SERVICES[s] for s in account.services
                      if policy.allows(SERVICES[s].capability, address)]
            why = ("Akira is no longer allowed to reach Google for this address" if not usable
                   else self._hand_back(lasting, usable[0], address, policy=policy, audit=audit,
                                        actor=actor))
            if why:
                note = (f"Google could not be told ({why}). The sign-in is forgotten here; to be "
                        f"sure, remove Akira at {CONNECTIONS_PAGE}.")
        self._vault.delete(name)
        self._store.remove(address)
        _forget_access(address)
        if audit is not None:
            audit.tool_call(actor, "disconnect_account", {"address": address}, allowed=True,
                            scope=address, error=note)
        return note


def sign_in(accounts: GoogleAccounts, address: str, services: Iterable[str], *, policy,
            audit: AuditLog | None, open_page: Callable[[str], None],
            receiver: Receiver | None = None, wait_s: float = WAIT_S,
            actor: str = ACTOR) -> Account:
    """Connect \a address for \a services, from permission to sealed sign-in.

    \a open_page shows Google's page in the person's browser. Raises
    `ConnectError` with a reason for the person, having connected nothing.
    """
    address = address_of(address)
    wanted = tuple(dict.fromkeys(name for name in services if name in SERVICES))
    if not wanted:
        raise ConnectError("Choose what to connect: Gmail, Google Calendar, or both.")
    missing = [SERVICES[name] for name in wanted
               if not policy.allows(SERVICES[name].capability, address)]
    if missing:
        needed = " and ".join(f"{s.title} ({s.capability})" for s in missing)
        raise ConnectError(f"Not permitted: allow {needed} for {address} first. Nothing reaches "
                           "Google for an address nobody allowed.")
    client = accounts.client()
    if client is None:
        raise ConnectError("Choose the Google client file first.")
    listener = receiver if receiver is not None else Receiver()
    try:
        pending = begin(client, address, wanted, listener.redirect_uri)
        open_page(pending.url)
        answer = listener.wait(pending.state, wait_s=wait_s)
    except LoopbackError as exc:
        raise ConnectError(str(exc)) from None
    finally:
        listener.close()
    if answer.error:
        raise ConnectError("Google says Akira was not allowed "
                           f"({answer.error}), so nothing was connected.")
    account = accounts.finish(pending, answer.code, client=client, policy=policy, audit=audit,
                              actor=actor)
    if audit is not None:
        audit.tool_call(actor, "connect_account",
                        {"address": account.address, "services": list(account.services)},
                        allowed=True, capability=SERVICES[account.services[0]].capability,
                        scope=account.address)
    return account
