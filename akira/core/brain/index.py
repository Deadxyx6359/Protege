"""A search index: ranked, incremental, and kept on disk.

Searching by reading every note on every query is fine for a few hundred notes
and not for a few thousand, and it cannot rank: a note that mentions a word
once scores like one that is about it. The index fixes both, and stays small
enough to understand in one sitting.

**What it reads is a corpus**: the vault, a folder of documents, the saved
conversations (`corpora.py`). Anything with a root, the paths under it, a way to
read one, and a `may_read` check will do.

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

**Held to the grant.** Only notes the corpus may read are indexed, notes that
are no longer readable are dropped, and results are filtered again when the
query runs. The index is a cache of what the permission already allowed, never
a way around it. And because it is a copy, `sweep` drops what the grants stop
covering as soon as they change, rather than at the next search, and drops it
from the file's bytes, not only from its tables.

The database lives in Akira's configuration folder, one per corpus, and
records what it holds. It is disposable: a damaged one is deleted and rebuilt
rather than trusted.
"""

from __future__ import annotations

import contextlib
import hashlib
import math
import re
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

from akira.core.config import config_dir

from .vault import VaultError

SCHEMA_VERSION = 2
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200
MAX_CHUNKS_PER_NOTE = 400
MAX_SECTIONS_PER_NOTE = 2
PREFIX_MIN = 4
K1, B = 1.2, 0.75

#: Plain files in a documents folder. They are opened under `files.read`, as
#: `search_documents` opens them, and everything else there under `docs.read`.
PLAIN_SUFFIXES = (".md", ".txt")

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

    text: str = ""
    """The whole section, for a model to read."""

    @property
    def section(self) -> str:
        """The heading inside the note, without its title; empty for the note as a whole."""
        return self.heading.split(" › ", 1)[1] if " › " in self.heading else ""


class Corpus(Protocol):
    """What the index reads.

    `read` returns something with `rel`, `title`, `body` and `version`, and may
    carry `tags` and ready-made `sections`; it raises `VaultError` for anything
    it will not read, which the index skips. An optional `kind` names the
    corpus, keeping indexes of the same folder as a vault and as documents apart.
    """

    root: Path

    def note_paths(self) -> Iterable[Path]: ...
    def rel(self, path: Path) -> str: ...
    def read(self, path: Path): ...
    def may_read(self, path: Path) -> bool: ...


def windows(text: str) -> list[str]:
    """\a text in pieces of at most CHUNK_CHARS, overlapping, broken at spaces."""
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
    return [Chunk(name, window) for name, text in sections for window in (windows(text) or [""])]


def _snippet(text: str, words: list[str], width: int = 160) -> str:
    flat = " ".join(text.split())
    lowered = flat.lower()
    positions = [lowered.find(w) for w in words if lowered.find(w) >= 0]
    if not positions:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, min(positions) - width // 4)
    piece = flat[start:start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(flat) else "")


def _schema(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA user_version").fetchone()[0] not in (0, SCHEMA_VERSION):
        for table in ("postings", "chunks", "notes", "meta"):
            db.execute(f"DROP TABLE IF EXISTS {table}")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS notes (rel TEXT PRIMARY KEY, version TEXT, mtime REAL, size INTEGER);
        CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, rel TEXT,
                                           heading TEXT, text TEXT, length INTEGER);
        CREATE INDEX IF NOT EXISTS chunks_rel ON chunks(rel);
        CREATE TABLE IF NOT EXISTS postings (term TEXT, chunk INTEGER, tf INTEGER);
        CREATE INDEX IF NOT EXISTS postings_term ON postings(term);
        CREATE INDEX IF NOT EXISTS postings_chunk ON postings(chunk);
    """)
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _drop(db: sqlite3.Connection, rel: str) -> None:
    db.execute("DELETE FROM postings WHERE chunk IN (SELECT id FROM chunks WHERE rel = ?)", (rel,))
    db.execute("DELETE FROM chunks WHERE rel = ?", (rel,))
    db.execute("DELETE FROM notes WHERE rel = ?", (rel,))


class Index:
    """The search index for one corpus."""

    def __init__(self, corpus: Corpus, *, path: Path | None = None) -> None:
        self.corpus = corpus
        self.kind = getattr(corpus, "kind", "vault")
        key = hashlib.sha256(f"{self.kind}:{corpus.root}".lower().encode("utf-8")).hexdigest()[:16]
        self.path = path if path is not None else config_dir() / "index" / f"{self.kind}-{key}.sqlite"

    # -- storage -----------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            _schema(db)
            return db
        except sqlite3.DatabaseError:
            # A damaged cache is thrown away and rebuilt, never trusted.
            db.close()
            with contextlib.suppress(OSError):
                self.path.unlink()
            db = sqlite3.connect(self.path, timeout=10)
            _schema(db)
            return db

    @staticmethod
    def _add(db: sqlite3.Connection, note, mtime: float, size: int) -> None:
        db.execute("INSERT OR REPLACE INTO notes (rel, version, mtime, size) VALUES (?, ?, ?, ?)",
                   (note.rel, note.version, mtime, size))
        sections = list(getattr(note, "sections", ()) or chunks(note.title, note.body))
        tags = getattr(note, "tags", ())
        for number, chunk in enumerate(sections[:MAX_CHUNKS_PER_NOTE]):
            text = chunk.heading + "\n" + chunk.text
            if number == 0 and tags:
                # Tags describe the note, so they are counted once, not per section.
                text += "\n" + " ".join(tags)
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
            # What it holds, so a sweep can tell without opening the files it came from.
            db.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                           [("kind", self.kind), ("root", str(self.corpus.root))])
            known = {rel: (version, mtime, size) for rel, version, mtime, size
                     in db.execute("SELECT rel, version, mtime, size FROM notes")}
            present: set[str] = set()
            for path in self.corpus.note_paths():
                rel = self.corpus.rel(path)
                present.add(rel)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                previous = known.get(rel)
                if previous and previous[1] == stat.st_mtime and previous[2] == stat.st_size:
                    continue
                try:
                    note = self.corpus.read(path)
                except VaultError:
                    continue
                stats["read"] += 1
                if previous and previous[0] == note.version:
                    db.execute("UPDATE notes SET mtime = ?, size = ? WHERE rel = ?",
                               (stat.st_mtime, stat.st_size, rel))
                    continue
                _drop(db, rel)
                self._add(db, note, stat.st_mtime, stat.st_size)
                stats["updated" if previous else "added"] += 1
            for rel in set(known) - present:
                _drop(db, rel)
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
                if not self.corpus.may_read(self.corpus.root / rel):
                    continue
                if per_note.get(rel, 0) >= MAX_SECTIONS_PER_NOTE:
                    continue
                per_note[rel] = per_note.get(rel, 0) + 1
                results.append(Result(rel, heading, _snippet(text, wanted), round(scores[chunk_id], 3),
                                      len(matched[chunk_id]) == len(wanted), text))
                if len(results) >= limit:
                    break
        return results


# -- keeping the copies honest ---------------------------------------------------------------


@dataclass
class Sweep:
    removed: int = 0
    """Databases deleted: nothing in them was still covered, or they could not
    say what they held."""

    emptied: int = 0
    """Databases that should have gone but were held open, so were cleared in
    place instead. The next sweep deletes the empty file."""

    dropped: int = 0
    """Notes dropped from databases that were kept."""

    failed: list[str] = field(default_factory=list)
    """Databases that could be neither deleted nor cleared. Tried again next time."""


def needs(kind: str, root: str, rel: str) -> tuple[str, str | None]:
    """The capability, and scope, a note in an index of \a kind is opened under."""
    if kind == "conversations":
        return "memory.read", None
    path = str(Path(root) / rel)
    if kind == "documents":
        return ("files.read" if Path(rel).suffix.lower() in PLAIN_SUFFIXES else "docs.read"), path
    return "vault.read", path


def anywhere(*policies) -> Callable[[str, str | None], bool]:
    """Allowed under any of \a policies: the global grants, or any project's.

    A sweep uses this rather than whichever project is open, so opening another
    project does not throw away an index that project will want back.
    """
    return lambda capability, scope: any(bool(p.allows(capability, scope)) for p in policies)


def _sweep_one(path: Path, allows: Callable[[str, str | None], bool], report: Sweep) -> bool:
    """Drop what \a allows no longer covers from one database. False to delete it."""
    try:
        with contextlib.closing(sqlite3.connect(path, timeout=2)) as db:
            # Deleted rows otherwise stay readable in the file's free pages.
            db.execute("PRAGMA secure_delete = ON")
            with db:
                meta = dict(db.execute("SELECT key, value FROM meta"))
                kind, root = meta.get("kind", ""), meta.get("root", "")
                if not kind or not root:
                    return False
                rels = [rel for (rel,) in db.execute("SELECT rel FROM notes")]
                gone = [rel for rel in rels if not allows(*needs(kind, root, rel))]
                for rel in gone:
                    _drop(db, rel)
            keep = len(gone) < len(rels)
            if keep:
                report.dropped += len(gone)
            return keep
    except sqlite3.DatabaseError:
        # An older index, or a damaged one: it cannot say what it holds.
        return False


def _delete(path: Path) -> bool:
    for leftover in (path.with_name(path.name + "-journal"), path):
        with contextlib.suppress(FileNotFoundError, PermissionError):
            leftover.unlink()
    return not path.exists()


def _empty(path: Path) -> bool:
    """Clear a database something still holds open, since it cannot be deleted."""
    try:
        with contextlib.closing(sqlite3.connect(path, timeout=2)) as db:
            db.execute("PRAGMA secure_delete = ON")
            tables = [name for (name,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
            with db:
                for name in tables:
                    db.execute('DROP TABLE IF EXISTS "{}"'.format(name.replace('"', '""')))
            with contextlib.suppress(sqlite3.OperationalError):
                db.execute("VACUUM")
        return True
    except sqlite3.DatabaseError:
        return False


def sweep(allows: Callable[[str, str | None], bool], directory: Path | None = None) -> Sweep:
    """Drop what current grants no longer cover from every index on disk.

    Reads only the index databases, never the files they were built from. A
    database left with nothing, or one that cannot say what it holds, is
    deleted: it is a cache, and one nobody can account for is not kept. One that
    something still holds open is cleared in place instead.
    """
    folder = directory if directory is not None else config_dir() / "index"
    report = Sweep()
    if not folder.is_dir():
        return report
    for path in sorted(folder.glob("*.sqlite")):
        with _refresh_lock(path):
            if _sweep_one(path, allows, report):
                continue
            if _delete(path):
                report.removed += 1
            elif _empty(path):
                report.emptied += 1
            else:
                report.failed.append(path.name)
    return report
