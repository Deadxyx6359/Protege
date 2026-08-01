"""Layer 3 -- scoped retrieval.

RAG over the vault, returning chunks only from notes whose every topic is
unlocked. Locked-topic notes are invisible to retrieval, and that includes
memory notes: if MAIN once wrote locked content into the vault, retrieval would
later hand it back and the gate would be bypassed by the model's own notes.

**Scoping happens at index-build time, not at query time.** Locked chunks are
never inserted into the index at all, so no ranked list exists that contains
one. Filtering after scoring is the more obvious design and the more fragile
one -- it leaves a correct, ordered list of locked material sitting in memory,
one `off-by-one` or one forgotten filter away from the prompt.

**Why BM25 and not embeddings.** Every practical local embedding model arrives
by download on first use, which the hard constraints forbid outright. Reusing
MAIN's GGUF for embeddings would mean a second context or repeated
re-prompting, on a box where system RAM is already the binding constraint. BM25
is lexical, deterministic, dependency-free, and explainable -- and for a vault
of notes the user wrote themselves, in their own vocabulary, lexical overlap is
a genuinely strong signal. It is also auditable: you can see exactly which term
caused a chunk to surface, which matters when the question is "why did the
model see this note".
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol, Sequence

from ..schemas import Manifest
from ..vault import Note, NoteScope, VaultScan

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'_-]*")

BM25_K1 = 1.5
BM25_B = 0.75

# Rough characters-per-token for English prose under a Mistral-family BPE.
# Only used when no real tokenizer is available; the context assembler swaps in
# the loaded model's tokenizer, because a budget measured with the wrong
# tokenizer is a budget that overflows silently.
CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric terms, single characters dropped."""
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) > 1]


@dataclass(frozen=True)
class Chunk:
    """A retrievable span of one note."""

    note_rel_path: str
    topics: tuple[str, ...]
    text: str
    heading: str = ""
    index: int = 0
    scope: NoteScope = NoteScope.LOOSE

    @property
    def citation(self) -> str:
        if self.heading:
            return f"{self.note_rel_path} # {self.heading}"
        return self.note_rel_path


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float
    matched_terms: tuple[str, ...] = ()


@dataclass
class RetrievalResult:
    """What retrieval produced, and what it had to leave out."""

    chunks: list[ScoredChunk] = field(default_factory=list)
    considered: int = 0
    hidden_notes: int = 0
    truncated: bool = False
    truncated_count: int = 0
    disabled_reason: str = ""

    @property
    def topics(self) -> tuple[str, ...]:
        seen: set[str] = set()
        for scored in self.chunks:
            seen.update(scored.chunk.topics)
        return tuple(sorted(seen))

    def note(self) -> str:
        """A one-line summary for the status area.

        When retrieval is truncated the user is told so explicitly rather than
        having context silently dropped -- an answer built on half the notes,
        presented as though it were built on all of them, is worse than a short
        answer that says it was short.
        """
        if self.disabled_reason:
            return f"retrieval off ({self.disabled_reason})"
        bits = [f"{len(self.chunks)} chunk(s) from {self.considered} candidate(s)"]
        if self.truncated:
            bits.append(f"{self.truncated_count} dropped for budget")
        if self.hidden_notes:
            bits.append(f"{self.hidden_notes} note(s) hidden by locks")
        return "; ".join(bits)


def chunk_note(
    note: Note,
    *,
    chunk_tokens: int = 320,
    overlap_tokens: int = 48,
    count_tokens: Callable[[str], int] = estimate_tokens,
) -> list[Chunk]:
    """Split a note into overlapping chunks along paragraph boundaries.

    Splitting mid-sentence to hit an exact token count produces chunks that
    retrieve well and read badly; the model then cites a fragment that starts
    halfway through a clause. Paragraphs are the natural unit in a markdown
    note, so a chunk may overshoot the target rather than cut one in half.
    """
    if not note.body.strip():
        return []

    blocks = _split_blocks(note.body)
    chunks: list[Chunk] = []
    current: list[tuple[str, str]] = []  # (heading, text)
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        text = "\n\n".join(t for _, t in current).strip()
        if text:
            chunks.append(
                Chunk(
                    note_rel_path=note.rel_path,
                    topics=note.topics,
                    text=text,
                    heading=current[0][0],
                    index=len(chunks),
                    scope=note.scope,
                )
            )
        if overlap_tokens > 0 and current:
            # Carry the tail forward so a fact spanning a boundary is still
            # findable from either side.
            tail: list[tuple[str, str]] = []
            carried = 0
            for heading, text_block in reversed(current):
                block_tokens = count_tokens(text_block)
                if carried + block_tokens > overlap_tokens and tail:
                    break
                tail.insert(0, (heading, text_block))
                carried += block_tokens
            current = tail
            current_tokens = carried
        else:
            current = []
            current_tokens = 0

    for heading, block in blocks:
        block_tokens = count_tokens(block)
        if current and current_tokens + block_tokens > chunk_tokens:
            flush()
        current.append((heading, block))
        current_tokens += block_tokens

    # Final flush must not re-carry overlap, or it would emit a duplicate tail.
    if current:
        text = "\n\n".join(t for _, t in current).strip()
        if text:
            chunks.append(
                Chunk(
                    note_rel_path=note.rel_path,
                    topics=note.topics,
                    text=text,
                    heading=current[0][0],
                    index=len(chunks),
                    scope=note.scope,
                )
            )
    return chunks


def _split_blocks(body: str) -> list[tuple[str, str]]:
    """Paragraph blocks, each tagged with the heading it sits under."""
    blocks: list[tuple[str, str]] = []
    heading = ""
    buffer: list[str] = []

    def flush_buffer() -> None:
        text = "\n".join(buffer).strip()
        if text:
            blocks.append((heading, text))
        buffer.clear()

    for line in body.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            flush_buffer()
            heading = match.group(2).strip()
            continue
        if not line.strip():
            flush_buffer()
            continue
        buffer.append(line)
    flush_buffer()
    return blocks


class Retriever(Protocol):
    def search(self, query: str, k: int) -> list[ScoredChunk]: ...


class BM25Index:
    """Okapi BM25 over a fixed chunk set.

    Built once per turn from the visible notes. Rebuilding each turn rather
    than caching is deliberate: a note re-tagged as locked, or a topic
    re-locked, must stop being retrievable on the very next message. A cache
    invalidation bug here is a lock bypass, and the index is cheap.
    """

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunks: list[Chunk] = list(chunks)
        self._term_freqs: list[dict[str, int]] = []
        self._lengths: list[int] = []
        self._doc_freq: dict[str, int] = {}

        for chunk in self.chunks:
            terms = tokenize(chunk.text)
            freqs: dict[str, int] = {}
            for term in terms:
                freqs[term] = freqs.get(term, 0) + 1
            self._term_freqs.append(freqs)
            self._lengths.append(len(terms))
            for term in freqs:
                self._doc_freq[term] = self._doc_freq.get(term, 0) + 1

        self._n = len(self.chunks)
        self._avg_len = (sum(self._lengths) / self._n) if self._n else 0.0

    def __len__(self) -> int:
        return self._n

    def _idf(self, term: str) -> float:
        df = self._doc_freq.get(term, 0)
        if df == 0:
            return 0.0
        # The +1 inside the log keeps idf non-negative, so a term appearing in
        # every chunk contributes nothing instead of scoring negatively and
        # pushing otherwise-good chunks below zero.
        return math.log(1.0 + (self._n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int) -> list[ScoredChunk]:
        if self._n == 0 or k <= 0:
            return []
        query_terms = tokenize(query)
        if not query_terms:
            return []

        scored: list[ScoredChunk] = []
        for i, chunk in enumerate(self.chunks):
            freqs = self._term_freqs[i]
            length = self._lengths[i] or 1
            score = 0.0
            matched: list[str] = []
            for term in set(query_terms):
                f = freqs.get(term, 0)
                if f == 0:
                    continue
                idf = self._idf(term)
                denom = f + BM25_K1 * (1 - BM25_B + BM25_B * length / (self._avg_len or 1))
                score += idf * (f * (BM25_K1 + 1)) / denom
                matched.append(term)
            if score > 0:
                scored.append(ScoredChunk(chunk=chunk, score=score, matched_terms=tuple(sorted(matched))))

        scored.sort(key=lambda s: (-s.score, s.chunk.note_rel_path, s.chunk.index))
        return scored[:k]


def build_index(
    scan: VaultScan,
    manifest: Manifest,
    *,
    project: str = "",
    chunk_tokens: int = 320,
    overlap_tokens: int = 48,
    count_tokens: Callable[[str], int] = estimate_tokens,
) -> tuple[BM25Index, int]:
    """Build an index over exactly the notes the model is permitted to see.

    Returns (index, hidden_note_count). The count is what the UI reports so a
    user with notes they cannot retrieve can tell locked from untagged from
    unparseable.
    """
    visible = scan.visible(manifest, project=project, retrievable_only=True)
    chunks: list[Chunk] = []
    for note in visible:
        chunks.extend(
            chunk_note(
                note,
                chunk_tokens=chunk_tokens,
                overlap_tokens=overlap_tokens,
                count_tokens=count_tokens,
            )
        )
    return BM25Index(chunks), scan.hidden_count(manifest)


def retrieve(
    scan: VaultScan,
    manifest: Manifest,
    query: str,
    *,
    project: str = "",
    k: int = 8,
    chunk_tokens: int = 320,
    overlap_tokens: int = 48,
    count_tokens: Callable[[str], int] = estimate_tokens,
    enabled: bool = True,
    disabled_reason: str = "",
) -> RetrievalResult:
    """Layer 3, end to end.

    When `enabled` is False -- the layer switched off in Settings, or trust
    tier 0 where the model gets no vault access -- this returns an empty result
    carrying the reason, rather than falling back to unscoped search. There is
    no configuration under which this function returns a chunk from a locked
    note.
    """
    if not enabled:
        return RetrievalResult(disabled_reason=disabled_reason or "disabled")

    index, hidden = build_index(
        scan,
        manifest,
        project=project,
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
        count_tokens=count_tokens,
    )
    hits = index.search(query, k)
    return RetrievalResult(chunks=hits, considered=len(index), hidden_notes=hidden)


def format_chunks(chunks: Iterable[ScoredChunk]) -> str:
    """Render retrieved chunks for the prompt, with citations.

    Each chunk is labelled with its source path so MAIN can attribute claims,
    and so a user reading the assembled-prompt viewer can trace any statement
    back to the note that supplied it.
    """
    parts: list[str] = []
    for scored in chunks:
        parts.append(f"[{scored.chunk.citation}]\n{scored.chunk.text}")
    return "\n\n".join(parts)
