"""Layer 3 -- chunking, BM25 ranking, and scoped retrieval."""

from __future__ import annotations

import pytest

from protege.lock.retrieval import (
    BM25Index,
    build_index,
    chunk_note,
    format_chunks,
    retrieve,
    tokenize,
)
from protege.schemas import Manifest
from protege.vault import Note, NoteScope, scan_vault


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "global" / "notes").mkdir(parents=True)
    (root / "projects" / "demo" / "notes").mkdir(parents=True)
    (root / "projects" / "demo" / "memory" / "pending").mkdir(parents=True)
    return root


def write(path, topics, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    joined = ", ".join(topics)
    path.write_text(f"---\ntopics: [{joined}]\n---\n\n{body}\n", encoding="utf-8")


def _manifest(*unlocked):
    manifest = Manifest.initial()
    for topic in unlocked:
        manifest = manifest.with_unlocked(topic)
    return manifest


def _note(rel, topics, body, scope=NoteScope.GLOBAL):
    from pathlib import Path

    return Note(
        path=Path(rel), rel_path=rel, scope=scope, project="",
        topics=tuple(topics), body=body, frontmatter={},
    )


# --- tokenizing ------------------------------------------------------------


def test_tokenize_lowercases_and_drops_single_chars():
    assert tokenize("The Quick brown-fox, a B c99") == ["the", "quick", "brown-fox", "c99"]


def test_tokenize_empty():
    assert tokenize("!!! ??? .") == []


# --- chunking --------------------------------------------------------------


def test_short_note_is_one_chunk():
    chunks = chunk_note(_note("a.md", ["t"], "One short paragraph."))
    assert len(chunks) == 1
    assert chunks[0].text == "One short paragraph."


def test_empty_note_yields_no_chunks():
    assert chunk_note(_note("a.md", ["t"], "   \n\n  ")) == []


def test_long_note_splits_into_several_chunks():
    body = "\n\n".join(f"Paragraph number {i} with a reasonable amount of filler text in it." for i in range(40))
    chunks = chunk_note(_note("a.md", ["t"], body), chunk_tokens=60, overlap_tokens=0)
    assert len(chunks) > 3
    assert all(c.note_rel_path == "a.md" for c in chunks)


def test_chunks_carry_their_heading():
    body = "# Optics\n\nLight bends when it enters glass.\n\n# Motion\n\nObjects keep moving.\n"
    chunks = chunk_note(_note("a.md", ["physics"], body), chunk_tokens=8, overlap_tokens=0)
    headings = {c.heading for c in chunks}
    assert "Optics" in headings


def test_chunks_inherit_the_notes_topics():
    chunks = chunk_note(_note("a.md", ["physics", "optics"], "Body."))
    assert chunks[0].topics == ("physics", "optics")


def test_overlap_carries_context_across_a_boundary():
    body = "\n\n".join(f"Block {i} content here." for i in range(12))
    with_overlap = chunk_note(_note("a.md", ["t"], body), chunk_tokens=20, overlap_tokens=10)
    without = chunk_note(_note("a.md", ["t"], body), chunk_tokens=20, overlap_tokens=0)
    assert len(with_overlap) >= len(without)
    joined = " ".join(c.text for c in with_overlap)
    # Some block appears in two chunks -- that is what overlap means.
    assert any(joined.count(f"Block {i} content here.") > 1 for i in range(12))


def test_final_chunk_is_not_a_duplicated_overlap_tail():
    body = "\n\n".join(f"Para {i}." for i in range(6))
    chunks = chunk_note(_note("a.md", ["t"], body), chunk_tokens=10, overlap_tokens=5)
    assert chunks[-1].text.strip()
    assert len({c.index for c in chunks}) == len(chunks)


# --- BM25 ------------------------------------------------------------------


def test_empty_index_returns_nothing():
    assert BM25Index([]).search("anything", 5) == []


def test_ranks_the_relevant_chunk_first():
    chunks = (
        chunk_note(_note("a.md", ["t"], "Photosynthesis converts light into chemical energy."))
        + chunk_note(_note("b.md", ["t"], "The bicycle has two wheels and a chain."))
    )
    hits = BM25Index(chunks).search("how does photosynthesis work", 5)
    assert hits
    assert hits[0].chunk.note_rel_path == "a.md"


def test_query_with_no_overlap_returns_nothing():
    chunks = chunk_note(_note("a.md", ["t"], "Bicycles have wheels."))
    assert BM25Index(chunks).search("photosynthesis chlorophyll", 5) == []


def test_matched_terms_are_reported():
    chunks = chunk_note(_note("a.md", ["t"], "Photosynthesis uses chlorophyll."))
    hit = BM25Index(chunks).search("chlorophyll", 3)[0]
    assert "chlorophyll" in hit.matched_terms


def test_k_limits_results():
    chunks = []
    for i in range(10):
        chunks += chunk_note(_note(f"n{i}.md", ["t"], "shared keyword here"))
    assert len(BM25Index(chunks).search("shared keyword", 3)) == 3


def test_ubiquitous_term_scores_non_negative():
    # With df == N a naive idf goes negative and drags good chunks below zero.
    chunks = []
    for i in range(5):
        chunks += chunk_note(_note(f"n{i}.md", ["t"], "common word everywhere"))
    hits = BM25Index(chunks).search("common", 5)
    assert all(h.score >= 0 for h in hits)


def test_ranking_is_deterministic():
    chunks = []
    for i in range(6):
        chunks += chunk_note(_note(f"n{i}.md", ["t"], "identical text for every chunk"))
    index = BM25Index(chunks)
    first = [h.chunk.note_rel_path for h in index.search("identical text", 6)]
    second = [h.chunk.note_rel_path for h in index.search("identical text", 6)]
    assert first == second


# --- scoping: the security property ----------------------------------------


def test_locked_notes_never_enter_the_index(vault):
    # Scoping happens at index-build time. There is no ranked list containing a
    # locked chunk that a later filter could fail to remove.
    write(vault / "global" / "notes" / "locked.md", ["chemistry"], "Sodium reacts violently with water.")
    write(vault / "global" / "notes" / "open.md", ["physics"], "Objects fall at nine point eight.")
    scan = scan_vault(vault)
    index, hidden = build_index(scan, _manifest("physics"))
    all_text = " ".join(c.text for c in index.chunks)
    assert "Sodium" not in all_text
    assert hidden == 1


def test_query_that_targets_locked_content_returns_nothing(vault):
    write(vault / "global" / "notes" / "locked.md", ["chemistry"], "Sodium reacts violently with water.")
    scan = scan_vault(vault)
    result = retrieve(scan, _manifest("physics"), "tell me about sodium reacting with water")
    assert result.chunks == []
    assert result.hidden_notes == 1


def test_untagged_note_is_not_retrievable(vault):
    (vault / "global" / "notes" / "untagged.md").write_text("Sodium reacts with water.", encoding="utf-8")
    scan = scan_vault(vault)
    assert retrieve(scan, _manifest("chemistry"), "sodium water").chunks == []


def test_partially_locked_note_is_not_retrievable(vault):
    write(vault / "global" / "notes" / "mixed.md", ["physics", "chemistry"], "Sodium and gravity.")
    scan = scan_vault(vault)
    assert retrieve(scan, _manifest("physics"), "sodium gravity").chunks == []
    assert retrieve(scan, _manifest("physics", "chemistry"), "sodium gravity").chunks


def test_pending_memory_is_not_retrievable(vault):
    write(
        vault / "projects" / "demo" / "memory" / "pending" / "s.md",
        ["physics"],
        "Unconfirmed consolidated claim about gravity.",
    )
    scan = scan_vault(vault)
    result = retrieve(scan, _manifest("physics"), "gravity", project="demo")
    assert result.chunks == []


def test_project_notes_do_not_leak_across_projects(vault):
    write(vault / "projects" / "demo" / "notes" / "a.md", ["physics"], "Demo project gravity note.")
    scan = scan_vault(vault)
    assert retrieve(scan, _manifest("physics"), "gravity", project="demo").chunks
    assert retrieve(scan, _manifest("physics"), "gravity", project="other").chunks == []


def test_relocking_removes_content_from_retrieval_immediately(vault):
    # The index is rebuilt each turn precisely so this holds on the very next
    # message rather than whenever a cache expires.
    write(vault / "global" / "notes" / "a.md", ["physics"], "Objects fall at nine point eight.")
    scan = scan_vault(vault)
    manifest = _manifest("physics")
    assert retrieve(scan, manifest, "objects fall").chunks
    assert retrieve(scan, manifest.with_relocked("physics"), "objects fall").chunks == []


def test_disabled_retrieval_returns_empty_with_a_reason(vault):
    write(vault / "global" / "notes" / "a.md", ["physics"], "Objects fall.")
    scan = scan_vault(vault)
    result = retrieve(scan, _manifest("physics"), "objects", enabled=False, disabled_reason="trust tier 0")
    assert result.chunks == []
    assert "trust tier 0" in result.note()


def test_disabled_retrieval_does_not_fall_back_to_unscoped_search(vault):
    write(vault / "global" / "notes" / "a.md", ["chemistry"], "Sodium reacts.")
    scan = scan_vault(vault)
    result = retrieve(scan, Manifest.initial(), "sodium", enabled=False)
    assert result.chunks == []


def test_empty_manifest_retrieves_nothing_at_all(vault):
    write(vault / "global" / "notes" / "a.md", ["physics"], "Objects fall.")
    write(vault / "global" / "notes" / "b.md", ["chemistry"], "Sodium reacts.")
    scan = scan_vault(vault)
    assert retrieve(scan, Manifest.initial(), "objects sodium").chunks == []


# --- formatting ------------------------------------------------------------


def test_formatted_chunks_carry_citations(vault):
    write(vault / "global" / "notes" / "a.md", ["physics"], "# Gravity\n\nObjects fall at nine point eight.")
    scan = scan_vault(vault)
    result = retrieve(scan, _manifest("physics"), "objects fall")
    text = format_chunks(result.chunks)
    assert "global/notes/a.md" in text
    assert "Objects fall" in text


def test_result_note_reports_hidden_notes(vault):
    write(vault / "global" / "notes" / "a.md", ["physics"], "Objects fall.")
    write(vault / "global" / "notes" / "b.md", ["chemistry"], "Sodium reacts.")
    scan = scan_vault(vault)
    assert "1 note(s) hidden by locks" in retrieve(scan, _manifest("physics"), "objects").note()
