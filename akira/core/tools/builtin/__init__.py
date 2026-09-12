"""The tools Akira ships with.

Each module exposes `ALL`, a tuple of its tools. `default_registry()` in
`akira.core.tools` registers them explicitly.
"""

from . import coding, files, knowledge, notes, office, screen, web

MODULES = (files, coding, office, notes, knowledge, web, screen)

__all__ = ["coding", "files", "knowledge", "notes", "office", "screen", "web", "MODULES"]
