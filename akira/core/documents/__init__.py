"""Word, Excel, PowerPoint and PDF — read, and edited without losing anything.

Standard library only. See `ooxml` for why edits are surgical rather than a
parse and a rewrite, and why that is the difference between an edited document
and a damaged one.
"""

from pathlib import Path

from . import pdf, sheets, slides, word
from .ooxml import Package, PackageError, write_atomically

KINDS = {".docx": "word", ".docm": "word", ".dotx": "word",
         ".xlsx": "sheets", ".xlsm": "sheets",
         ".pptx": "slides", ".pptm": "slides",
         ".pdf": "pdf"}
"""The formats read here, by extension."""


def text_of(raw: bytes, name: str) -> str:
    """A document as text: headings, bullets, tables, sheets, slides and speaker notes.

    One place, so what `read_document` shows and what a search finds are the
    same text.
    """
    kind = KINDS.get(Path(name).suffix.lower())
    if kind is None:
        raise PackageError(f"{name} is not a Word, Excel, PowerPoint or PDF file.")
    if kind == "pdf":
        return word.render(pdf.read(raw))
    package = Package(raw, name)
    if kind == "word":
        return word.render(word.read(package))
    if kind == "sheets":
        return sheets.render(sheets.read(package))
    return slides.render(slides.read(package))


__all__ = ["KINDS", "Package", "PackageError", "pdf", "sheets", "slides", "text_of", "word",
           "write_atomically"]
