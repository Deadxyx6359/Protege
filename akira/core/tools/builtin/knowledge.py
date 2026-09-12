"""Searching what the person knows: documents in a folder, and past conversations.

Notes are searched by `search_notes`, in `notes.py`. All three answer from the
local index (`akira.core.brain.index`), ranked by section, and hand back the
passages with where each came from. They are what retrieval (B4) calls, so
every search is held to its own permission and audited.

**Documents need `docs.read` for the folder**, and only the files it covers
are opened, even inside that folder. Markdown and text files are plain files,
so they are searched only where `files.read` reaches too.

**Conversations need `memory.read`.** What someone said in a chat is theirs,
and an agent does not get to trawl it because it may read their files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from akira.core.brain import Index, Result, VaultError
from akira.core.brain.corpora import TEXT_SUFFIXES, ConversationArchive, DocumentFolder
from akira.security.paths import real

from ..schema import Parameter, Requirement, Tool, ToolContext, ToolError, ToolResult

MAX_PASSAGES = 12


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def cite_file(result: Result) -> str:
    return f"{result.rel} › {result.section}" if result.section else result.rel


def cite_conversation(result: Result) -> str:
    return result.heading


def present(results: list[Result], query: str, *, noun: str,
            cite: Callable[[Result], str]) -> ToolResult:
    """Search results for the model to read, and as passages for retrieval to merge."""
    if not results:
        return ToolResult.success(f"Nothing in the {noun}s matches {query!r}.",
                                  data={"count": 0, "passages": []})
    sources = len({r.rel for r in results})
    lines = [f"{_plural(len(results), 'passage')} from {_plural(sources, noun)} "
             f"match {query!r}, best first:", ""]
    lines += [f"- {cite(r)} — {r.snippet}" + ("" if r.complete else " (some of the words)")
              for r in results]
    passages = [{"cite": cite(r), "rel": r.rel, "section": r.section, "text": r.text,
                 "score": r.score, "complete": r.complete} for r in results]
    return ToolResult.success("\n".join(lines), data={"count": len(results), "passages": passages})


def _search(index: Index, query: str) -> list[Result]:
    try:
        index.refresh()
        return index.search(query, limit=MAX_PASSAGES)
    except VaultError as exc:
        raise ToolError(str(exc)) from None


# -- search_documents -------------------------------------------------------------------


def _may_open(context: ToolContext) -> Callable[[Path], bool]:
    def check(path: Path) -> bool:
        capability = "files.read" if path.suffix.lower() in TEXT_SUFFIXES else "docs.read"
        return bool(context.policy.allows(capability, str(path)))
    return check


def _run_documents(arguments: dict, context: ToolContext) -> ToolResult:
    folder = real(arguments["folder"])
    if not folder.is_dir():
        raise ToolError(f"not a folder: {folder}")
    try:
        corpus = DocumentFolder(folder, may_read=_may_open(context))
    except VaultError as exc:
        raise ToolError(str(exc)) from None
    query = str(arguments["query"])
    return present(_search(Index(corpus), query), query, noun="document", cite=cite_file)


search_documents = Tool(
    name="search_documents",
    summary=("Search the Word, Excel, PowerPoint and PDF files in a folder for the passages "
             "most about a question, best first, each with its file and heading. Markdown and "
             "text files are included where files may be read."),
    parameters=(
        Parameter("folder", "string", "Absolute path to the folder."),
        Parameter("query", "string", "What to look for, in a few words."),
    ),
    requires=(Requirement("docs.read", scope_from="folder"),),
    run=_run_documents,
)


# -- search_conversations ------------------------------------------------------------------


def _run_conversations(arguments: dict, context: ToolContext) -> ToolResult:
    query = str(arguments["query"])
    return present(_search(Index(ConversationArchive()), query), query, noun="conversation",
                   cite=cite_conversation)


search_conversations = Tool(
    name="search_conversations",
    summary=("Search earlier conversations for what was said about something. Returns the "
             "exchanges that match, best first, each under its conversation's title."),
    parameters=(Parameter("query", "string", "What to look for, in a few words."),),
    requires=(Requirement("memory.read"),),
    run=_run_conversations,
)


ALL = (search_documents, search_conversations)
