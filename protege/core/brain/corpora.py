"""What else the index can hold: a folder of documents, and the saved conversations.

The index reads a *corpus*: anything with a root, the paths under it, a way to
read one, and a `may_read` check. The vault is one. These are the other two
that retrieval (B4) searches.

**Documents** are the Word, Excel, PowerPoint and PDF files in a folder, and
Markdown and text files beside them, read with the same code as
`read_document`, so what a search finds is what reading the file shows. Only
files `may_read` allows are opened, checked on the real path, so a link inside
the folder cannot lead a search outside it. The formats' own limits apply — a
ZIP bomb is refused, not unpacked — and anything unreadable is skipped.

**Conversations** are Protégé's saved chats. Each exchange, a question and its
answer, is a section, so a hit cites the turn it came from rather than a thread
an hour long. Failed turns are left out: an error is not a memory.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from protege.core.documents import KINDS, PackageError, text_of
from protege.security.paths import PathViolation, real

from .index import Chunk, windows
from .vault import EXCLUDED_DIRS, VaultError, version_of

TEXT_SUFFIXES = frozenset({".md", ".txt"})
MAX_DOCUMENT_BYTES = 25_000_000
MAX_TEXT_BYTES = 5_000_000
MAX_DOCUMENTS = 5_000
MAX_CONVERSATION_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Item:
    """One file as the index sees it."""

    rel: str
    title: str
    body: str
    version: str
    tags: tuple[str, ...] = ()
    sections: tuple[Chunk, ...] = ()


def _hidden(folder: str) -> bool:
    return folder.startswith(".") or folder in EXCLUDED_DIRS or folder == "__pycache__"


class DocumentFolder:
    """The documents under one folder."""

    kind = "documents"

    def __init__(self, root: str | Path, *, may_read: Callable[[Path], bool] | None = None) -> None:
        self.root = real(root)
        if not self.root.is_dir():
            raise VaultError(f"{root} is not a folder.")
        self._may_read = may_read or (lambda path: True)

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def may_read(self, path: Path) -> bool:
        return self._may_read(path)

    def note_paths(self) -> Iterator[Path]:
        count = 0
        for current, folders, files in os.walk(self.root):
            folders[:] = sorted(f for f in folders if not _hidden(f))
            for name in sorted(files):
                suffix = Path(name).suffix.lower()
                # ~$name is the lock file Office leaves beside a document it has open.
                if name.startswith("~$") or (suffix not in KINDS and suffix not in TEXT_SUFFIXES):
                    continue
                path = Path(current) / name
                if not self._may_read(path):
                    continue
                yield path
                count += 1
                if count >= MAX_DOCUMENTS:
                    return

    def read(self, path: Path) -> Item:
        try:
            target = real(path)
        except (PathViolation, OSError, ValueError) as exc:
            raise VaultError(f"{path} cannot be used: {exc}") from None
        if not target.is_relative_to(self.root) or not self._may_read(target):
            raise VaultError(f"{path} is outside what may be read.")
        rel = self.rel(path)
        text_file = target.suffix.lower() in TEXT_SUFFIXES
        try:
            if target.stat().st_size > (MAX_TEXT_BYTES if text_file else MAX_DOCUMENT_BYTES):
                raise VaultError(f"{rel} is too large to search.")
            raw = target.read_bytes()
        except OSError as exc:
            raise VaultError(f"{rel} could not be read: {exc}") from None
        try:
            text = raw.decode("utf-8-sig") if text_file else text_of(raw, target.name)
        except (PackageError, ValueError, LookupError) as exc:
            raise VaultError(f"{rel} could not be read: {exc}") from None
        return Item(rel, target.stem, text, version_of(raw))


def _headline(question: str, width: int = 60) -> str:
    line = " ".join(question.split())
    return line if len(line) <= width else line[:width - 1].rstrip() + "…"


def _exchange(title: str, question: str, answer: str) -> list[Chunk]:
    heading = f"{title} › {_headline(question)}" if question else title
    text = "\n\n".join(part for part in (question and f"You: {question}",
                                          answer and f"Assistant: {answer}") if part)
    return [Chunk(heading, piece) for piece in windows(text)]


class ConversationArchive:
    """The saved conversations, one exchange to a section."""

    kind = "conversations"

    def __init__(self, directory: Path | None = None) -> None:
        if directory is None:
            from protege.core.conversations import conversations_dir
            directory = conversations_dir()
        self.root = Path(directory)

    def rel(self, path: Path) -> str:
        return path.stem

    def may_read(self, path: Path) -> bool:
        # One capability, memory.read, covers every conversation; the tool checks it.
        return True

    def note_paths(self) -> Iterator[Path]:
        if self.root.is_dir():
            yield from sorted(p for p in self.root.glob("*.json") if not p.name.startswith("."))

    def read(self, path: Path) -> Item:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise VaultError(f"conversation {path.stem} could not be read: {exc}") from None
        if len(raw) > MAX_CONVERSATION_BYTES:
            raise VaultError(f"conversation {path.stem} is implausibly large.")
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise VaultError(f"conversation {path.stem} is not readable.") from None
        if not isinstance(data, dict):
            raise VaultError(f"conversation {path.stem} is not readable.")

        title = " ".join(str(data.get("title") or "Untitled").split())
        sections: list[Chunk] = []
        question = None
        for message in data.get("messages") or []:
            if not isinstance(message, dict) or message.get("error"):
                continue
            text = str(message.get("text") or "").strip()
            if not text:
                continue
            if message.get("role") == "user":
                if question is not None:
                    sections += _exchange(title, question, "")
                question = text
            elif message.get("role") == "assistant":
                sections += _exchange(title, question or "", text)
                question = None
        if question is not None:
            sections += _exchange(title, question, "")
        body = "\n\n".join(chunk.text for chunk in sections)
        return Item(path.stem, title, body, version_of(raw), sections=tuple(sections))
