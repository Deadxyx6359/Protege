"""Model abstraction layer.

Nothing above this package may import `llama_cpp` or know it exists. The base
model is a replaceable component; assume it will be replaced.
"""

from .base import (
    ChatMessage,
    GenerationResult,
    GenerationTimeout,
    ModelBackend,
    ModelError,
    ModelSpec,
    ModelUnavailable,
    Role,
    deadline_from,
)
from .registry import ModelManager, ModelStatus

__all__ = [
    "ChatMessage",
    "GenerationResult",
    "GenerationTimeout",
    "ModelBackend",
    "ModelError",
    "ModelManager",
    "ModelSpec",
    "ModelStatus",
    "ModelUnavailable",
    "Role",
    "deadline_from",
]
