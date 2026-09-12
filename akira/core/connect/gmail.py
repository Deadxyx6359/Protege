"""Gmail, as a connected address (C5): reading, and sending what the person approved.

Reading is held to `mail.read` for the address, and an email says whatever its
sender wanted, so the tools that show one to a model frame it as material, not
instructions. Sending is held to `mail.send`, and a message is checked by
`draft` before anyone is asked about it: real addresses, a subject on one line,
a body short enough to be read in full when the person approves it.
"""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr

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

_ADDRESS = re.compile(r"\A[^@\s,;<>\"]+@[^@\s,;<>\"]+\.[^@\s,;<>\"]+\Z")

#: People one message may go to at once.
MAX_RECIPIENTS = 10

#: The longest subject, and the longest message: short enough for the person to
#: read in full when they approve it.
MAX_SUBJECT_CHARS = 200
MAX_SEND_CHARS = 5_000

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


# -- sending --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Outgoing:
    """A message checked and ready to show the person, then to send."""

    sender: str
    to: tuple[str, ...]
    subject: str
    body: str


def _recipients(to) -> tuple[str, ...]:
    items = to if isinstance(to, (list, tuple)) else str(to).replace(";", ",").split(",")
    found: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        _, address = parseaddr(text)
        address = address.strip().lower()
        if not _ADDRESS.match(address):
            raise ConnectError(f"{text!r} is not an email address.")
        if address not in found:
            found.append(address)
    if not found:
        raise ConnectError("Say who the message is for.")
    if len(found) > MAX_RECIPIENTS:
        raise ConnectError(f"A message goes to at most {MAX_RECIPIENTS} people at once.")
    return tuple(found)


def draft(sender: str, to, subject: str, body: str) -> Outgoing:
    """Check a message before anyone is asked about it. Raises `ConnectError` with why not."""
    if not _ADDRESS.match(str(sender).strip().lower()):
        raise ConnectError("No Google address is connected for sending. Connect one, with "
                           "sending switched on, in Settings, Accounts.")
    # One line: a line break in a subject would begin a header of its own.
    subject = " ".join(str(subject).split())
    if not subject:
        raise ConnectError("A message needs a subject.")
    if len(subject) > MAX_SUBJECT_CHARS:
        raise ConnectError(f"Keep the subject to {MAX_SUBJECT_CHARS} characters.")
    text = str(body).replace("\r\n", "\n").strip()
    if not text:
        raise ConnectError("A message needs something to say.")
    if len(text) > MAX_SEND_CHARS:
        raise ConnectError(f"A message is at most {MAX_SEND_CHARS} characters, so the person "
                           "can read all of it before it goes.")
    return Outgoing(str(sender).strip().lower(), _recipients(to), subject, text)


def send(accounts: GoogleAccounts, message: Outgoing, *, policy, audit, actor: str) -> str:
    """Send \a message from its sender's Gmail, once. Returns Gmail's id for it."""
    mime = EmailMessage()
    mime["From"] = message.sender
    mime["To"] = ", ".join(message.to)
    mime["Subject"] = message.subject
    mime.set_content(message.body)
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
    sent = accounts.post(message.sender, "send", f"{API}/messages/send", {"raw": raw},
                         policy=policy, audit=audit, actor=actor)
    return str(sent.get("id", ""))
