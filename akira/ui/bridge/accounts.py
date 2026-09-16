"""Connected Google addresses — the `Accounts` bridge (C5).

Choosing the Google client file, connecting an address, and disconnecting one.
Connecting runs on a worker: it opens the person's own browser at Google's page
and waits, up to five minutes, for the browser to come back to this computer.
How it ended arrives through `finished`, on a queued signal.

Nothing secret crosses this bridge: not the client's secret, not a sign-in. The
view sees addresses, what each is connected for, and why one needs connecting
again. The slots are `connectAccount` and `disconnectAccount` because `connect`
and `disconnect` already belong to every QObject.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from akira.core.connect import (SERVICES, AccountStore, ConnectError, GoogleAccounts, address_of,
                                sign_in)
from akira.core.connect import canvas as lms
from akira.core.connect import simplefin as bank
from akira.core.connect.canvas import Canvas
from akira.core.connect.simplefin import Bank
from akira.core.net import host_of
from akira.core.net.loopback import Receiver
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.permissions.capabilities import CATALOGUE


def open_in_browser(url: str) -> None:
    """Google's page, in the person's own browser. Windows opens it; Akira fetches nothing."""
    start = getattr(os, "startfile", None)
    if start is None:
        raise ConnectError(f"Open this page in your browser to sign in: {url}")
    start(url)


class AccountsBridge(QObject):
    """The Google client, the connected addresses, and connecting another."""

    accountsChanged = Signal()
    clientChanged = Signal()
    busyChanged = Signal()

    #: ok, message — once per sign-in, however it ended.
    finished = Signal(bool, str)

    #: Private: from the sign-in's worker to this thread.
    _done = Signal(bool, str)

    canvasChanged = Signal()

    #: ok, message — once per Canvas connection, however it ended.
    canvasFinished = Signal(bool, str)

    #: Private: from the Canvas worker to this thread.
    _canvas_done = Signal(bool, str)

    bankChanged = Signal()

    #: ok, message — once per SimpleFIN claim, however it ended.
    bankFinished = Signal(bool, str)

    #: Private: from the claim's worker to this thread.
    _bank_done = Signal(bool, str)

    def __init__(self, *, vault: SecretStore, policy: Callable[[], Policy], audit: AuditLog,
                 store: AccountStore | None = None,
                 open_page: Callable[[str], None] = open_in_browser,
                 canvas: Canvas | None = None,
                 banks: Bank | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._google = GoogleAccounts(vault=vault, store=store)
        self._canvas = canvas if canvas is not None else Canvas(vault=vault)
        self._bank = banks if banks is not None else Bank(vault=vault)
        self._bank_connecting = False
        self._policy = policy
        self._audit = audit
        self._open = open_page
        self._connecting = ""
        self._canvas_connecting = ""
        self._receiver: Receiver | None = None
        self._done.connect(self._on_done)
        self._canvas_done.connect(self._on_canvas_done)
        self._bank_done.connect(self._on_bank_done)

    @property
    def google(self) -> GoogleAccounts:
        return self._google

    # -- the client ------------------------------------------------------------------------

    @Property(bool, notify=clientChanged)
    def clientReady(self) -> bool:
        """Whether a Google client file has been chosen and sealed."""
        return self._google.client() is not None

    @Slot(str, result=str)
    def chooseClientFile(self, path: str) -> str:
        """Seal the client in a file downloaded from Google Cloud. Returns "" or why not."""
        try:
            self._google.set_client_file(path)
        except ConnectError as exc:
            return str(exc)
        self.clientChanged.emit()
        return ""

    # -- the addresses -----------------------------------------------------------------------

    @Property("QVariantList", constant=True)
    def services(self) -> list:
        """What an address can be connected for: `id`, `title`, `capability`, and
        `detail`, what it does and does not do, for the person choosing."""
        return [{"id": s.name, "title": s.title, "capability": s.capability,
                 "detail": s.detail}
                for s in SERVICES.values()]

    @Property("QVariantList", notify=accountsChanged)
    def accounts(self) -> list:
        """Each connected address: `address`, `services` (ids), `titles`, `connected`
        (epoch seconds) and `needsSignIn` (why it must be connected again, or "")."""
        return [{"address": a.address, "services": list(a.services),
                 "titles": [SERVICES[s].title for s in a.services], "connected": a.connected,
                 "needsSignIn": a.needs_sign_in} for a in self._google.accounts()]

    @Slot(str, "QVariantList", result="QVariantList")
    def missing(self, address: str, services: list) -> list:
        """What must be allowed before \a address can be connected for \a services:
        `capability` and `title` for each not yet granted for that address."""
        try:
            who = address_of(address)
        except ConnectError:
            return []
        policy = self._policy()
        return [{"capability": SERVICES[s].capability, "title": SERVICES[s].title}
                for s in services if s in SERVICES
                and not policy.allows(SERVICES[s].capability, who)]

    # -- connecting ------------------------------------------------------------------------------

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return bool(self._connecting)

    @Property(str, notify=busyChanged)
    def connecting(self) -> str:
        """The address being signed in, or ""."""
        return self._connecting

    @Slot(str, "QVariantList", result=str)
    def connectAccount(self, address: str, services: list) -> str:
        """Start signing \a address in for \a services. Returns "" once started, or why not."""
        if self._connecting:
            return f"Already signing in {self._connecting}. Finish or stop that first."
        try:
            who = address_of(address)
        except ConnectError as exc:
            return str(exc)
        wanted = [s for s in services if s in SERVICES]
        if not wanted:
            return "Choose what to connect: Gmail, Google Calendar, or both."
        if self._google.client() is None:
            return "Choose the Google client file first."
        gaps = self.missing(who, wanted)
        if gaps:
            needed = " and ".join(gap["title"] for gap in gaps)
            return f"Not permitted: allow {needed} for {who} first."
        receiver = Receiver()
        self._receiver = receiver
        self._connecting = who
        self.busyChanged.emit()
        threading.Thread(target=self._sign_in, args=(who, wanted, receiver),
                         name="google-sign-in", daemon=True).start()
        return ""

    def _sign_in(self, address: str, services: list, receiver: Receiver) -> None:
        """Worker thread. Emits a signal; touches no Qt property."""
        try:
            account = sign_in(self._google, address, services, policy=self._policy(),
                              audit=self._audit, open_page=self._open, receiver=receiver)
            titles = " and ".join(SERVICES[s].title for s in account.services)
            self._done.emit(True, f"Connected {account.address} for {titles}.")
        except ConnectError as exc:
            self._done.emit(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - a crashed sign-in must still report back
            self._done.emit(False, f"{type(exc).__name__}: {exc}")

    def _on_done(self, ok: bool, message: str) -> None:
        self._connecting = ""
        self._receiver = None
        self.busyChanged.emit()
        self.accountsChanged.emit()
        self.finished.emit(ok, message)

    @Slot()
    def cancel(self) -> None:
        """Stop waiting for the browser. The sign-in ends with `finished(false, ...)`."""
        if self._receiver is not None:
            self._receiver.stop()

    @Slot(str, result=str)
    def disconnectAccount(self, address: str) -> str:
        """Hand the sign-in back to Google and forget it. Returns "" or a note for the person."""
        note = self._google.disconnect(address, policy=self._policy(), audit=self._audit)
        self.accountsChanged.emit()
        return note

    # -- Canvas ------------------------------------------------------------------------------

    @Property(str, constant=True)
    def canvasHelp(self) -> str:
        """How to make a token, and what Akira does with it, for the person."""
        return (f"{lms.TOKEN_HELP} Canvas gives students no token that only reads, so Akira "
                "holds itself to reading: it never submits, posts or changes anything there.")

    @Property("QVariantList", notify=canvasChanged)
    def canvasSites(self) -> list:
        """Each connected Canvas site: `site`, `name` (the person's, as Canvas has it),
        `connected` (epoch seconds). Never the token."""
        return [{"site": a.site, "name": a.name, "connected": a.connected}
                for a in self._canvas.accounts()]

    @Property(str, notify=canvasChanged)
    def canvasConnecting(self) -> str:
        """The site being connected, or ""."""
        return self._canvas_connecting

    @Slot(str, result=str)
    def canvasSite(self, text: str) -> str:
        """\a text as a Canvas site, or "" when it is not one."""
        try:
            return lms.site_of(text)
        except ConnectError:
            return ""

    @Slot(str, result="QVariantList")
    def canvasMissing(self, site: str) -> list:
        """What must be allowed before \a site can be connected: `capability` and `title`."""
        where = self.canvasSite(site)
        if not where or self._policy().allows(lms.CAPABILITY, where):
            return []
        return [{"capability": lms.CAPABILITY, "title": CATALOGUE[lms.CAPABILITY].title}]

    @Slot(str, str, result=str)
    def connectCanvas(self, site: str, token: str) -> str:
        """Check \a token with Canvas and keep it sealed. Returns "" once started, or why not."""
        if self._canvas_connecting:
            return f"Already connecting {self._canvas_connecting}."
        try:
            where = lms.site_of(site)
        except ConnectError as exc:
            return str(exc)
        if not str(token).strip():
            return f"Paste the access token. {lms.TOKEN_HELP}"
        if self.canvasMissing(where):
            return (f"Not permitted: allow {CATALOGUE[lms.CAPABILITY].title} for {where} "
                    "first.")
        self._canvas_connecting = where
        self.canvasChanged.emit()
        threading.Thread(target=self._connect_canvas, args=(where, str(token)),
                         name="canvas-connect", daemon=True).start()
        return ""

    def _connect_canvas(self, site: str, token: str) -> None:
        """Worker thread. Emits a signal; touches no Qt property."""
        try:
            account = self._canvas.connect(site, token, policy=self._policy(), audit=self._audit)
            who = f" as {account.name}" if account.name else ""
            self._canvas_done.emit(True, f"Connected {account.site}{who}. Akira reads it, and "
                                         "never submits or posts anything there.")
        except ConnectError as exc:
            self._canvas_done.emit(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - a crashed connection must still report back
            self._canvas_done.emit(False, f"{type(exc).__name__}: {exc}")

    def _on_canvas_done(self, ok: bool, message: str) -> None:
        self._canvas_connecting = ""
        self.canvasChanged.emit()
        self.canvasFinished.emit(ok, message)

    @Slot(str, result=str)
    def disconnectCanvas(self, site: str) -> str:
        """Forget a site's token. Returns what the person should also do in Canvas."""
        try:
            note = self._canvas.disconnect(site)
        except ConnectError as exc:
            return str(exc)
        self.canvasChanged.emit()
        return note

    # -- banks, through SimpleFIN -----------------------------------------------------------

    @Property(str, constant=True)
    def bankHelp(self) -> str:
        """Where a setup token comes from, and that money never moves."""
        return bank.TOKEN_HELP

    @Property("QVariantList", notify=bankChanged)
    def bankConnections(self) -> list:
        """Each connected bridge: `bridge`, `connected` (epoch seconds). Never the access."""
        return [{"bridge": c.bridge, "connected": c.connected} for c in self._bank.connections()]

    @Property(bool, notify=bankChanged)
    def bankConnecting(self) -> bool:
        return self._bank_connecting

    @Slot(str, result=str)
    def bankBridge(self, setup_token: str) -> str:
        """The SimpleFIN bridge \a setup_token belongs to, or "" when it is not one."""
        return bank.bridge_of(setup_token)

    @Slot(str, result="QVariantList")
    def bankMissing(self, bridge: str) -> list:
        """`capability` and `title` for `bank.read` when it is not granted for \a bridge."""
        if bridge not in bank.BRIDGES or self._policy().allows(bank.CAPABILITY, bridge):
            return []
        return [{"capability": bank.CAPABILITY, "title": CATALOGUE[bank.CAPABILITY].title}]

    @Slot(str, result=str)
    def connectBank(self, setup_token: str) -> str:
        """Claim \a setup_token and seal the access. Returns "" once started, or why not."""
        if self._bank_connecting:
            return "Already connecting."
        try:
            bridge = bank.bridge_of(setup_token) or host_of(bank.claim_address(setup_token))
        except ConnectError as exc:
            return str(exc)
        if self.bankMissing(bridge):
            return f"Not permitted: allow {CATALOGUE[bank.CAPABILITY].title} for {bridge} first."
        self._bank_connecting = True
        self.bankChanged.emit()
        threading.Thread(target=self._connect_bank, args=(str(setup_token),),
                         name="simplefin-claim", daemon=True).start()
        return ""

    def _connect_bank(self, setup_token: str) -> None:
        """Worker thread. Emits a signal; touches no Qt property."""
        try:
            self._bank.connect(setup_token, policy=self._policy(), audit=self._audit)
            self._bank_done.emit(True, "Connected your banks through SimpleFIN. Akira reads "
                                       "balances and transactions, and cannot move money.")
        except ConnectError as exc:
            self._bank_done.emit(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - a crashed claim must still report back
            self._bank_done.emit(False, f"{type(exc).__name__}: {exc}")

    def _on_bank_done(self, ok: bool, message: str) -> None:
        self._bank_connecting = False
        self.bankChanged.emit()
        self.bankFinished.emit(ok, message)

    @Slot(str, result=str)
    def disconnectBank(self, bridge: str) -> str:
        """Forget the access to a bridge. Returns what the person should also do there."""
        note = self._bank.disconnect(bridge)
        self.bankChanged.emit()
        return note
