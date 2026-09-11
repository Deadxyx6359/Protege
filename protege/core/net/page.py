"""A web page as text a model can read (C1).

Scripts, styles and everything else that is not reading matter are dropped.
Headings keep their level as `#` marks, list items become `- ` lines, table
cells are separated by `|`, and paragraphs stay paragraphs. Links are not kept:
an address in a page is the page's say-so, and following one is a separate fetch
that the grants decide on.

`page_text` is what `fetch_page` and the page watcher both read a response
with, so what an agent reads and what a watch compares are the same text.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from protege.core.documents import PackageError, text_of

from .client import Response, redact

SKIPPED = frozenset({"script", "style", "noscript", "template", "svg", "canvas", "iframe",
                     "object", "head"})
BLOCKS = frozenset({"p", "div", "section", "article", "main", "header", "footer", "nav",
                    "aside", "ul", "ol", "table", "tr", "blockquote", "pre", "figure",
                    "figcaption", "dl", "dt", "dd", "form", "fieldset", "address", "br", "hr"})
HEADINGS = {f"h{level}": level for level in range(1, 7)}
CELLS = frozenset({"td", "th"})

#: Media types read as they are.
TEXT_TYPES = ("text/", "application/json", "application/xml")


class PageError(ValueError):
    """A page that cannot be read as text, with a reason for the person."""


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in SKIPPED:
            self._skip += 1
        elif self._skip:
            return
        elif tag in HEADINGS:
            self.parts.append("\n\n" + "#" * HEADINGS[tag] + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in CELLS:
            self.parts.append(" | ")
        elif tag in BLOCKS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs) -> None:
        if tag not in SKIPPED:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in SKIPPED:
            self._skip = max(0, self._skip - 1)
        elif not self._skip and (tag in HEADINGS or tag in BLOCKS):
            self.parts.append("\n")

    def handle_data(self, data) -> None:
        if self._in_title:
            self.title.append(data)
        elif not self._skip:
            self.parts.append(data)


def readable(html: str) -> tuple[str, str]:
    """(title, text) of an HTML page."""
    reader = _Reader()
    try:
        reader.feed(html)
        reader.close()
    except (AssertionError, ValueError):
        # html.parser is forgiving; a page it still chokes on keeps what was read.
        pass
    title = " ".join("".join(reader.title).split())
    lines = [" ".join(line.split()) for line in "".join(reader.parts).splitlines()]
    return title, re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def page_text(response: Response) -> tuple[str, str]:
    """(title, text) of a fetched page: HTML read as above, a PDF's text, or text as it is.

    Raises `PageError` for anything else, such as a picture or an archive.
    """
    kind = response.media_type
    if kind in ("text/html", "application/xhtml+xml"):
        return readable(response.text())
    if kind == "application/pdf":
        try:
            return "", text_of(response.body, "page.pdf")
        except PackageError as exc:
            raise PageError(f"The PDF could not be read: {exc}") from None
    if not kind or kind.startswith(TEXT_TYPES) or kind.endswith(("+xml", "+json")):
        return "", response.text()
    raise PageError(f"{redact(response.url)} is {kind}, which cannot be read as text.")
