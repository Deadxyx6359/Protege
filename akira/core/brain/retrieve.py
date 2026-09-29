"""Retrieval: the passages worth putting in front of a model, and where each came from.

B4, over the B3 index. Three rules.

**Retrieval is a tool.** Each source — notes, documents, past conversations —
is searched by calling its tool through the registry, so every search is held
to the permission for that source and written to the audit log exactly as if an
agent had asked. Nothing reads the vault on the side because a chat wanted
context.

**Sources are merged by rank, not score.** BM25 scores from different indexes
are not on one scale — a rare word in a small folder scores high — so ranked
lists are merged by reciprocal rank fusion: a passage weighs the sum of
1/(60 + rank) over the lists it appears in. The same method will merge lexical
and embedding results when embeddings arrive, which is what makes it hybrid.

**What was left out is said.** A budget caps how much text comes back. When
passages are left out for it, or a source could not be searched, the result
says so, rather than presenting part of the evidence as all of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping, Sequence

if TYPE_CHECKING:
    from akira.core.tools import ToolContext, ToolRegistry

RRF_K = 60
LIMIT = 8
BUDGET_CHARS = 6000


@dataclass(frozen=True, slots=True)
class Passage:
    source: str
    """`notes`, `documents` or `conversations`."""

    cite: str
    """Where it came from, as a person would look it up: a file and its section."""

    text: str


@dataclass
class Retrieval:
    passages: list[Passage] = field(default_factory=list)
    searched: list[str] = field(default_factory=list)
    unavailable: list[tuple[str, str]] = field(default_factory=list)
    """Sources that could not be searched, with the reason."""

    left_out: int = 0
    """Passages that ranked but did not fit the budget."""

    def note(self) -> str:
        """One line for the status area: what was found, and what was not looked at."""
        bits = []
        if self.searched:
            count = len(self.passages)
            bits.append(f"{count} passage{'' if count == 1 else 's'} from {', '.join(self.searched)}")
        if self.left_out:
            bits.append(f"{self.left_out} more left out for length")
        bits += [f"{source} not searched: {reason}" for source, reason in self.unavailable]
        return "; ".join(bits) or "nothing was searched"

    def for_prompt(self) -> str:
        """The passages, each under its citation, so a claim can be traced to its source."""
        return "\n\n".join(f"[{p.source}: {p.cite}]\n{p.text.strip()}" for p in self.passages)


def fuse(ranked: Mapping[str, Sequence[Passage]]) -> list[Passage]:
    """Ranked lists merged by reciprocal rank, best first.

    A passage found by more than one list counts once, and for more. Ties go to
    the better rank, then to the source named first.
    """
    weight: dict[Passage, float] = {}
    first: dict[Passage, tuple[int, int]] = {}
    for order, passages in enumerate(ranked.values()):
        for rank, passage in enumerate(passages):
            weight[passage] = weight.get(passage, 0.0) + 1.0 / (RRF_K + rank + 1)
            first.setdefault(passage, (rank, order))
    return sorted(weight, key=lambda p: (-weight[p], first[p]))


def gather(registry: ToolRegistry, context: ToolContext, query: str, *,
           vault: str | None = None, folder: str | None = None, conversations: bool = False,
           folders: list[str] | tuple[str, ...] = (),
           limit: int = LIMIT, budget_chars: int = BUDGET_CHARS) -> Retrieval:
    """Search the sources asked for, as \a context's actor, and merge what they find.

    \a folder and \a folders are folders of documents: the open project's, and
    the library's (`akira.core.documents.library`).
    """
    wanted = []
    if vault:
        wanted.append(("notes", "search_notes", {"vault": str(vault), "query": query}))
    for place in dict.fromkeys(str(f) for f in (folder, *folders) if f):
        wanted.append(("documents", "search_documents", {"folder": place, "query": query}))
    if conversations:
        wanted.append(("conversations", "search_conversations", {"query": query}))

    retrieval = Retrieval()
    ranked: dict[str, list[Passage]] = {}
    for source, tool, arguments in wanted:
        # Through the registry: the permission for this source is checked with
        # the real scope, and the search is audited like any other tool call.
        result = registry.invoke(tool, arguments, context)
        if not result.ok:
            retrieval.unavailable.append((source, result.content))
            continue
        if source not in retrieval.searched:
            retrieval.searched.append(source)
        # Each folder ranked on its own, then merged like any other source.
        key = source if source not in ranked else f"{source}:{len(ranked)}"
        ranked[key] = [Passage(source, str(p["cite"]), str(p["text"]))
                       for p in (result.data or {}).get("passages", ())]

    used = 0
    for passage in fuse(ranked):
        if len(retrieval.passages) >= limit:
            break
        if retrieval.passages and used + len(passage.text) > budget_chars:
            retrieval.left_out += 1
            continue
        retrieval.passages.append(passage)
        used += len(passage.text)
    return retrieval
