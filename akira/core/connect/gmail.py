"""Reading Gmail, as a connected address (C5).

Only reading: Google was asked for `gmail.readonly`, and every request is held
to `mail.read` for the address. An email says whatever its sender wanted, so
the tools that show one to a model frame it as material, not instructions.
"""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass

from akira.core.net import with_query
from akira.core.net.page import readable

from .google import ConnectError, GoogleAccounts

API = "https://gmail.googleapis.com/gmail/v1/users/me"

#: The most messages one search looks at. Each is its own request.
MAX_RESULTS = 10

#: The most of one message's text that is kept.
MAX_TEXT_CHARS = 20_000

HEADERS = ("From", "To", "Subject", "Date")

#: What a Gmail message id looks like. Anything else never reaches an address.
_ID = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")

_CHARSET = re.compile(r"charset\s*=\s*\"?([\w.-]+)", re.I)


@dataclass(frozen=True)
class Mail:
    id: str
    thread: str
    sender: str
    to: str
    subject: str
    date: str
    snippet: str
    unread: bool


@dataclass(frozen=True)
class Letter:
    """One message, read in full."""

    mail: Mail
    text: str
    truncated: bool
    attachments: tuple[str, ...]
    """Their names only. Nothing attached is opened."""


def _headers(part: dict) -> dict[str, str]:
    return {str(h.get("name", "")).lower(): str(h.get("value", ""))
            for h in part.get("headers") or [] if isinstance(h, dict)}


def _mail(data: dict) -> Mail:
    headers = _headers(data.get("payload") or {})
    return Mail(str(data.get("id", "")), str(data.get("threadId", "")),
                headers.get("from", ""), headers.get("to", ""),
                headers.get("subject", "") or "(no subject)", headers.get("date", ""),
                html.unescape(str(data.get("snippet", ""))),
                "UNREAD" in (data.get("labelIds") or []))


def _decode(part: dict) -> str:
    data = str((part.get("body") or {}).get("data") or "")
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (ValueError, TypeError):
        return ""
    found = _CHARSET.search(_headers(part).get("content-type", ""))
    try:
        return raw.decode(found.group(1) if found else "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _walk(part: dict, plain: list[str], marked_up: list[str], names: list[str],
          depth: int = 0) -> None:
    if depth > 20:
        return
    mime = str(part.get("mimeType", "")).lower()
    if part.get("filename"):
        names.append(str(part["filename"]))
        return
    if mime == "text/plain":
        plain.append(_decode(part))
    elif mime == "text/html":
        marked_up.append(_decode(part))
    for child in part.get("parts") or []:
        if isinstance(child, dict):
            _walk(child, plain, marked_up, names, depth + 1)


def search(accounts: GoogleAccounts, address: str, query: str, *, policy, audit, actor: str,
           limit: int = MAX_RESULTS) -> list[Mail]:
    """Messages matching \a query, as Gmail's own search box reads it, newest first."""
    limit = max(1, min(int(limit), MAX_RESULTS))
    listing = accounts.get(address, "mail",
                           with_query(f"{API}/messages", {"q": query, "maxResults": str(limit)}),
                           policy=policy, audit=audit, actor=actor)
    found = []
    for entry in (listing.get("messages") or [])[:limit]:
        message_id = str(entry.get("id", "")) if isinstance(entry, dict) else ""
        if not _ID.match(message_id):
            continue
        url = (with_query(f"{API}/messages/{message_id}", {"format": "metadata"})
               + "".join(f"&metadataHeaders={name}" for name in HEADERS))
        found.append(_mail(accounts.get(address, "mail", url, policy=policy, audit=audit,
                                        actor=actor)))
    return found


def read(accounts: GoogleAccounts, address: str, message_id: str, *, policy, audit,
         actor: str) -> Letter:
    """One message: its text, preferring the plain version, and its attachments' names."""
    message_id = str(message_id).strip()
    if not _ID.match(message_id):
        raise ConnectError(f"{message_id!r} is not a Gmail message id.")
    data = accounts.get(address, "mail",
                        with_query(f"{API}/messages/{message_id}", {"format": "full"}),
                        policy=policy, audit=audit, actor=actor)
    plain: list[str] = []
    marked_up: list[str] = []
    names: list[str] = []
    _walk(data.get("payload") or {}, plain, marked_up, names)
    text = "\n\n".join(p for p in plain if p.strip())
    if not text:
        text = "\n\n".join(readable(page)[1] for page in marked_up if page.strip())
    mail = _mail(data)
    text = text.strip() or mail.snippet
    return Letter(mail, text[:MAX_TEXT_CHARS], len(text) > MAX_TEXT_CHARS, tuple(names))
