"""The second brain: an Obsidian vault Akira keeps, so the person never has to.

B2 is the vault itself — reading, linking, searching, and writing that is
automatic but always recoverable. B3 is the index that ranks it by section.
Retrieval (B4) and memory distillation (B5) build on both.
"""

from . import markdown
from .index import Index, Result
from .markdown import Link
from .vault import ConflictError, Hit, Note, Vault, VaultError, find_root, moment_format, version_of

__all__ = ["ConflictError", "Hit", "Index", "Link", "Note", "Result", "Vault", "VaultError",
           "find_root", "markdown", "moment_format", "version_of"]
