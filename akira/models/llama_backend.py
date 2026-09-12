"""llama.cpp backend, via `llama-cpp-python`.

llama.cpp is bound directly as a shared library through ctypes. There is no
server, no port, and no socket anywhere in this path -- which is precisely why
the brief rules out Ollama and LM Studio. Those are HTTP servers; using one
would mean the application's core loop depended on a network stack, and no
amount of binding to 127.0.0.1 makes that as strong as never opening a socket.

`import llama_cpp` sits at module scope on purpose, even though it means this
module cannot be imported without the library installed. A lazy import inside a
function would hide the entire `llama_cpp` subtree from `verify_offline.py`,
which only follows module-level imports -- and `llama_cpp` is exactly the
dependency most worth following, since it ships an unused FastAPI server and a
HuggingFace downloader. This module is therefore listed explicitly in
`verify_offline.ENTRY_POINTS`, and `registry.py` imports it lazily so a missing
library degrades to a clear message rather than a crash at startup.

Two things in `llama_cpp` that must never be called:

* `llama_cpp.server`      -- a FastAPI/uvicorn HTTP server.
* `Llama.from_pretrained` -- downloads weights from HuggingFace Hub.

Models are constructed from local filesystem paths only.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Sequence

import llama_cpp

from .base import (
    ChatMessage,
    GenerationResult,
    GenerationTimeout,
    ModelBackend,
    ModelSpec,
    ModelUnavailable,
)
from .think_filter import ThinkFilter, strip_think


class LlamaBackend(ModelBackend):
    """A single llama.cpp context.

    Loading happens in the constructor rather than lazily, so that "the model
    is unavailable" surfaces at a point where the UI can report it, instead of
    midway through the first response.
    """

    def __init__(self, spec: ModelSpec) -> None:
        super().__init__(spec)
        self._llama: Any | None = None
        self._closed = False
        self._load()

    def _load(self) -> None:
        path = spec_path(self.spec)
        kwargs: dict[str, Any] = {
            "model_path": path,
            "n_ctx": self.spec.n_ctx,
            "n_gpu_layers": self.spec.n_gpu_layers,
            # llama.cpp's own progress and timing chatter would otherwise land
            # on stdout behind a GUI with no console.
            "verbose": False,
        }
        if self.spec.n_threads > 0:
            kwargs["n_threads"] = self.spec.n_threads
        if self.spec.seed is not None and self.spec.seed >= 0:
            kwargs["seed"] = self.spec.seed

        try:
            self._llama = llama_cpp.Llama(**kwargs)
        except TypeError:
            # `seed` moved between constructor and sampler across llama-cpp-python
            # releases. Retry without it rather than pinning users to one version.
            kwargs.pop("seed", None)
            try:
                self._llama = llama_cpp.Llama(**kwargs)
            except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the user
                raise ModelUnavailable(f"could not load {path}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable(f"could not load {path}: {exc}") from exc

    @property
    def _is_qwen3(self) -> bool:
        """Whether the loaded file is a Qwen3-family model, judged by filename.

        Filename rather than GGUF metadata because the metadata's
        `general.name` is set by whoever ran the conversion and is frequently
        blank or wrong in community quants, while nobody renames a model file
        to hide its family.
        """
        import os

        return "qwen3" in os.path.basename(self.spec.path).lower()

    @property
    def is_loaded(self) -> bool:
        return self._llama is not None and not self._closed

    @property
    def n_ctx(self) -> int:
        if self._llama is None:
            return self.spec.n_ctx
        try:
            return int(self._llama.n_ctx())
        except Exception:  # noqa: BLE001
            return self.spec.n_ctx

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop: Sequence[str] = (),
        deadline: float | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> GenerationResult:
        with self._lock:
            if not self.is_loaded:
                raise ModelUnavailable(f"{self.label} is not loaded")
            assert self._llama is not None

            started = time.monotonic()
            payload = [m.to_dict() for m in messages]

            # Qwen3's chat template thinks out loud unless the reply is opened
            # with a soft switch in the final user turn. Thinking would burn the
            # auditor's entire 64-token budget on reasoning and then time out,
            # so it is disabled at the source; the ThinkFilter below removes the
            # empty <think></think> pair the template still emits. Dialect
            # handling like this belongs in the backend -- nothing above this
            # layer knows which model family is loaded.
            if self._is_qwen3 and payload and payload[-1]["role"] == "user":
                payload[-1] = {
                    "role": "user",
                    "content": payload[-1]["content"] + "\n/no_think",
                }

            # Always stream internally, even when the caller wants a single
            # string. Streaming is what makes the deadline enforceable: we can
            # check the clock between tokens and abandon the generator. The
            # alternative -- a blocking call plus a watchdog thread -- cannot
            # actually stop llama.cpp, so a timed-out auditor would keep a core
            # busy for the rest of the turn.
            stream = self._llama.create_chat_completion(
                messages=payload,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stop=list(stop) or None,
                stream=True,
            )

            chunks: list[str] = []
            finish_reason = "stop"
            timed_out = False
            # Reasoning spans are filtered at the stream level, not only at the
            # end: the UI displays tokens as they arrive, and without this the
            # user watches a whole thinking monologue print and then vanish.
            think = ThinkFilter()
            try:
                for chunk in stream:
                    if deadline is not None and time.monotonic() > deadline:
                        timed_out = True
                        break
                    choice = (chunk.get("choices") or [{}])[0]
                    piece = (choice.get("delta") or {}).get("content") or ""
                    if piece:
                        visible = think.feed(piece)
                        if visible:
                            chunks.append(visible)
                            if on_token:
                                on_token(visible)
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                tail = think.flush()
                if tail:
                    chunks.append(tail)
                    if on_token:
                        on_token(tail)
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

            if timed_out:
                # Raise rather than returning the partial text. A truncated
                # auditor verdict that happens to start with "VERDICT: PASS"
                # would otherwise be parsed as a pass.
                raise GenerationTimeout(
                    f"{self.label} exceeded its deadline after "
                    f"{time.monotonic() - started:.1f}s ({len(chunks)} chunks received)"
                )

            # Belt over the streaming filter: a span that opened but never
            # closed (cut off by max_tokens) must not surface as text.
            text = strip_think("".join(chunks))
            return GenerationResult(
                text=text,
                # Streaming responses carry no usage block. Summing the message
                # contents with the real tokenizer undercounts by the chat
                # template's own tokens (a few dozen), which is why the context
                # budget keeps a reserve rather than filling to the brim.
                prompt_tokens=sum(self.count_tokens(m.content) for m in messages),
                completion_tokens=self.count_tokens(text),
                stop_reason=finish_reason or "stop",
                duration_s=time.monotonic() - started,
            )

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if not self.is_loaded:
            raise ModelUnavailable(f"{self.label} is not loaded")
        assert self._llama is not None
        try:
            return len(self._llama.tokenize(text.encode("utf-8"), add_bos=False, special=False))
        except TypeError:
            return len(self._llama.tokenize(text.encode("utf-8"), add_bos=False))

    def close(self) -> None:
        with self._lock:
            if self._llama is not None:
                closer = getattr(self._llama, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:  # noqa: BLE001 - teardown must not raise
                        pass
                self._llama = None
            self._closed = True


def spec_path(spec: ModelSpec) -> str:
    """Validate a model path before handing it to llama.cpp.

    llama.cpp's own error for a missing file is terse and easily mistaken for a
    corrupt-model error, which sends people re-downloading five gigabytes for
    what is actually a typo.
    """
    if not spec.path:
        raise ModelUnavailable(
            f"no model path configured for {spec.role.value.upper()}. "
            "Set it in Settings -> Models."
        )
    path = os.path.abspath(os.path.expanduser(spec.path))
    if not os.path.exists(path):
        raise ModelUnavailable(f"{spec.role.value.upper()} model file not found: {path}")
    if not os.path.isfile(path):
        raise ModelUnavailable(f"{spec.role.value.upper()} model path is not a file: {path}")
    return path


def library_available() -> bool:
    """Always True here -- reaching this module means the import succeeded.

    Kept so callers can ask the question without a bare try/except ImportError
    around an import statement, which reads as though the failure were routine.
    """
    return True
