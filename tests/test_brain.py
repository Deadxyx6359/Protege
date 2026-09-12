"""The second brain's vault (B2): Markdown as Obsidian writes it, and a vault
that is written automatically without ever losing anything.
"""

from __future__ import annotations

from datetime import date

import pytest

from akira.core.brain import ConflictError, Vault, VaultError, markdown, moment_format
from akira.core.brain import vault as vault_module
from akira.core.brain.markdown import Link


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


# == Markdown ============================================================================


def test_frontmatter_is_split_from_the_body():
    frontmatter, body, error = markdown.split("---\ntags: [a, b]\nstatus: open\n---\n# Title\n")
    assert frontmatter == {"tags": ["a", "b"], "status": "open"}
    assert body == "# Title\n" and error == ""


def test_an_empty_frontmatter_block_is_fine():
    assert markdown.split("---\n---\nbody") == ({}, "body", "")


def test_malformed_frontmatter_is_reported_not_raised():
    frontmatter, body, error = markdown.split("---\ntags: [unclosed\n---\ntext")
    assert frontmatter == {} and body == "text" and "not valid YAML" in error


def test_frontmatter_must_be_named_values():
    assert "named values" in markdown.split("---\n- just\n- a list\n---\n")[2]


def test_compose_round_trips():
    text = markdown.compose({"status": "open", "tags": ["x"]}, "# Body\n")
    assert markdown.split(text) == ({"status": "open", "tags": ["x"]}, "# Body\n", "")
    assert markdown.compose({}, "plain") == "plain"


def test_tags_come_from_frontmatter_and_text():
    assert markdown.tags({"tags": ["project", "#draft"]}, "about #garden and #Project") == (
        "project", "draft", "garden")
    assert markdown.tags({"tags": "alpha, beta gamma"}, "") == ("alpha", "beta", "gamma")


def test_tags_ignore_code_headings_links_and_bare_numbers():
    body = ("# Heading\n```\n#include <x>\n```\nInline `#nope`, a url http://x.test/#anchor,\n"
            "issue #42, but #y2026 and #nested/tag count.\n")
    assert markdown.tags({}, body) == ("y2026", "nested/tag")


def test_links_in_all_their_forms():
    body = ("[[Plain]] [[Target|Alias]] [[Page#Section]] ![[Embedded.png]] "
            "[text](Folder/My%20Note.md) [site](https://example.com/page.md)")
    assert markdown.links(body) == (
        Link("Plain"), Link("Target", alias="Alias"), Link("Page", heading="Section"),
        Link("Embedded.png", embed=True), Link("Folder/My Note.md", alias="text"))


def test_links_inside_code_are_not_links():
    assert markdown.links("```\n[[Not]]\n```\n`[[Nope]]` [[Yes]]") == (Link("Yes"),)


def test_appending_under_a_heading_lands_at_the_end_of_that_section():
    body = "## Log\n- one\n\n## Other\n- keep\n"
    assert markdown.append_under(body, "- two", "Log") == "## Log\n- one\n- two\n\n## Other\n- keep\n"


def test_appending_to_the_last_section():
    assert markdown.append_under("## Log\n- one\n", "- two", "log") == "## Log\n- one\n- two\n"


def test_appending_to_a_missing_heading_creates_it():
    assert markdown.append_under("# Day\n", "- task", "Tasks") == "# Day\n\n## Tasks\n- task\n"
    assert markdown.append_under("", "- task", "Tasks") == "## Tasks\n- task\n"


def test_appending_without_a_heading_adds_at_the_end():
    assert markdown.append_under("line", "more") == "line\nmore\n"


def test_appending_keeps_windows_line_endings():
    body = "## Log\r\n- one\r\n"
    assert markdown.append_under(body, "- two", "Log") == "## Log\r\n- one\r\n- two\r\n"


def test_a_heading_inside_code_is_not_a_section():
    body = "```\n## Log\n```\n"
    assert markdown.append_under(body, "- x", "Log") == "```\n## Log\n```\n\n## Log\n- x\n"


@pytest.mark.parametrize("pattern, expected", [
    ("YYYY-MM-DD", "2026-03-02"),
    ("YYYY/MM/YYYY-MM-DD", "2026/03/2026-03-02"),
    ("dddd, Do MMMM YYYY", "Monday, 2nd March 2026"),
    ("[Journal] D.M.YY", "Journal 2.3.26"),
])
def test_daily_note_names_follow_obsidians_date_format(pattern, expected):
    assert moment_format(date(2026, 3, 2), pattern) == expected


# == the vault ===========================================================================


@pytest.fixture
def root(tmp_path):
    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "daily-notes.json").write_text(
        '{"folder": "Daily", "format": "YYYY-MM-DD"}', encoding="utf-8")
    (vault / ".trash").mkdir()
    (vault / ".trash" / "Gone.md").write_text("[[Ideas]] garden", encoding="utf-8")
    (vault / "Projects").mkdir()
    (vault / "Projects" / "Ideas.md").write_text(
        "---\ntags: [project]\nstatus: open\n---\n# Ideas\n\nA #garden planner.\n"
        "See [[Reading List|the list]] and [[Archive/Old Ideas]].\n", encoding="utf-8")
    (vault / "Reading List.md").write_text("# Reading\n\n- Dune #books\n- [[Ideas]]\n",
                                           encoding="utf-8")
    (vault / "Archive").mkdir()
    (vault / "Archive" / "Old Ideas.md").write_text("# Old ideas\ngarden garden garden\n",
                                                    encoding="utf-8")
    return vault


@pytest.fixture
def vault(root, tmp_path):
    return Vault(root, history_dir=tmp_path / "history")


def test_obsidians_own_folders_are_never_read(vault):
    names = {vault.rel(p) for p in vault.note_paths()}
    assert names == {"Projects/Ideas.md", "Reading List.md", "Archive/Old Ideas.md"}


def test_a_note_reads_with_tags_links_and_version(vault, root):
    note = vault.read(root / "Projects" / "Ideas.md")
    assert note.rel == "Projects/Ideas.md" and note.title == "Ideas"
    assert note.frontmatter == {"tags": ["project"], "status": "open"}
    assert note.tags == ("project", "garden")
    assert [link.target for link in note.links] == ["Reading List", "Archive/Old Ideas"]
    assert len(note.version) == 16


def test_links_resolve_the_way_obsidian_resolves_them(tmp_path):
    root = tmp_path / "V"
    for rel in ("A/Note.md", "B/deep/Note.md", "B/deep/Here.md", "Top.md"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x", encoding="utf-8")
    vault = Vault(root, history_dir=tmp_path / "h")
    top, here = root / "Top.md", root / "B" / "deep" / "Here.md"
    assert vault.resolve("Note", top) == root / "A" / "Note.md"               # shortest path
    assert vault.resolve("Note", here) == root / "B" / "deep" / "Note.md"     # same folder first
    assert vault.resolve("deep/Note", top) == root / "B" / "deep" / "Note.md" # folder-qualified
    assert vault.resolve("A/Note.md", top) == root / "A" / "Note.md"
    assert vault.resolve("Missing", top) is None


def test_backlinks_find_every_note_that_links_here(vault, root):
    assert vault.backlinks(root / "Projects" / "Ideas.md") == ["Reading List.md"]
    assert vault.backlinks(root / "Reading List.md") == ["Projects/Ideas.md"]


def test_search_ranks_titles_then_tags_then_mentions(vault):
    # Both titles hold "ideas"; the list that only links to it comes last.
    assert [h.rel for h in vault.search("ideas")] == [
        "Projects/Ideas.md", "Archive/Old Ideas.md", "Reading List.md"]
    # A note tagged #garden outranks one that only says "garden" three times.
    garden = vault.search("garden")
    assert [h.rel for h in garden] == ["Projects/Ideas.md", "Archive/Old Ideas.md"]
    assert "garden" in garden[1].snippet


def test_search_needs_every_word(vault):
    assert [h.rel for h in vault.search("dune #books")] == ["Reading List.md"]
    assert vault.search("dune garden") == []


def test_the_daily_note_follows_obsidians_settings(vault, root):
    assert vault.daily_path(date(2026, 3, 2)) == root / "Daily" / "2026-03-02.md"


def test_without_settings_the_daily_note_is_an_iso_date_at_the_root(tmp_path):
    root = tmp_path / "Plain"
    root.mkdir()
    assert Vault(root, history_dir=tmp_path / "h").daily_path(date(2026, 3, 2)) == root / "2026-03-02.md"


def test_only_what_may_be_read_is_read(root, tmp_path):
    allowed = root / "Projects"
    vault = Vault(root, history_dir=tmp_path / "h", may_read=lambda p: p.is_relative_to(allowed))
    assert [h.rel for h in vault.search("garden")] == ["Projects/Ideas.md"]
    with pytest.raises(VaultError):
        vault.read(root / "Reading List.md")


# -- writing ----------------------------------------------------------------------------


def test_writing_over_a_note_changed_in_obsidian_is_refused(vault, root):
    path = root / "Reading List.md"
    seen = vault.read(path).version
    path.write_text("# Reading\n\n- Edited in Obsidian\n", encoding="utf-8")
    with pytest.raises(ConflictError, match="edited in Obsidian"):
        vault.write(path, "# Mine\n", expected=seen)
    assert "Edited in Obsidian" in path.read_text(encoding="utf-8")


def test_every_overwrite_keeps_the_previous_version_and_can_be_restored(vault, root):
    path = root / "Reading List.md"
    original = path.read_text(encoding="utf-8")
    vault.write(path, "# Replaced\n", expected=vault.read(path).version)
    [(version, _)] = vault.history(path)
    vault.restore(path, version)
    assert path.read_text(encoding="utf-8") == original
    assert len(vault.history(path)) == 2, "the replaced version was not kept in turn"


def test_history_is_bounded(vault, root, monkeypatch):
    monkeypatch.setattr(vault_module, "HISTORY_KEEP", 3)
    path = root / "Reading List.md"
    for number in range(6):
        vault.write(path, f"# Version {number}\n")
    assert len(vault.history(path)) == 3


def test_history_lives_outside_the_vault(vault, root):
    vault.write(root / "Reading List.md", "# New\n")
    assert not any(".protege" in str(p) for p in root.rglob("*"))
    assert vault.history_dir.is_relative_to(root.parent) and not vault.history_dir.is_relative_to(root)


def test_appending_leaves_the_frontmatter_byte_for_byte(vault, root):
    path = root / "Projects" / "Ideas.md"
    before = path.read_text(encoding="utf-8")
    vault.append(path, "- water the plan", "Ideas")
    after = path.read_text(encoding="utf-8")
    assert after.startswith(before.split("# Ideas")[0])
    assert "- water the plan" in after and after.count("status: open") == 1


def test_appending_creates_the_note_and_its_folders(vault, root):
    vault.append(root / "Daily" / "2026-03-02.md", "- started", "Log")
    assert (root / "Daily" / "2026-03-02.md").read_text(encoding="utf-8") == "## Log\n- started\n"


def test_an_append_racing_an_edit_is_refused(vault, root, monkeypatch):
    path = root / "Reading List.md"
    real_write = vault.write

    def edited_meanwhile(target, text, *, expected=None):
        path.write_text("changed underneath\n", encoding="utf-8")
        return real_write(target, text, expected=expected)

    monkeypatch.setattr(vault, "write", edited_meanwhile)
    with pytest.raises(ConflictError):
        vault.append(path, "- mine")
    assert path.read_text(encoding="utf-8") == "changed underneath\n"


def test_a_note_keeps_its_byte_order_mark(vault, root):
    path = root / "Bom.md"
    path.write_bytes("﻿# Title\n".encode("utf-8"))
    vault.append(path, "- more")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf# Title\n- more")


def test_creating_refuses_an_existing_note(vault, root):
    with pytest.raises(VaultError, match="already exists"):
        vault.create(root / "Reading List.md", "x")


@pytest.mark.parametrize("target", [
    ".obsidian/hack.md", ".trash/x.md", "Projects/.hidden/x.md", "What?.md", "A [b].md",
    "notes.txt", "../outside.md", "CON.md",
])
def test_a_note_cannot_be_written_where_it_does_not_belong(vault, target):
    with pytest.raises(VaultError):
        vault.write(target, "x")
