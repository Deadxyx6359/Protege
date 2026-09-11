"""The second brain: an Obsidian vault Protégé keeps, so the person never has to.

B2 is the vault itself — reading, linking, searching, and writing that is
automatic but always recoverable. Indexing (B3), retrieval (B4) and memory
distillation (B5) build on it.
"""

from . import markdown
from .markdown import Link
from .vault import ConflictError, Hit, Note, Vault, VaultError, find_root, moment_format, version_of

__all__ = ["ConflictError", "Hit", "Link", "Note", "Vault", "VaultError", "find_root",
           "markdown", "moment_format", "version_of"]
