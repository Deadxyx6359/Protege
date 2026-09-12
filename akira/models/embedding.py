"""A local embedding model, on the processor (B4).

Turns a passage, or a question, into a vector, so the index can rank by meaning
as well as by words. `import llama_cpp` sits at module scope for the reason it
does in `llama_backend`: `verify_offline.py` follows only module-level imports,
and lists this module so it does.

On the processor, deliberately: the graphics card is the chat model's, and a
model this size is quick enough without it. Measured on this machine,
nomic-embed-text-v1.5 at Q8_0 loads in a quarter of a second and takes about
25 ms a passage. Loaded on first use, and used by one caller at a time.

nomic-embed-text is told which side of a search a text is on, with the
prefixes it was trained on. Any other model is given the text as it is.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import llama_cpp

#: nomic-embed-text's task prefixes: (a question, a passage).
NOMIC_PREFIXES = ("search_query: ", "search_document: ")

#: The most of one text that is embedded. Longer is cut, never refused.
MAX_CHARS = 4000

#: Room for the longest text, in tokens. llama.cpp embeds a text in one batch.
CONTEXT = 2048


class LlamaEmbedder:
    """An embedding model in a GGUF file, loaded when first asked for a vector."""

    def __init__(self, path: Path, *, threads: int = 0) -> None:
        self.path = Path(path)
        self.model = self.path.name
        self._threads = threads
        self._llama: Any = None
        self._lock = threading.Lock()
        self._prefixes = NOMIC_PREFIXES if "nomic" in self.model.lower() else ("", "")

    def _load(self) -> Any:
        options: dict[str, Any] = {
            "model_path": str(self.path), "embedding": True, "n_gpu_layers": 0,
            "n_ctx": CONTEXT, "n_batch": CONTEXT, "n_ubatch": CONTEXT,
            # llama.cpp's own chatter would otherwise land on a console nobody sees.
            "verbose": False,
        }
        if self._threads > 0:
            options["n_threads"] = self._threads
        return llama_cpp.Llama(**options)

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        """One unit-length vector per text. \a query marks the question side of a search."""
        if not texts:
            return []
        prefix = self._prefixes[0 if query else 1]
        with self._lock:
            if self._llama is None:
                self._llama = self._load()
            vectors = self._llama.embed([prefix + text[:MAX_CHARS] for text in texts],
                                        normalize=True)
        return [list(vector) for vector in vectors]
