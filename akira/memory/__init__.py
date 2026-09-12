"""Three-tier memory: live session scratch, pending consolidation, durable notes.

Every write goes through the lock gate before it reaches disk. See
`live.LiveMemory.write` for why that is not optional.
"""

from .consolidate import ConsolidationResult, Consolidator, ProposedNote
from .live import (
    REMEMBER_TOOL_DESCRIPTION,
    LiveMemory,
    MemoryEntry,
    MemoryWriteResult,
    new_session_id,
    parse_remember_calls,
)

__all__ = [
    "REMEMBER_TOOL_DESCRIPTION",
    "ConsolidationResult",
    "Consolidator",
    "LiveMemory",
    "MemoryEntry",
    "MemoryWriteResult",
    "ProposedNote",
    "new_session_id",
    "parse_remember_calls",
]
