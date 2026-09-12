"""Sweeping the indexes (B4): the stored copy of a note goes when the grants stop
covering it, not at the next search, and goes from the file's bytes, not just
from its tables; a grant made in any project keeps it; an index held open is
cleared in place; and an index that cannot say what it holds is not kept.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3

import pytest

from akira.core.brain import Index, Vault
from akira.core.brain.corpora import ConversationArchive
from akira.core.brain.index import anywhere, sweep
from akira.core.config import config_dir
from akira.core.permissions import Policy


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def root(tmp_path):
    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    for rel, text in (("Projects/Garden.md", "Tomatoes in June."),
                      ("Private/Diary.md", "Secret plans for the orchard.")):
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_text(text, encoding="utf-8")
    return vault


def indexes():
    folder = config_dir() / "index"
    return sorted(folder.glob("*.sqlite")) if folder.is_dir() else []


def indexed(path) -> list[str]:
    with contextlib.closing(sqlite3.connect(path)) as db:
        return sorted(rel for (rel,) in db.execute("SELECT rel FROM notes"))


def built(root) -> None:
    Index(Vault(root)).refresh()


def granted(capability, *scopes) -> Policy:
    policy = Policy()
    policy.grant(capability, tuple(str(s) for s in scopes))
    return policy


def test_a_covered_index_is_left_alone(root):
    built(root)
    report = sweep(anywhere(granted("vault.read", root)))
    assert (report.removed, report.emptied, report.dropped) == (0, 0, 0)
    assert indexed(indexes()[0]) == ["Private/Diary.md", "Projects/Garden.md"]


def test_revoking_the_grant_removes_the_stored_copy(root):
    built(root)
    report = sweep(anywhere(Policy()))
    assert report.removed == 1 and indexes() == []


def test_narrowing_the_grant_drops_only_what_it_no_longer_covers(root):
    built(root)
    report = sweep(anywhere(granted("vault.read", root / "Projects")))
    assert (report.removed, report.dropped) == (0, 1)
    [path] = indexes()
    assert indexed(path) == ["Projects/Garden.md"]
    # Deleted rows linger in a SQLite file's free pages unless overwritten.
    assert b"Secret plans" not in path.read_bytes(), "the dropped text is still in the file"


def test_a_grant_in_any_project_keeps_the_index(root):
    built(root)
    report = sweep(anywhere(Policy(), Policy(), granted("vault.read", root)))
    assert report.removed == 0 and len(indexes()) == 1


def test_an_index_held_open_is_cleared_in_place(root):
    built(root)
    [path] = indexes()
    holder = sqlite3.connect(path)   # a search still running, say
    try:
        report = sweep(anywhere(Policy()))
    finally:
        holder.close()
    # Windows will not delete an open file; elsewhere it goes at once.
    assert report.removed + report.emptied == 1 and report.failed == []
    if path.exists():
        assert b"Secret plans" not in path.read_bytes()
        with contextlib.closing(sqlite3.connect(path)) as db:
            assert list(db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")) == []
        assert sweep(anywhere(Policy())).removed == 1, "the emptied file was not deleted later"


def test_past_conversations_go_with_their_permission(tmp_path):
    folder = tmp_path / "cfg" / "conversations"
    folder.mkdir(parents=True)
    (folder / "a1b2c3d4.json").write_text(json.dumps({
        "id": "a1b2c3d4", "title": "Garden",
        "messages": [{"role": "user", "text": "When do tomatoes go in?"},
                     {"role": "assistant", "text": "In June."}]}), encoding="utf-8")
    Index(ConversationArchive()).refresh()
    assert sweep(anywhere(granted("memory.read"))).removed == 0
    assert sweep(anywhere(Policy())).removed == 1 and indexes() == []


def test_an_index_that_cannot_say_what_it_holds_is_removed(root):
    folder = config_dir() / "index"
    folder.mkdir(parents=True)
    with contextlib.closing(sqlite3.connect(folder / "vault-old.sqlite")) as db, db:
        db.execute("CREATE TABLE notes (rel TEXT)")
        db.execute("INSERT INTO notes VALUES ('Garden.md')")
    (folder / "vault-broken.sqlite").write_bytes(b"not a database at all" * 20)
    report = sweep(anywhere(granted("vault.read", root)))
    assert report.removed == 2 and indexes() == []


def test_a_swept_index_is_rebuilt_when_it_is_wanted_again(root):
    built(root)
    sweep(anywhere(Policy()))
    index = Index(Vault(root))
    assert index.refresh()["added"] == 2
    assert index.search("tomatoes")[0].rel == "Projects/Garden.md"
