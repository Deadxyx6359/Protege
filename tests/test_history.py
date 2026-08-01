"""Keeping transcripts, and searching the ones that were kept.

Before this, a transcript was always destroyed once consolidation was
confirmed. That is a defensible privacy default and it was also the *only*
behaviour, so "what did I ask about Thevenin last week" had no answer and no
way to get one. The setting exists to make it a choice.

The property worth guarding is that the choice is honoured in every place a
transcript can die -- session end, the holding sweep, and a discarded
consolidation. A retention setting obeyed in two of three places is worse than
none, because it reads as kept and behaves as deleted.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from protege import store
from protege.history import load_all, search, summarize
from protege.memory.consolidate import Consolidator
from protege.projects import ensure_project, get_project
from protege.schemas import Manifest, Settings


def vault_with(tmp_path, *, keep: bool) -> tuple[Path, Settings]:
    vault = tmp_path / "vault"
    vault.mkdir()
    store.bootstrap_vault(vault)
    ensure_project(vault, "default")
    settings = Settings()
    settings = replace(settings, memory=replace(settings.memory, keep_transcripts=keep))
    return vault, settings


def consolidator(vault: Path, settings: Settings) -> Consolidator:
    return Consolidator(vault, "default", Manifest.initial(), settings, None, None)


def held(vault: Path, name: str = "s1") -> Path:
    """Put a transcript in the holding area the way a session end would."""
    directory = get_project(vault, "default").memory_holding_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.transcript.md"
    path.write_text(
        "---\nkind: held-transcript\nsession: " + name +
        "\nheld_at: '2026-07-01T10:00:00+00:00'\n---\n\n"
        "USER: how do I find the thevenin equivalent\nPROTEGE: short the sources.\n",
        encoding="utf-8",
    )
    return path


def archive_of(vault: Path) -> Path:
    return get_project(vault, "default").memory_archive_dir


# --- retiring a transcript --------------------------------------------------------


def test_a_transcript_is_deleted_when_keeping_is_off(tmp_path):
    vault, settings = vault_with(tmp_path, keep=False)
    path = held(vault)
    consolidator(vault, settings)._retire_transcript(path)

    assert not path.exists()
    assert not archive_of(vault).exists() or not list(archive_of(vault).glob("*.md"))


def test_a_transcript_is_archived_when_keeping_is_on(tmp_path):
    vault, settings = vault_with(tmp_path, keep=True)
    path = held(vault)
    result = consolidator(vault, settings)._retire_transcript(path)

    assert not path.exists(), "it should move, not copy"
    assert result is not None and result.exists()
    assert result.parent == archive_of(vault)


def test_the_holding_sweep_honours_the_setting_too(tmp_path):
    """The place this would most plausibly have been forgotten.

    Session end archives, then a week later the sweep deletes anyway -- the
    setting would read as kept and behave as deleted.
    """
    vault, settings = vault_with(tmp_path, keep=True)
    settings = replace(settings, memory=replace(settings.memory, holding_days=0))
    path = held(vault)

    swept = consolidator(vault, settings).sweep_holding(now=10**12)
    assert swept == [path]
    assert not path.exists()
    assert len(list(archive_of(vault).glob("*.md"))) == 1


def test_the_sweep_still_deletes_when_keeping_is_off(tmp_path):
    vault, settings = vault_with(tmp_path, keep=False)
    settings = replace(settings, memory=replace(settings.memory, holding_days=0))
    path = held(vault)

    consolidator(vault, settings).sweep_holding(now=10**12)
    assert not path.exists()
    assert not list(archive_of(vault).glob("*.md")) if archive_of(vault).is_dir() else True


def test_a_name_clash_in_the_archive_does_not_overwrite(tmp_path):
    vault, settings = vault_with(tmp_path, keep=True)
    con = consolidator(vault, settings)
    con._retire_transcript(held(vault, "same"))
    con._retire_transcript(held(vault, "same"))
    assert len(list(archive_of(vault).glob("*.md"))) == 2


def test_retiring_a_missing_file_is_harmless(tmp_path):
    vault, settings = vault_with(tmp_path, keep=True)
    assert consolidator(vault, settings)._retire_transcript(None) is None
    assert consolidator(vault, settings)._retire_transcript(tmp_path / "nope.md") is None


# --- reading them back --------------------------------------------------------------


def test_archived_transcripts_are_listed_with_their_metadata(tmp_path):
    vault, settings = vault_with(tmp_path, keep=True)
    consolidator(vault, settings)._retire_transcript(held(vault, "s1"))

    found = load_all(vault)
    assert len(found) == 1
    assert found[0].project == "default"
    assert found[0].session == "s1"
    assert "thevenin" in found[0].body
    assert "held-transcript" not in found[0].body, "frontmatter should be stripped"


def test_search_is_case_folded_substring(tmp_path):
    vault, settings = vault_with(tmp_path, keep=True)
    consolidator(vault, settings)._retire_transcript(held(vault))
    found = load_all(vault)

    assert search(found, "THEVENIN") == found
    assert search(found, "") == found
    assert search(found, "kirchhoff") == []


def test_a_damaged_archive_file_does_not_break_the_listing(tmp_path):
    vault, settings = vault_with(tmp_path, keep=True)
    consolidator(vault, settings)._retire_transcript(held(vault))
    (archive_of(vault) / "broken.md").write_text("---\nnot: [valid\n", encoding="utf-8")

    assert len(load_all(vault)) == 2, "one good, one salvaged as raw text"


def test_the_summary_explains_an_empty_archive_differently_by_setting():
    assert "not being kept" in summarize(0, 0, enabled=False)
    assert "No transcripts archived yet" in summarize(0, 0, enabled=True)
    assert "3 transcript(s) archived" in summarize(3, 3, enabled=True)
    assert "1 of 3" in summarize(3, 1, enabled=True)


def test_nothing_is_listed_before_anything_is_archived(tmp_path):
    vault, _ = vault_with(tmp_path, keep=True)
    assert load_all(vault) == []


# --- the window ---------------------------------------------------------------------


def test_the_history_window_lists_and_filters(clean_root, tmp_path):
    from protege.ui.history_window import HistoryWindow

    vault, settings = vault_with(tmp_path, keep=True)
    consolidator(vault, settings)._retire_transcript(held(vault, "s1"))

    window = HistoryWindow(clean_root, vault, settings)
    try:
        window.update_idletasks()
        assert window.listbox.size() == 1

        window.query.insert(0, "thevenin")
        window._filter()
        assert window.listbox.size() == 1

        window.query.delete(0, "end")
        window.query.insert(0, "kirchhoff")
        window._filter()
        assert window.listbox.size() == 0
    finally:
        window.destroy()


def test_the_setting_is_off_by_default():
    """Not accumulating a record of everything ever said is the safe default."""
    assert Settings().memory.keep_transcripts is False
