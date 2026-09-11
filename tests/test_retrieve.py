"""Retrieval (B4): documents and conversations as corpora, the search tools and
the permission each needs, and merging sources into cited passages.
"""

from __future__ import annotations

import json

import pytest

from protege.core.agents.roles import GATHERER
from protege.core.brain import Index, VaultError
from protege.core.brain.corpora import ConversationArchive, DocumentFolder
from protege.core.brain.retrieve import Passage, fuse, gather
from protege.core.documents import sheets, word
from protege.core.permissions import AuditLog, Policy, SecretStore
from protege.core.permissions.capabilities import ScopeKind, get
from protege.core.tools import ToolContext, default_registry


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


def docx(outline: str) -> bytes:
    return word.create(word.parse_outline(outline), title="Document")


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "Documents"
    (root / "private").mkdir(parents=True)
    (root / ".cache").mkdir()
    (root / "plan.docx").write_bytes(docx(
        "# Plan\n\n## Timeline\nLaunch in March, once the tomatoes are in.\n\n## Budget\nPaper and ink.\n"))
    (root / "budget.xlsx").write_bytes(sheets.create(
        [("Budget", [["Item", "Cost"], ["Paper", 12.5], ["Ink", 30]])], title="Budget"))
    (root / "ideas.md").write_text("# Ideas\nA greenhouse for the tomatoes.\n", encoding="utf-8")
    (root / "private" / "salary.docx").write_bytes(docx("# Salary\nConfidential figures.\n"))
    (root / ".cache" / "old.docx").write_bytes(docx("# Old\nConfidential figures.\n"))
    (root / "~$plan.docx").write_bytes(b"the lock file Word leaves beside an open document")
    (root / "broken.docx").write_bytes(b"not a zip at all")
    return root


def conversation(directory, cid, title, *turns):
    directory.mkdir(parents=True, exist_ok=True)
    messages = [{"id": f"m{n}", "role": role, "text": text, "created": 0, "error": error}
                for n, (role, text, error) in enumerate(turns)]
    (directory / f"{cid}.json").write_text(
        json.dumps({"id": cid, "title": title, "messages": messages}), encoding="utf-8")


@pytest.fixture
def chats(tmp_path):
    directory = tmp_path / "cfg" / "conversations"
    conversation(directory, "a1b2c3d4", "Garden planning",
                 ("user", "When should I plant the tomatoes?", False),
                 ("assistant", "In May, after the last frost.", False),
                 ("user", "And the basil?", False),
                 ("assistant", "The model stopped responding.", True),
                 ("assistant", "Alongside the tomatoes, in the sun.", False))
    (directory / "deadbeef.json").write_text("{not json", encoding="utf-8")
    return directory


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "Vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "Garden.md").write_text(
        "# Garden\n\n## Tomatoes\nStake the tomatoes in June.\n\n## Compost\nTurn it weekly.\n",
        encoding="utf-8")
    return root


def ctx(tmp_path, *grants):
    policy = Policy()
    for capability, *scope in grants:
        policy.grant(capability, tuple(str(s) for s in scope))
    return ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"), actor="tester")


def everything(tmp_path, vault, folder):
    return ctx(tmp_path, ("vault.read", vault), ("docs.read", folder), ("files.read", folder),
               ("memory.read",))


def call(name, arguments, context):
    return default_registry().invoke(name, arguments, context)


def offered(context):
    return {tool.name for tool in default_registry().available(context.policy)}


# -- documents ---------------------------------------------------------------------------


def test_documents_are_indexed_by_their_text(folder, tmp_path):
    index = Index(DocumentFolder(folder), path=tmp_path / "docs.sqlite")
    # plan, budget, ideas and private/salary. The broken file is skipped; the
    # lock file and the hidden folder are never listed.
    assert index.refresh()["added"] == 4
    [hit] = [r for r in index.search("launch") if r.rel == "plan.docx"]
    assert "Timeline" in hit.heading and "March" in hit.text
    assert any(r.rel == "budget.xlsx" for r in index.search("ink"))
    assert [r.rel for r in index.search("figures")] == ["private/salary.docx"]


def test_only_documents_that_may_be_read_are_opened(folder, tmp_path):
    corpus = DocumentFolder(folder, may_read=lambda path: "private" not in path.parts)
    index = Index(corpus, path=tmp_path / "docs.sqlite")
    index.refresh()
    assert index.search("figures") == []


def test_a_file_outside_the_folder_is_refused(folder, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(VaultError):
        DocumentFolder(folder).read(outside)


# -- conversations -------------------------------------------------------------------------


def test_conversations_are_indexed_one_exchange_to_a_section(chats, tmp_path):
    index = Index(ConversationArchive(chats), path=tmp_path / "chats.sqlite")
    assert index.refresh()["added"] == 1, "the damaged conversation was not skipped"
    [hit] = index.search("frost")
    assert hit.rel == "a1b2c3d4"
    assert hit.heading == "Garden planning › When should I plant the tomatoes?"
    assert "Assistant: In May" in hit.text
    assert index.search("stopped responding") == [], "a failed turn was kept as if it were an answer"


# -- the tools and their permissions -----------------------------------------------------


def test_remembering_conversations_is_its_own_capability():
    memory = get("memory.read")
    assert memory.scope is ScopeKind.NONE
    assert not memory.leaves_machine and not memory.irreversible


def test_documents_need_document_permission_not_file_permission(folder, tmp_path):
    assert "search_documents" not in offered(ctx(tmp_path, ("files.read", folder)))
    result = call("search_documents", {"folder": str(folder), "query": "launch"},
                  ctx(tmp_path, ("docs.read", folder)))
    assert result.ok and "plan.docx" in result.content and "Timeline" in result.content


def test_text_files_in_the_folder_need_file_permission_too(folder, tmp_path):
    query = {"folder": str(folder), "query": "greenhouse"}
    documents_only = call("search_documents", query, ctx(tmp_path, ("docs.read", folder)))
    assert documents_only.ok and "ideas.md" not in documents_only.content
    both = call("search_documents", query,
                ctx(tmp_path, ("docs.read", folder), ("files.read", folder)))
    assert "ideas.md" in both.content


def test_conversations_need_their_own_permission(chats, tmp_path):
    reading = ctx(tmp_path, ("vault.read", tmp_path), ("docs.read", tmp_path), ("files.read", tmp_path))
    assert "search_conversations" not in offered(reading)
    refused = call("search_conversations", {"query": "frost"}, reading)
    assert not refused.ok and "Not permitted" in refused.content
    result = call("search_conversations", {"query": "frost"}, ctx(tmp_path, ("memory.read",)))
    assert result.ok and "Garden planning › When should I plant the tomatoes?" in result.content


def test_note_search_returns_cited_sections(vault, tmp_path):
    result = call("search_notes", {"vault": str(vault), "query": "stake tomatoes"},
                  ctx(tmp_path, ("vault.read", vault)))
    assert result.ok and "Garden.md › Tomatoes" in result.content
    [passage] = [p for p in result.data["passages"] if p["section"] == "Tomatoes"]
    assert passage["text"] == "Stake the tomatoes in June."


def test_the_gatherer_can_search_documents_and_conversations():
    assert {"search_documents", "search_conversations"} <= set(GATHERER.tools)


# -- merging ----------------------------------------------------------------------------------


def test_retrieval_merges_every_source_and_cites_each(vault, folder, chats, tmp_path):
    found = gather(default_registry(), everything(tmp_path, vault, folder), "tomatoes",
                   vault=str(vault), folder=str(folder), conversations=True)
    assert found.searched == ["notes", "documents", "conversations"] and not found.unavailable
    assert [p.source for p in found.passages[:3]] == ["notes", "documents", "conversations"]
    prompt = found.for_prompt()
    assert "[notes: Garden.md › Tomatoes]\nStake the tomatoes in June." in prompt
    assert "[conversations: Garden planning › " in prompt


def test_a_source_that_may_not_be_searched_is_reported_and_audited(vault, folder, tmp_path):
    found = gather(default_registry(), ctx(tmp_path, ("vault.read", vault)), "tomatoes",
                   vault=str(vault), folder=str(folder))
    assert found.searched == ["notes"]
    [(source, reason)] = found.unavailable
    assert source == "documents" and "Not permitted" in reason
    assert "documents not searched" in found.note()
    assert "search_documents" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_the_budget_holds_and_what_did_not_fit_is_counted(vault, folder, chats, tmp_path):
    found = gather(default_registry(), everything(tmp_path, vault, folder), "tomatoes",
                   vault=str(vault), folder=str(folder), conversations=True, budget_chars=40)
    assert len(found.passages) == 1 and found.left_out >= 2
    assert "left out for length" in found.note()


def test_a_passage_found_twice_ranks_above_one_found_once():
    a, b, c = (Passage("notes", name, name) for name in "abc")
    assert fuse({"lexical": [a, b], "semantic": [b, c]}) == [b, a, c]


def test_equal_ranks_interleave_in_source_order():
    a1, a2 = Passage("notes", "a1", "x"), Passage("notes", "a2", "y")
    b1 = Passage("documents", "b1", "z")
    assert fuse({"notes": [a1, a2], "documents": [b1]}) == [a1, b1, a2]
