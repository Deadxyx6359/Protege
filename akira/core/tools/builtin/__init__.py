"""The tools Akira ships with.

Each module exposes `ALL`, a tuple of its tools. `default_registry()` in
`akira.core.tools` registers them explicitly.
"""

from . import (accounts, browsing, coding, coursework, drawing, files, knowledge, maths,
               money, notes, office, pictures, screen, texts, web)

MODULES = (files, coding, office, notes, knowledge, web, browsing, screen, accounts,
           coursework, money, texts, drawing, pictures, maths)

__all__ = ["accounts", "browsing", "coding", "coursework", "drawing", "money", "files",
           "knowledge", "maths", "notes", "office", "pictures", "screen", "texts", "web", "MODULES"]
