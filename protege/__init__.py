"""Protege -- a local, offline AI assistant gated by a knowledge lock system.

This module is deliberately import-light. `verify_offline.py` treats it as an
entry point for the reachability scan, and pulling the UI or the model backend
in here would make the graph walk describe an import that startup does not
actually perform. Import submodules directly.
"""

__version__ = "0.1.0"

# The fixed string MAIN is instructed to emit, and the string the UI renders for
# any blocked response regardless of which layer blocked it. Defined here rather
# than in the lock package so that the UI can render a block without importing
# the lock machinery.
LOCKED_MARKER = "[LOCKED: {topic}]"
