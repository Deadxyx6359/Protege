"""An Obsidian vault, kept by an assistant, so the person never has to open it.

Everything here reads and writes the vault's Markdown files directly and never
touches Obsidian's own state. `.obsidian`, `.trash` and every other dot-folder
are neither read nor written.

**Automatic, but never unrecoverable.** Writing notes does not stop to ask —
that would defeat a second brain that maintains itself — so every overwrite
first saves the previous version, in Protégé's configuration folder rather
than the vault, where history files would clutter it and sync as junk. Any
version can be restored.

**Never over someone else's edit.** The person may have the vault open in
Obsidian, or synced from a phone. Each note carries a version — a hash of its
bytes — and a rewrite must name the version it was based on. If the file has
changed since, the write is refused and says why, rather than silently
discarding the newer text. Appends check the same way.

**Only what may be read.** Search and backlinks walk the vault through a
`may_read` check, so a vault whose root sits above the granted folder is only
ever read where the permission reaches.

Links resolve the way Obsidian resolves them: a path if one is given, otherwise
a note of that name in the same folder, otherwise the shortest path. Daily
notes follow the vault's own `.obsidian/daily-notes.json` folder and format.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterator

from protege.core.config import config_dir
from protege.security.paths import PathViolation, real, reject_dangerous

from . import markdown
from .markdown import Link

EXCLUDED_DIRS = frozenset({".obsidian", ".trash", ".git", ".protege", "node_modules"})
MAX_NOTE_BYTES = 5_000_000
MAX_NOTES = 20_000

#: Previous versions kept per note.
HISTORY_KEEP = 20

#: Characters Obsidian will not use in a note name, or that break its links.
_BAD_NAME = re.compile(r'[\\:*?"<>|#^\[\]]')
_VERSION = re.compile(r"[0-9a-f]{16}")
_BOM = "﻿"

_MOMENT = re.compile(r"\[([^\]]*)\]|YYYY|YY|MMMM|MMM|MM|M|DDDD|DDD|DD|Do|D|dddd|ddd|dd|d|ww|w|gggg")


class VaultError(ValueError):
    """Something the vault will not do, with a reason for the person."""


class ConflictError(VaultError):
    """The note changed after it was read."""


def version_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def find_root(path: Path) -> Path | None:
    """The vault holding \a path: the nearest folder with an `.obsidian` inside."""
    current = path if path.is_dir() else path.parent
    for candidate in (current, *current.parents):
        if (candidate / ".obsidian").is_dir():
            return candidate
    return None


def _ordinal(number: int) -> str:
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def moment_format(day: date, pattern: str) -> str:
    """A date in Obsidian's (moment.js) format, e.g. `YYYY-MM-DD` or `dddd, Do MMMM`."""
    iso_year, iso_week, _ = day.isocalendar()

    def token(match: re.Match) -> str:
        if match.group(1) is not None:
            return match.group(1)
        return {
            "YYYY": f"{day.year:04d}", "YY": f"{day.year % 100:02d}",
            "MMMM": day.strftime("%B"), "MMM": day.strftime("%b"),
            "MM": f"{day.month:02d}", "M": str(day.month),
            "DDDD": f"{day.timetuple().tm_yday:03d}", "DDD": str(day.timetuple().tm_yday),
            "DD": f"{day.day:02d}", "Do": _ordinal(day.day), "D": str(day.day),
            "dddd": day.strftime("%A"), "ddd": day.strftime("%a"),
            "dd": day.strftime("%a")[:2], "d": str(day.isoweekday() % 7),
            "ww": f"{iso_week:02d}", "w": str(iso_week), "gggg": f"{iso_year:04d}",
        }[match.group(0)]

    return _MOMENT.sub(token, pattern)


def _write_atomically(path: Path, data: bytes) -> None:
    handle, temporary = tempfile.mkstemp(prefix=".protege-", suffix=".md", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


@dataclass(frozen=True, slots=True)
class Note:
    path: Path
    rel: str
    title: str
    frontmatter: dict
    body: str
    tags: tuple[str, ...]
    links: tuple[Link, ...]
    version: str
    error: str = ""


@dataclass(frozen=True, slots=True)
class Hit:
    rel: str
    title: str
    score: int
    snippet: str


def _snippet(body: str, word: str, width: int = 90) -> str:
    flat = " ".join(body.split())
    at = flat.lower().find(word.lower())
    if at < 0:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, at - width // 3)
    piece = flat[start:start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(flat) else "")


class Vault:
    """One vault on disk."""

    def __init__(self, root: str | Path, *, may_read: Callable[[Path], bool] | None = None,
                 history_dir: Path | None = None) -> None:
        self.root = real(root)
        if not self.root.is_dir():
            raise VaultError(f"{root} is not a folder.")
        self._may_read = may_read or (lambda path: True)
        key = hashlib.sha256(str(self.root).lower().encode("utf-8")).hexdigest()[:16]
        self.history_dir = history_dir if history_dir is not None else config_dir() / "vault-history" / key
        self._catalogue_cache: tuple[dict[str, Path], dict[str, list[Path]]] | None = None

    # -- where things are ------------------------------------------------------------

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def may_read(self, path: Path) -> bool:
        """Whether the permission this vault was opened under reaches \a path."""
        return self._may_read(path)

    def locate(self, path: str | Path) -> Path:
        """An absolute path inside the vault, or a refusal."""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            resolved = real(candidate)
        except (PathViolation, OSError, ValueError) as exc:
            raise VaultError(f"{path} cannot be used: {exc}") from None
        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise VaultError(f"{path} is outside the vault.")
        return resolved

    def note_paths(self) -> Iterator[Path]:
        """Every note that may be read, skipping Obsidian's and Protégé's folders."""
        count = 0
        for current, folders, files in os.walk(self.root):
            folders[:] = sorted(f for f in folders if f not in EXCLUDED_DIRS and not f.startswith("."))
            for name in sorted(files):
                if not name.lower().endswith(".md"):
                    continue
                path = Path(current) / name
                if not self._may_read(path):
                    continue
                yield path
                count += 1
                if count >= MAX_NOTES:
                    return

    # -- reading ------------------------------------------------------------------------

    def read(self, path: str | Path) -> Note:
        target = self.locate(path)
        rel = self.rel(target)
        if not self._may_read(target):
            raise VaultError(f"{rel} is outside what may be read.")
        try:
            data = target.read_bytes()
        except FileNotFoundError:
            raise VaultError(f"There is no note at {rel}.") from None
        except OSError as exc:
            raise VaultError(f"{rel} could not be read: {exc}") from None
        if len(data) > MAX_NOTE_BYTES:
            raise VaultError(f"{rel} is over {MAX_NOTE_BYTES // 1_000_000} MB, too large for a note.")
        try:
            text = data.decode("utf-8").lstrip(_BOM)
        except UnicodeDecodeError:
            return Note(target, rel, target.stem, {}, "", (), (), version_of(data),
                        "this file is not UTF-8 text")
        frontmatter, body, error = markdown.split(text)
        return Note(target, rel, target.stem, frontmatter, body,
                    markdown.tags(frontmatter, body), markdown.links(body),
                    version_of(data), error)

    def _catalogue(self) -> tuple[dict[str, Path], dict[str, list[Path]]]:
        if self._catalogue_cache is None:
            by_path: dict[str, Path] = {}
            by_name: dict[str, list[Path]] = {}
            for path in self.note_paths():
                by_path[self.rel(path)[:-3].lower()] = path
                by_name.setdefault(path.stem.lower(), []).append(path)
            self._catalogue_cache = (by_path, by_name)
        return self._catalogue_cache

    def resolve(self, target: str, source: Path | None = None) -> Path | None:
        """The note a link points at, as Obsidian would choose it, or None."""
        wanted = target.strip().replace("\\", "/")
        if wanted.lower().endswith(".md"):
            wanted = wanted[:-3]
        if not wanted:
            return None
        by_path, by_name = self._catalogue()

        if source is not None and ("/" in wanted or wanted.startswith(".")):
            try:
                relative = real(source.parent / (wanted + ".md"))
            except (PathViolation, OSError, ValueError):
                relative = None
            if (relative is not None and relative.is_relative_to(self.root)
                    and self.rel(relative)[:-3].lower() in by_path):
                return by_path[self.rel(relative)[:-3].lower()]

        key = wanted.lower().lstrip("/")
        if key in by_path:
            return by_path[key]
        if "/" in key:
            matches = [path for rel, path in by_path.items() if rel.endswith("/" + key)]
        else:
            matches = by_name.get(key, [])
        if not matches:
            return None
        if source is not None:
            beside = [m for m in matches if m.parent == source.parent]
            if beside:
                return beside[0]
        return min(matches, key=lambda path: (len(self.rel(path)), self.rel(path)))

    def backlinks(self, path: str | Path) -> list[str]:
        """The notes that link to \a path."""
        target = self.locate(path)
        linking = []
        for source in self.note_paths():
            if source == target:
                continue
            try:
                note = self.read(source)
            except VaultError:
                continue
            if any(self.resolve(link.target, source) == target for link in note.links):
                linking.append(note.rel)
        return linking

    def search(self, query: str, limit: int = 20) -> list[Hit]:
        """Notes containing every word of \a query. Titles outrank tags outrank text."""
        words = [w for w in query.lower().split() if w]
        if not words:
            raise VaultError("Say what to look for.")
        hits = []
        for path in self.note_paths():
            try:
                note = self.read(path)
            except VaultError:
                continue
            title, body = note.title.lower(), note.body.lower()
            tagged = {t.lower() for t in note.tags}
            if not all(w in title or w in body or w.lstrip("#") in tagged for w in words):
                continue
            score = sum(10 * (w in title) + 5 * (w.lstrip("#") in tagged) + min(body.count(w), 5)
                        for w in words)
            hits.append(Hit(note.rel, note.title, score, _snippet(note.body, words[0])))
        hits.sort(key=lambda hit: (-hit.score, hit.rel))
        return hits[:limit]

    def daily_settings(self) -> tuple[str, str]:
        """(folder, date format) from Obsidian's daily-notes settings, or the defaults."""
        folder, pattern = "", "YYYY-MM-DD"
        try:
            raw = json.loads((self.root / ".obsidian" / "daily-notes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        if isinstance(raw, dict):
            folder = str(raw.get("folder") or "").strip().strip("/")
            pattern = str(raw.get("format") or "").strip() or pattern
        return folder, pattern

    def daily_path(self, day: date) -> Path:
        folder, pattern = self.daily_settings()
        name = moment_format(day, pattern)
        return self.locate(f"{folder}/{name}.md" if folder else f"{name}.md")

    # -- writing ------------------------------------------------------------------------

    def _writable(self, path: str | Path) -> Path:
        target = self.locate(path)
        parts = target.relative_to(self.root).parts
        if target.suffix.lower() != ".md":
            raise VaultError("Notes are Markdown files ending in .md.")
        if any(part.startswith(".") or part in EXCLUDED_DIRS for part in parts):
            raise VaultError(f"{'/'.join(parts)} is inside a folder Obsidian or Protégé keeps for itself.")
        if _BAD_NAME.search(target.stem):
            raise VaultError(f'{target.stem!r} uses characters Obsidian cannot have in a note '
                             'name: \\ : * ? " < > | # ^ [ ]')
        try:
            reject_dangerous(target)
        except (PathViolation, ValueError) as exc:
            raise VaultError(str(exc)) from None
        return target

    def _history_folder(self, target: Path) -> Path:
        return self.history_dir / self.rel(target).replace("/", "__")

    def _remember(self, target: Path, data: bytes) -> None:
        folder = self._history_folder(target)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{version_of(data)}.md").write_bytes(data)
        for old in sorted(folder.glob("*.md"))[:-HISTORY_KEEP]:
            with contextlib.suppress(OSError):
                old.unlink()

    def write(self, path: str | Path, text: str, *, expected: str | None = None) -> str:
        """Write a note. Returns its new version.

        If the note exists and \a expected is given, it must be the version the
        change was based on. The previous content is kept as a restorable version.
        """
        target = self._writable(path)
        data = text.encode("utf-8")
        if len(data) > MAX_NOTE_BYTES:
            raise VaultError(f"A note is limited to {MAX_NOTE_BYTES // 1_000_000} MB.")
        if target.exists():
            try:
                current = target.read_bytes()
            except OSError as exc:
                raise VaultError(f"{self.rel(target)} could not be read: {exc}") from None
            if expected is not None and version_of(current) != expected:
                raise ConflictError(
                    f"{self.rel(target)} changed after it was read — most likely edited in "
                    "Obsidian or synced from another device. Read it again and make the change "
                    "to the new version, so that edit is not lost.")
            if current == data:
                return version_of(data)
            self._remember(target, current)
        elif expected:
            raise ConflictError(f"{self.rel(target)} was moved or deleted after it was read.")
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(target, data)
        self._catalogue_cache = None
        return version_of(data)

    def create(self, path: str | Path, text: str) -> str:
        target = self._writable(path)
        if target.exists():
            raise VaultError(f"{self.rel(target)} already exists.")
        return self.write(target, text)

    def append(self, path: str | Path, text: str, heading: str | None = None) -> str:
        """Add \a text to a note — under \a heading if given — creating it if needed.

        The frontmatter is carried over byte for byte, and the note's version is
        checked at the moment of writing, so an edit made meanwhile is not lost.
        """
        target = self._writable(path)
        if not text.strip():
            raise VaultError("There is nothing to add.")
        bom = ""
        version = None
        current = ""
        if target.exists():
            data = target.read_bytes()
            version = version_of(data)
            try:
                current = data.decode("utf-8")
            except UnicodeDecodeError:
                raise VaultError(f"{self.rel(target)} is not UTF-8 text, so it was left alone.") from None
            if current.startswith(_BOM):
                bom, current = _BOM, current[1:]
        block, body = markdown.frontmatter_block(current)
        return self.write(target, bom + block + markdown.append_under(body, text, heading),
                          expected=version)

    def history(self, path: str | Path) -> list[tuple[str, str]]:
        """(version, when it was replaced), newest first."""
        folder = self._history_folder(self.locate(path))
        entries = []
        for item in sorted(folder.glob("*.md"), reverse=True):
            stamp, _, version = item.stem.rpartition("-")
            try:
                when = datetime.strptime(stamp, "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            entries.append((version, when))
        return entries

    def restore(self, path: str | Path, version: str) -> str:
        """Put a saved version back. The version it replaces is saved in turn."""
        target = self._writable(path)
        if not _VERSION.fullmatch(version or ""):
            raise VaultError(f"{version!r} is not a note version.")
        saved = next(iter(self._history_folder(target).glob(f"*-{version}.md")), None)
        if saved is None:
            raise VaultError(f"There is no saved version {version} of {self.rel(target)}.")
        return self.write(target, saved.read_bytes().decode("utf-8"))
