"""The tools that ship with Protégé.

Each module exports an `ALL` tuple. `protege.core.tools.default_registry`
assembles them; nothing here registers itself on import, so a test can build a
registry holding exactly the tools it means to exercise.
"""

from . import coding, files

MODULES = (files, coding)

__all__ = ["coding", "files", "MODULES"]
