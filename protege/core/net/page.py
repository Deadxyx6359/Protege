"""A web page as text a model can read (C1).

Scripts, styles and everything else that is not reading matter are dropped.
Headings keep their level as `#` marks, list items become `- ` lines, table
cells are separated by `|`, and paragraphs stay paragraphs. Links are not kept:
an address in a page is the page's say-so, and following one is a separate fetch
that the grants decide on.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

SKIPPED = frozenset({"script", "style", "noscript", "template", "svg", "canvas", "iframe",
                     "object", "head"})
BLOCKS = frozenset({"p", "div", "section", "article", "main", "header", "footer", "nav",
                    "aside", "ul", "ol", "table", "tr", "blockquote", "pre", "figure",
                    "figcaption", "dl", "dt", "dd", "form", "fieldset", "address", "br", "hr"})
HEADINGS = {f"h{level}": level for level in range(1, 7)}
CELLS = frozenset({"td", "th"})


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
