"""A connected Gmail address, as the monitor sees an inbox (C6 over C5).

The monitor asks two things: is this address connected for mail, and what is in
its inbox lately. Both go through the connection's own rules, `mail.read` for
the address and the sign-in added beneath, under the global grants like every
watch. Reading only: nothing is sent, deleted or marked read.
"""

from __future__ import annotations

from collections.abc import Callable

from akira.core.permissions import AuditLog, Policy

from . import gmail
from .google import MAIL, GoogleAccounts

#: What one look reads: the inbox's last week, the longest a watch waits between
#: looks, newest first and at most `gmail.MAX_RESULTS` messages.
QUERY = "in:inbox newer_than:8d"

#: Who the activity log records.
ACTOR = "monitor"


class GmailInbox:
    """The monitor's view of connected Gmail addresses."""

    def __init__(self, accounts: GoogleAccounts, *, policy: Callable[[], Policy],
                 audit: AuditLog | None = None) -> None:
        self._accounts = accounts
        self._policy = policy
        self._audit = audit

    def connected(self, address: str) -> bool:
        account = self._accounts.account(address)
        return account is not None and MAIL.name in account.services

    def recent(self, address: str) -> list[gmail.Mail]:
        """The latest messages in \a address's inbox. Raises `ConnectError` with a reason."""
        return gmail.search(self._accounts, address, QUERY, policy=self._policy(),
                            audit=self._audit, actor=ACTOR)
