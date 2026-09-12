"""PDF text, with headings inferred from type size.

The reading itself is `akira.pdftext`, the standard-library parser written
for the original knowledge-lock import — used here as it stands rather than
copied. This module only turns its lines into the same blocks the Word reader
produces: the most common type size on the page is the body, and anything
clearly larger is a heading, ranked by size.
"""

from __future__ import annotations

from collections import Counter

from akira.pdftext import PdfError, extract_lines

from .ooxml import PackageError
from .word import Block

#: How much larger than body text a line must be to count as a heading.
HEADING_RATIO = 1.18

#: A "heading" longer than this is a short paragraph set large, not a title.
MAX_HEADING_CHARS = 120


def read(raw: bytes) -> list[Block]:
    try:
        lines = extract_lines(raw)
    except PdfError as exc:
        raise PackageError(f"This PDF could not be read: {exc}") from None

    sizes = Counter(round(line.size, 1) for line in lines if line.text.strip())
    if not sizes:
        return []
    body = sizes.most_common(1)[0][0]
    larger = sorted({size for size in sizes if size >= body * HEADING_RATIO}, reverse=True)[:3]
    rank = {size: level for level, size in enumerate(larger, 1)}

    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(Block("paragraph", "\n".join(paragraph)))
            paragraph.clear()

    for line in lines:
        text = line.text.strip()
        if not text:
            flush()
            continue
        level = rank.get(round(line.size, 1))
        if level and len(text) <= MAX_HEADING_CHARS:
            flush()
            blocks.append(Block("heading", text, level))
        else:
            paragraph.append(text)
    flush()
    return blocks
