"""The tools Akira ships with.

Each module exposes `ALL`, a tuple of its tools. `default_registry()` in
`akira.core.tools` registers them explicitly.
"""

from . import (accounts, browsing, coding, coursework, files, knowledge, notes, office,
               screen, web)

MODULES = (files, coding, office, notes, knowledge, web, browsing, screen, accounts,
           coursework)

__all__ = ["accounts", "browsing", "coding", "coursework", "files", "knowledge", "notes", "office", "screen",
           "web", "MODULES"]
