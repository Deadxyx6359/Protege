"""The tools Protégé ships with.

Each module exposes `ALL`, a tuple of its tools. `default_registry()` in
`protege.core.tools` registers them explicitly.
"""

from . import coding, files, knowledge, notes, office

MODULES = (files, coding, office, notes, knowledge)

__all__ = ["coding", "files", "knowledge", "notes", "office", "MODULES"]
