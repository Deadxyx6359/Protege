"""The vault's search index (B3): ranked by section, incremental, disposable,
and never wider than the permission it was built under.
"""

from __future__ import annotations

import os

import pytest

from protege.core.brain import Vault, VaultError
from protege.core.brain import index as index_module
from protege.core.brain.index import Index, chunks, terms


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path):
    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    write(vault, "Garden.md", "# Garden\n\n## Tomatoes\nPlant tomatoes in May, beside the basil.\n\n"
                              "## Compost\nTurn the heap weekly.\n")
    write(vault, "Recipes/Sauce.md", "# Sauce\nTomato sauce: tomatoes, garlic, basil, olive oil.\n")
    write(vault, "Journal/2026-09-01.md", "Walked the dog. Nothing about vegetables.\n")
    write(vault, "Private/Diary.md", "# Diary\nSecret plans for the tomatoes.\n")
    return vault


def build(root, tmp_path, may_read=None):
    vault = Vault(root, history_dir=tmp_path / "history", may_read=may_read)
    return Index(vault, path=tmp_path / "index.sqlite")


@pytest.fixture
def index(root, tmp_path):
    built = build(root, tmp_path)
    built.refresh()
    return built


def bump(path):
    """Move a file's timestamp on, as an editor saving it would."""
    stat = path.stat()
    os.utime(path, (stat.st_atime + 10, stat.st_mtime + 10))


# -- the text ----------------------------------------------------------------------------


def test_terms_are_lower_case_words_without_common_ones():
    assert terms("The Garden, and the TOMATOES!") == ["garden", "tomatoes"]


def test_a_note_splits_at_its_headings_without_repeating_its_title():
    parts = chunks("Garden", "# Garden\n\n## Tomatoes\nPlant them.\n\n## Compost\nTurn it.\n")
    assert [(c.heading, c.text) for c in parts] == [
        ("Garden › Tomatoes", "Plant them."), ("Garden › Compost", "Turn it.")]


def test_a_heading_inside_code_does_not_split_a_section():
    parts = chunks("Code", "## Setup\n```\n## not a heading\n```\nDone.\n")
    assert [c.heading for c in parts] == ["Code › Setup"]


def test_a_note_that_is_only_a_title_is_still_findable():
    assert [(c.heading, c.text) for c in chunks("Empty", "")] == [("Empty", "")]


def test_a_long_section_is_windowed_with_overlap(monkeypatch):
    monkeypatch.setattr(index_module, "CHUNK_CHARS", 200)
    monkeypatch.setattr(index_module, "CHUNK_OVERLAP", 40)
    text = " ".join(f"word{n}" for n in range(200))
    parts = chunks("Long", text)
    assert len(parts) > 3 and all(len(p.text) <= 200 for p in parts)
    first_tail = parts[0].text.split()[-1]
    assert first_tail in parts[1].text, "neighbouring windows do not overlap"


# -- ranking ------------------------------------------------------------------------------


def test_a_section_holding_every_word_comes_first(index):
    results = index.search("tomato sauce")
    assert results[0].rel == "Recipes/Sauce.md" and results[0].complete
    assert any(r.rel == "Garden.md" and not r.complete for r in results)


def test_results_cite_the_section_they_came_from(index):
    [hit] = index.search("compost")
    assert hit.rel == "Garden.md" and hit.heading == "Garden › Compost"
    assert "heap" in hit.snippet


def test_plurals_and_longer_forms_are_found(index):
    assert index.search("gardens")[0].rel == "Garden.md"
    assert {r.rel for r in index.search("tomato")} >= {"Garden.md", "Recipes/Sauce.md"}


def test_a_query_of_only_common_words_is_refused(index):
    with pytest.raises(VaultError):
        index.search("the and of")


def test_one_long_note_cannot_fill_the_results(root, tmp_path):
    write(root, "Long.md", "".join(f"## Part {n}\nalpha alpha alpha\n\n" for n in range(20)))
    write(root, "Short.md", "A single alpha.\n")
    built = build(root, tmp_path)
    built.refresh()
    rels = [r.rel for r in built.search("alpha", limit=5)]
    assert rels.count("Long.md") == index_module.MAX_SECTIONS_PER_NOTE
    assert "Short.md" in rels


# -- keeping current ------------------------------------------------------------------------


def test_the_first_refresh_reads_everything_and_the_next_reads_nothing(root, tmp_path):
    built = build(root, tmp_path)
    assert built.refresh() == {"added": 4, "updated": 0, "removed": 0, "read": 4}
    assert built.refresh() == {"added": 0, "updated": 0, "removed": 0, "read": 0}


def test_only_the_changed_note_is_read_again(index, root):
    path = write(root, "Recipes/Sauce.md", "# Sauce\nNow with smoked paprika.\n")
    bump(path)
    assert index.refresh() == {"added": 0, "updated": 1, "removed": 0, "read": 1}
    assert index.search("paprika")[0].rel == "Recipes/Sauce.md"
    assert not any(r.rel == "Recipes/Sauce.md" for r in index.search("garlic"))


def test_a_note_saved_without_changes_is_not_reindexed(index, root):
    bump(root / "Garden.md")
    assert index.refresh() == {"added": 0, "updated": 0, "removed": 0, "read": 1}


def test_a_deleted_note_leaves_the_index(index, root):
    (root / "Recipes" / "Sauce.md").unlink()
    assert index.refresh()["removed"] == 1
    assert not any(r.rel == "Recipes/Sauce.md" for r in index.search("garlic"))


def test_the_index_survives_a_restart(index, root, tmp_path):
    reopened = build(root, tmp_path)
    assert reopened.refresh()["read"] == 0
    assert reopened.search("compost")[0].rel == "Garden.md"


def test_a_damaged_index_is_rebuilt_not_trusted(root, tmp_path):
    (tmp_path / "index.sqlite").write_bytes(b"this is not a database at all" * 20)
    built = build(root, tmp_path)
    assert built.refresh()["added"] == 4
    assert built.search("compost")


# -- the grant --------------------------------------------------------------------------------


def outside_private(root):
    return lambda path: not path.is_relative_to(root / "Private")


def test_only_what_may_be_read_is_indexed(root, tmp_path):
    built = build(root, tmp_path, may_read=outside_private(root))
    assert built.refresh()["read"] == 3, "a note outside the grant was read"
    assert built.search("secret") == []


def test_losing_permission_drops_notes_from_the_index(index, root, tmp_path):
    narrowed = build(root, tmp_path, may_read=outside_private(root))
    assert narrowed.refresh()["removed"] == 1
    assert build(root, tmp_path).search("secret") == []


def test_results_are_filtered_at_query_time_too(index, root, tmp_path):
    """An index built under a wider grant must not answer beyond a narrower one."""
    narrowed = build(root, tmp_path, may_read=outside_private(root))
    assert narrowed.search("secret") == []
    assert index.search("secret")[0].rel == "Private/Diary.md"
