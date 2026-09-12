"""Filtering reasoning-trace blocks out of model output.

Qwen3-family models emit their chain of thought between `<think>` and
`</think>` before the actual reply. Akira must remove those spans everywhere,
not just in chat:

* The auditor's verdict grammar is two lines; a reasoning preamble around
  `VERDICT: PASS` parses as "unexpected text alongside the verdict" and would
  block every response -- the app would appear completely broken.
* Memory writes, consolidation, skills and the unlock demonstration all treat
  generated text as content. A stored think-block is reasoning frozen into a
  note.

The filter is a streaming state machine rather than a final-pass regex because
the UI shows tokens as they arrive: without suppression at the stream level the
user watches an entire reasoning monologue print and then vanish on redraw.
Tags can be split across stream chunks ("<thi" + "nk>"), so the filter carries
a small holdback buffer across feed() calls.

Pure and model-agnostic: text without think-tags passes through byte-identical,
so running it unconditionally on every backend is safe. Kept separate from
`llama_backend` so it can be unit-tested without loading a model.
"""

from __future__ import annotations

import re

OPEN_TAG = "<think>"
CLOSE_TAG = "</think>"

# Belt for non-streaming callers and as a final sweep: spans, including an
# unclosed trailing one (a think-block cut off by max_tokens must not surface
# as visible text just because the model never got to close it).
_SPAN_RE = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL)


def strip_think(text: str) -> str:
    """Remove every think-span from a complete string."""
    if OPEN_TAG not in text:
        return text
    return _SPAN_RE.sub("", text)


class ThinkFilter:
    """Incremental filter over a token stream.

    feed(piece) returns the displayable part of `piece` (possibly empty,
    possibly including text held back from earlier pieces). flush() returns
    whatever remains when the stream ends.
    """

    def __init__(self) -> None:
        self._inside = False
        self._carry = ""

    def feed(self, piece: str) -> str:
        buffer = self._carry + piece
        self._carry = ""
        out: list[str] = []

        while buffer:
            if self._inside:
                end = buffer.find(CLOSE_TAG)
                if end != -1:
                    buffer = buffer[end + len(CLOSE_TAG):]
                    self._inside = False
                    continue
                # Still inside; keep only a tail that could be a partial close
                # tag, discard the rest of the reasoning.
                self._carry = _partial_tail(buffer, CLOSE_TAG)
                return "".join(out)

            start = buffer.find(OPEN_TAG)
            if start != -1:
                out.append(buffer[:start])
                buffer = buffer[start + len(OPEN_TAG):]
                self._inside = True
                continue

            # Outside a span with no full open tag. Hold back any suffix that
            # could be the beginning of one arriving split across chunks.
            tail = _partial_tail(buffer, OPEN_TAG)
            emit_upto = len(buffer) - len(tail)
            out.append(buffer[:emit_upto])
            self._carry = tail
            return "".join(out)

        return "".join(out)

    def flush(self) -> str:
        """End of stream. A held partial tag that never completed is real text;
        reasoning inside an unclosed span is not."""
        carry, self._carry = self._carry, ""
        if self._inside:
            return ""
        return carry


def _partial_tail(text: str, tag: str) -> str:
    """The longest suffix of `text` that is a proper prefix of `tag`."""
    max_len = min(len(text), len(tag) - 1)
    for length in range(max_len, 0, -1):
        if text.endswith(tag[:length]):
            return text[-length:]
    return ""
