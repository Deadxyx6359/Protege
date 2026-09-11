"""Word, Excel, PowerPoint and PDF — read, and edited without losing anything.

Standard library only. See `ooxml` for why edits are surgical rather than a
parse and a rewrite, and why that is the difference between an edited document
and a damaged one.
"""

from . import pdf, sheets, slides, word
from .ooxml import Package, PackageError, write_atomically

__all__ = ["Package", "PackageError", "write_atomically", "pdf", "sheets", "slides", "word"]
