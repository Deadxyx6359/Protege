"""Meaning as well as words: what the index needs from an embedding model (B4).

The index ranks by words (BM25). Given an embedder, it also ranks by meaning and
merges the two lists by reciprocal rank, the fusion retrieval already uses
across sources. That is what finds the note about the allotment when the
question says "garden".

The model is local (`akira.models.embedding`) and optional: with none in
`models/embed/`, search is words only, exactly as before. The application
switches it on at start with `use`. Importing this module never loads a model,
so no test or tool loads one by being imported.
"""

from __future__ import annotations

import threading
from typing import Protocol

from akira.core.config import EMBED_DIR, looks_like_gguf


class Embedder(Protocol):
    model: str
    """Stored with every vector, so vectors from different models are never compared."""

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        """One unit-length vector per text. \a query marks the question side of a search."""
        ...


_current: Embedder | None = None
_lock = threading.Lock()


def use(embedder: Embedder | None) -> None:
    """Rank by meaning with \a embedder from now on, or by words only with None."""
    global _current
    with _lock:
        _current = embedder


def current() -> Embedder | None:
    with _lock:
        return _current


def local() -> Embedder | None:
    """The embedding model in `models/embed/`, not yet loaded, or None if there is none."""
    found = sorted(p for p in EMBED_DIR.glob("*.gguf") if looks_like_gguf(p)) \
        if EMBED_DIR.is_dir() else []
    if not found:
        return None
    try:
        from akira.models.embedding import LlamaEmbedder
    except ImportError:
        return None
    return LlamaEmbedder(found[0])
