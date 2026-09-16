"""Reading Google Drive, as a connected address (C5).

Only reading: Google is asked for `drive.readonly`, and every request is held
to `cloud.read` for the address. A file is found by its name or its words, and
read as text: a Google Doc, Sheet or Slides file by asking Google for it as text,
and a Word, Excel, PowerPoint or PDF file by downloading it, capped, and reading
it with the same readers `read_document` uses. Nothing in Drive is changed, and
nothing downloaded is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from akira.core.documents import KINDS, PackageError, text_of
from akira.core.net import with_query

from .google import ConnectError, GoogleAccounts

API = "https://www.googleapis.com/drive/v3/files"

#: The most files one search returns.
MAX_RESULTS = 20

#: The most of a file that is downloaded to be read.
MAX_DOWNLOAD = 15_000_000

#: The most of a file's text that is kept.
MAX_TEXT = 60_000

#: What Drive's file ids are made of. Checked rather than escaped, so an id can
#: never become part of another address.
_FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,200}")

#: Google's own formats, and what each is asked for as.
EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", "a Google Doc"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", "a Google Sheet"),
    "application/vnd.google-apps.presentation": ("text/plain", "Google Slides"),
}

#: Plain text formats read as they are.
TEXT_TYPES = ("text/", "application/json", "application/xml")

_FIELDS = "id,name,mimeType,modifiedTime,size,owners(emailAddress)"


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    kind: str
    """Google's name for its type, such as `application/pdf`."""
    modified: str
    size: int
    """In bytes; 0 for Google's own formats, which have none."""
    owner: str


@dataclass(frozen=True)
class Read:
    file: DriveFile
    text: str
    truncated: bool


def file_id(text: str) -> str:
    """\a text as a Drive file id. Raises `ConnectError` if it is not one."""
    value = str(text).strip()
    if not _FILE_ID.fullmatch(value):
        raise ConnectError(f"{value!r} is not a Drive file id. search_drive gives each file's id.")
    return value


def _quoted(words: str) -> str:
    """\a words inside a Drive query's single quotes."""
    return words.replace("\\", "\\\\").replace("'", "\\'")


def _file(item: dict) -> DriveFile:
    owners = item.get("owners") or []
    owner = owners[0].get("emailAddress", "") if owners and isinstance(owners[0], dict) else ""
    try:
        size = int(item.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return DriveFile(str(item.get("id") or ""), str(item.get("name") or "(untitled)"),
                     str(item.get("mimeType") or ""), str(item.get("modifiedTime") or ""), size,
                     str(owner))


def search(accounts: GoogleAccounts, address: str, words: str, *, policy, audit, actor: str,
           limit: int = MAX_RESULTS) -> list[DriveFile]:
    """Files in \a address's Drive whose name or text has \a words, not in the bin."""
    words = " ".join(str(words).split())
    if not words:
        raise ConnectError("Say what to look for.")
    query = (f"trashed = false and (name contains '{_quoted(words)}' or "
             f"fullText contains '{_quoted(words)}')")
    url = with_query(API, {"q": query, "pageSize": str(max(1, min(int(limit), MAX_RESULTS))),
                           "fields": f"files({_FIELDS})", "spaces": "drive"})
    data = accounts.get(address, "drive", url, policy=policy, audit=audit, actor=actor)
    return [_file(item) for item in data.get("files") or [] if isinstance(item, dict)]


def read(accounts: GoogleAccounts, address: str, ident: str, *, policy, audit,
         actor: str) -> Read:
    """One file, as text. Raises `ConnectError` for a file that cannot be read as text."""
    found = _file(accounts.get(address, "drive",
                               with_query(f"{API}/{file_id(ident)}", {"fields": _FIELDS}),
                               policy=policy, audit=audit, actor=actor))
    signed = {"policy": policy, "audit": audit, "actor": actor}
    if found.kind in EXPORTS:
        wanted, _ = EXPORTS[found.kind]
        response = accounts.download(address, "drive",
                                     with_query(f"{API}/{found.id}/export", {"mimeType": wanted}),
                                     max_bytes=MAX_DOWNLOAD, **signed)
        text = response.text()
        truncated = response.truncated
    elif found.kind.startswith("application/vnd.google-apps."):
        raise ConnectError(f"{found.name} is a kind of Google file that cannot be read as text.")
    else:
        suffix = PurePosixPath(found.name).suffix.lower()
        readable_document = suffix in KINDS
        if not readable_document and not found.kind.startswith(TEXT_TYPES):
            raise ConnectError(f"{found.name} is {found.kind or 'a file'}, which cannot be read "
                               "as text. Word, Excel, PowerPoint, PDF and plain text files can.")
        if found.size > MAX_DOWNLOAD:
            raise ConnectError(f"{found.name} is {found.size // 1_000_000} MB; at most "
                               f"{MAX_DOWNLOAD // 1_000_000} MB is read.")
        response = accounts.download(address, "drive",
                                     with_query(f"{API}/{found.id}", {"alt": "media"}),
                                     max_bytes=MAX_DOWNLOAD, **signed)
        if response.truncated:
            raise ConnectError(f"{found.name} is larger than the {MAX_DOWNLOAD // 1_000_000} MB "
                               "read, so it was not read.")
        if readable_document:
            try:
                text = text_of(response.body, found.name)
            except PackageError as exc:
                raise ConnectError(f"{found.name} could not be read: {exc}") from None
        else:
            text = response.text()
        truncated = False
    cut = len(text) > MAX_TEXT
    return Read(found, text[:MAX_TEXT], truncated or cut)
