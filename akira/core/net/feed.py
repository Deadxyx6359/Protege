"""A feed's entries, read from RSS or Atom (C6).

Only what a watch needs from each entry: an id to know it by, its title, its
link, its date and a short summary, all as plain text. A feed is someone else's
file, so it is read defensively:

- **No document type.** Feeds never need one, and a document type is how entity
  expansion arrives: a few hundred bytes that unpack to gigabytes. A feed that
  declares one is refused before anything in it is expanded.
- **Bounded.** The chokepoint already caps the size. Entries past
  `MAX_ENTRIES` are ignored, nesting deeper than `MAX_DEPTH` is refused, and
  titles and summaries are cut short.
- **Text, not markup.** Titles and summaries lose their HTML.

RSS 2.0, RSS 1.0 and Atom are read. Anything else, a web page included, is
refused with a reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.parsers import expat

from .page import readable

MAX_ENTRIES = 200
MAX_DEPTH = 64
MAX_TITLE_CHARS = 300
MAX_SUMMARY_CHARS = 500
MAX_ID_CHARS = 500
MAX_LINK_CHARS = 2000
MAX_FIELD_CHARS = 100_000

#: The outermost element of RSS 2.0, Atom and RSS 1.0.
ROOTS = frozenset({"rss", "feed", "RDF"})
ENTRIES = frozenset({"item", "entry"})

#: What each child of an entry is kept as.
_FIELDS = {
    "title": "title",
    "link": "link",
    "guid": "id",
    "id": "id",
    "pubDate": "published",
    "published": "published",
    "date": "published",  # Dublin Core, in RSS 1.0
    "updated": "updated",
    "description": "summary",
    "summary": "summary",
    "content": "content",
    "encoded": "content",  # content:encoded
}


class FeedError(ValueError):
    """Something that cannot be read as a feed, with a reason for the person."""


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    link: str = ""
    published: str = ""
    summary: str = ""


@dataclass(frozen=True)
class Feed:
    title: str
    entries: tuple[Entry, ...]


def _local(name: str) -> str:
    """An element or attribute name without its namespace."""
    return name.rsplit(" ", 1)[-1]


def _plain(text: str, limit: int) -> str:
    if "<" in text and ">" in text:
        text = readable(text)[1]
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


class _Reader:
    """Expat handlers that keep the feed's title and its entries' fields."""

    def __init__(self) -> None:
        self.root = ""
        self.title = ""
        self.entries: list[Entry] = []
        self._stack: list[str] = []
        self._entry: dict[str, str] | None = None
        self._entry_depth = 0
        self._field = ""
        self._field_depth = 0
        self._text: list[str] = []
        self._size = 0

    def start(self, name: str, attrs: dict) -> None:
        local = _local(name)
        parent = self._stack[-1] if self._stack else ""
        self._stack.append(local)
        depth = len(self._stack)
        if depth > MAX_DEPTH:
            raise FeedError("The feed is nested too deeply to be read.")
        if depth == 1:
            self.root = local
            if local not in ROOTS:
                raise FeedError(f"This is not a feed: it is <{local}>, not RSS or Atom. Watch "
                                "it as a page instead, or look for the site's feed address.")
            return
        if self._field:
            # Markup inside a field, such as Atom's XHTML content: its text is kept.
            return
        if local in ENTRIES and self._entry is None:
            self._entry, self._entry_depth = {}, depth
            about = next((value for key, value in attrs.items() if _local(key) == "about"), "")
            if about:
                self._entry["about"] = about
            return
        if self._entry is not None and depth == self._entry_depth + 1:
            field = _FIELDS.get(local, "")
            if field == "link" and attrs.get("href"):
                # Atom: the address is an attribute, and "alternate" is the page itself.
                if attrs.get("rel", "alternate") == "alternate" and "link" not in self._entry:
                    self._entry["link"] = attrs["href"]
                return
            if field and field not in self._entry:
                self._reading(field, depth)
            return
        if self._entry is None and local == "title" and parent in ("channel", "feed"):
            if not self.title:
                self._reading("feed title", depth)

    def _reading(self, field: str, depth: int) -> None:
        self._field, self._field_depth, self._text, self._size = field, depth, [], 0

    def data(self, text: str) -> None:
        if self._field and self._size < MAX_FIELD_CHARS:
            self._text.append(text)
            self._size += len(text)

    def end(self, name: str) -> None:
        depth = len(self._stack)
        if self._field and depth == self._field_depth:
            text = "".join(self._text)
            if self._field == "feed title":
                self.title = _plain(text, MAX_TITLE_CHARS)
            elif self._entry is not None:
                self._entry[self._field] = text
            self._field, self._text = "", []
        elif self._entry is not None and depth == self._entry_depth:
            self._finish()
        self._stack.pop()

    def _finish(self) -> None:
        raw, self._entry = self._entry or {}, None
        if len(self.entries) >= MAX_ENTRIES:
            return
        title = _plain(raw.get("title", ""), MAX_TITLE_CHARS)
        link = "".join(raw.get("link", "").split())[:MAX_LINK_CHARS]
        published = _plain(raw.get("published") or raw.get("updated") or "", 60)
        summary = _plain(raw.get("summary") or raw.get("content") or "", MAX_SUMMARY_CHARS)
        ident = " ".join((raw.get("id") or raw.get("about") or link).split())
        if not ident and title:
            # Nothing else to know it by. A new date makes it a new entry, which
            # is what a feed republishing an undated item would mean anyway.
            ident = f"{title} | {published}"
        if ident:
            self.entries.append(Entry(ident[:MAX_ID_CHARS], title, link, published, summary))


WEB_PAGE = ("This is a web page, not a feed. Watch it as a page instead, or look for the "
            "site's feed address.")


def _looks_like_html(data: bytes) -> bool:
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<!doctype html", b"<html"))


def parse_feed(data: bytes) -> Feed:
    """The feed in \a data. Raises `FeedError` with a reason for the person."""
    reader = _Reader()
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.buffer_text = True

    def doctype(name, *_args) -> None:
        if str(name).lower() == "html":
            raise FeedError(WEB_PAGE)
        refuse()

    def refuse(*_args) -> None:
        raise FeedError("The feed declares a document type, which feeds never need, so it "
                        "was not read.")

    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = refuse
    parser.StartElementHandler = reader.start
    parser.EndElementHandler = reader.end
    parser.CharacterDataHandler = reader.data
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        if _looks_like_html(data):
            raise FeedError(WEB_PAGE) from None
        raise FeedError(f"This could not be read as a feed: {expat.ErrorString(exc.code)}, "
                        f"line {exc.lineno}.") from None
    if not reader.root:
        raise FeedError("The feed was empty.")
    return Feed(reader.title, tuple(reader.entries))
