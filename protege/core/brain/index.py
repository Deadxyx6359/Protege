"""A search index over the vault: ranked, incremental, and kept on disk.

Searching by reading every note on every query is fine for a few hundred notes
and not for a few thousand, and it cannot rank: a note that mentions a word
once scores like one that is about it. The index fixes both, and stays small
enough to understand in one sitting.

**Sections, not files.** Notes are split at their headings, and long sections
into overlapping windows. A hit points at the part of a note that matters — the
citation a retrieval step wants — and one long note cannot drown out ten short
ones; at most two sections of any note reach the results.

**BM25**, the standard ranking for lexical search: a word counts for more the
more often a section uses it and the fewer sections use it at all. Sections
holding every word of the query come first. Pure Python over SQLite, both in
the standard library — `requirements.txt` rules out embedding stacks that fetch
model weights over the network. Embeddings can join later through llama.cpp,
which is already here, once an embedding model is configured.

**Forgiving about word forms, timidly.** A query word of four letters or more
matches any indexed word it begins, so "garden" finds "gardening"; a plural in
the query is folded first, so "gardens" finds "garden". No stemmer — a clever
one gets "news" wrong and "business" worse.

**Incremental.** A note is re-read only when its size or modification time has
changed, and re-indexed only when its content hash has, so refreshing an
unchanged vault reads nothing.

**Held to the grant.** Only notes the vault may read are indexed, notes that
are no longer readable are dropped, and results are filtered again when the
query runs. The index is a cache of what the permission already allowed, never
a way around it.

The database lives in Protégé's configuration folder, one per vault. It is
disposable: a damaged one is deleted and rebuilt rather than trusted.
"""

from __future__ import annotations

import contextlib
import hashlib
import math
import re
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from protege.core.config import config_dir

from .vault import Vault, VaultError

SCHEMA_VERSION = 1
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200
MAX_CHUNKS_PER_NOTE = 400
MAX_SECTIONS_PER_NOTE = 2
PREFIX_MIN = 4
K1, B = 1.2, 0.75

_STOPWORDS = frozenset(
    "a an and are as at be but by for from had has have he her his i if in into is it its "
    "me my no not of on or our she so than that the their them then there these they this "
    "to was we were what when which who why will with would you your".split())
_WORD = re.compile(r"\w+")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")

_REFRESHING: dict[str, threading.Lock] = {}
_REFRESHING_GUARD = threading.Lock()


def _refresh_lock(path: Path) -> threading.Lock:
    with _REFRESHING_GUARD:
        return _REFRESHING.setdefault(str(path).lower(), threading.Lock())


def terms(text: str) -> list[str]:
    """The words a section is indexed under: lower case, common words dropped."""
    return [w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS and (len(w) > 1 or w.isdigit())]


def _fold(word: str) -> str:
    """A query word's plural folded away, when that leaves enough of a word."""
    folded = word
    if len(word) > 4 and (word.endswith(("ches", "shes")) or
                          (word.endswith("es") and word[-3] in "osxz")):
        folded = word[:-2]
    elif len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        folded = word[:-1]
    return folded if len(folded) >= PREFIX_MIN else word


@dataclass(frozen=True, slots=True)
class Chunk:
    heading: str
    """The note's title and the headings above this section, joined with ›."""
    text: str


@dataclass(frozen=True, slots=True)
class Result:
    rel: str
    heading: str
    snippet: str
    score: float
    complete: bool
    """Whether the section holds every word of the query."""


def _windows(text: str) -> list[str]:
    if len(text) <= CHUNK_CHARS:
        return [text]
    pieces, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            space = text.rfind(" ", start + CHUNK_CHARS // 2, end)
            if space > start:
                end = space
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return [p for p in pieces if p]


def chunks(title: str, body: str) -> list[Chunk]:
    """A note as sections under their headings, long ones windowed."""
    sections: list[tuple[str, str]] = []
    trail: list[tuple[int, str]] = []
    lines: list[str] = []

    def heading() -> str:
        names = [name for _, name in trail]
        if names and names[0].lower() == title.lower():
            names = names[1:]
        return " › ".join([title] + names)

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            sections.append((heading(), text))
        lines.clear()

    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            lines.append(line)
            continue
        match = None if fenced else _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            trail = [(depth, name) for depth, name in trail if depth < level]
            trail.append((level, match.group(2).strip()))
            continue
        lines.append(line)
    flush()
    if not sections:
        # A note that is only a title is still findable by it.
        sections.append((title, ""))
    return [Chunk(name, window) for name, text in sections for window in (_windows(text) or [""])]


def _snippet(text: str, words: list[str], width: int = 160) -> str:
    flat = " ".join(text.split())
    lowered = flat.lower()
    positions = [lowered.find(w) for w in words if lowered.find(w) >= 0]
    if not positions:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, min(positions) - width // 4)
    piece = flat[start:start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(flat) else "")


class Index:
    """The search index for one vault."""

    def __init__(self, vault: Vault, *, path: Path | None = None) -> None:
        self.vault = vault
        key = hashlib.sha256(str(vault.root).lower().encode("utf-8")).hexdigest()[:16]
        self.path = path if path is not None else config_dir() / "index" / f"{key}.sqlite"

    # -- storage -----------------------------------------------------------------------

    @staticmethod
    def _schema(db: sqlite3.Connection) -> None:
        if db.execute("PRAGMA user_version").fetchone()[0] not in (0, SCHEMA_VERSION):
            for table in ("postings", "chunks", "notes"):
                db.execute(f"DROP TABLE IF EXISTS {table}")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS notes (rel TEXT PRIMARY KEY, version TEXT, mtime REAL, size INTEGER);
            CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, rel TEXT,
                                               heading TEXT, text TEXT, length INTEGER);
            CREATE INDEX IF NOT EXISTS chunks_rel ON chunks(rel);
            CREATE TABLE IF NOT EXISTS postings (term TEXT, chunk INTEGER, tf INTEGER);
            CREATE INDEX IF NOT EXISTS postings_term ON postings(term);
            CREATE INDEX IF NOT EXISTS postings_chunk ON postings(chunk);
        """)
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            self._schema(db)
            return db
        except sqlite3.DatabaseError:
            # A damaged cache is thrown away and rebuilt, never trusted.
            db.close()
            with contextlib.suppress(OSError):
                self.path.unlink()
            db = sqlite3.connect(self.path, timeout=10)
            self._schema(db)
            return db

    @staticmethod
    def _drop(db: sqlite3.Connection, rel: str) -> None:
        db.execute("DELETE FROM postings WHERE chunk IN (SELECT id FROM chunks WHERE rel = ?)", (rel,))
        db.execute("DELETE FROM chunks WHERE rel = ?", (rel,))

    @staticmethod
    def _add(db: sqlite3.Connection, note, mtime: float, size: int) -> None:
        db.execute("INSERT OR REPLACE INTO notes (rel, version, mtime, size) VALUES (?, ?, ?, ?)",
                   (note.rel, note.version, mtime, size))
        for number, chunk in enumerate(chunks(note.title, note.body)[:MAX_CHUNKS_PER_NOTE]):
            text = chunk.heading + "\n" + chunk.text
            if number == 0 and note.tags:
                # Tags describe the note, so they are counted once, not per section.
                text += "\n" + " ".join(note.tags)
            words = terms(text)
            cursor = db.execute("INSERT INTO chunks (rel, heading, text, length) VALUES (?, ?, ?, ?)",
                                (note.rel, chunk.heading, chunk.text, max(len(words), 1)))
            db.executemany("INSERT INTO postings (term, chunk, tf) VALUES (?, ?, ?)",
                           [(term, cursor.lastrowid, n) for term, n in Counter(words).items()])

    # -- keeping it current -----------------------------------------------------------------

    def refresh(self) -> dict[str, int]:
        """Bring the index up to date with what may be read. Returns what changed."""
        stats = {"added": 0, "updated": 0, "removed": 0, "read": 0}
        # One refresh per database at a time, so a scheduled one and one a search
        # asked for do not wait on each other's write lock until it times out.
        with _refresh_lock(self.path), contextlib.closing(self._connect()) as db, db:
            known = {rel: (version, mtime, size) for rel, version, mtime, size
                     in db.execute("SELECT rel, version, mtime, size FROM notes")}
            present: set[str] = set()
            for path in self.vault.note_paths():
                rel = self.vault.rel(path)
                present.add(rel)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                previous = known.get(rel)
                if previous and previous[1] == stat.st_mtime and previous[2] == stat.st_size:
                    continue
                try:
                    note = self.vault.read(path)
                except VaultError:
                    continue
                stats["read"] += 1
                if previous and previous[0] == note.version:
                    db.execute("UPDATE notes SET mtime = ?, size = ? WHERE rel = ?",
                               (stat.st_mtime, stat.st_size, rel))
                    continue
                self._drop(db, rel)
                self._add(db, note, stat.st_mtime, stat.st_size)
                stats["updated" if previous else "added"] += 1
            for rel in set(known) - present:
                self._drop(db, rel)
                db.execute("DELETE FROM notes WHERE rel = ?", (rel,))
                stats["removed"] += 1
        return stats

    # -- searching ---------------------------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> list[Result]:
        wanted = list(dict.fromkeys(_fold(w) for w in terms(query)))
        if not wanted:
            raise VaultError("Say what to look for — those words are too common to search on.")
        with contextlib.closing(self._connect()) as db:
            total, average = db.execute("SELECT COUNT(*), AVG(length) FROM chunks").fetchone()
            if not total:
                return []
            average = average or 1.0
            scores: dict[int, float] = {}
            matched: dict[int, set[str]] = {}
            for word in wanted:
                if len(word) >= PREFIX_MIN:
                    rows = db.execute(
                        "SELECT p.chunk, SUM(p.tf), c.length FROM postings p JOIN chunks c "
                        "ON c.id = p.chunk WHERE p.term >= ? AND p.term < ? GROUP BY p.chunk",
                        (word, word[:-1] + chr(ord(word[-1]) + 1))).fetchall()
                else:
                    rows = db.execute(
                        "SELECT p.chunk, p.tf, c.length FROM postings p JOIN chunks c "
                        "ON c.id = p.chunk WHERE p.term = ?", (word,)).fetchall()
                if not rows:
                    continue
                idf = math.log(1 + (total - len(rows) + 0.5) / (len(rows) + 0.5))
                for chunk_id, tf, length in rows:
                    weight = tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / average))
                    scores[chunk_id] = scores.get(chunk_id, 0.0) + idf * weight
                    matched.setdefault(chunk_id, set()).add(word)

            ranked = sorted(scores, key=lambda c: (-len(matched[c]), -scores[c], c))
            results: list[Result] = []
            per_note: dict[str, int] = {}
            for chunk_id in ranked:
                rel, heading, text = db.execute(
                    "SELECT rel, heading, text FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
                # Checked again here: the index may have been built under a wider grant.
                if not self.vault.may_read(self.vault.root / rel):
                    continue
                if per_note.get(rel, 0) >= MAX_SECTIONS_PER_NOTE:
                    continue
                per_note[rel] = per_note.get(rel, 0) + 1
                results.append(Result(rel, heading, _snippet(text, wanted), round(scores[chunk_id], 3),
                                      len(matched[chunk_id]) == len(wanted)))
                if len(results) >= limit:
                    break
        return results
