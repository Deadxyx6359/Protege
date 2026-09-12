"""The rename to Akira: the settings folder moves to its new name once, whole,
and is never lost on the way; saved credentials keep the seal they were made with.
"""

from __future__ import annotations

import pytest

from akira.core import config
from akira.core.config import config_dir, migrate_config
from akira.core.permissions import secrets


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("AKIRA_CONFIG_DIR", raising=False)
    monkeypatch.delenv("PROTEGE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def old_settings(home):
    old = home / "Protege"
    (old / "secrets").mkdir(parents=True)
    (old / "permissions.json").write_text('{"grants": []}', encoding="utf-8")
    (old / "secrets" / "canvas_token.dpapi").write_bytes(b"sealed")
    return old


def test_until_it_moves_the_old_folder_is_used_where_it_is(home):
    old = old_settings(home)
    assert config_dir() == old, "an empty new folder would look like everything had been lost"


def test_the_folder_moves_whole_and_only_once(home):
    old = old_settings(home)
    assert migrate_config().startswith("Moved the settings folder")
    new = home / "Akira"
    assert config_dir() == new and not old.exists()
    assert (new / "permissions.json").read_text(encoding="utf-8") == '{"grants": []}'
    assert (new / "secrets" / "canvas_token.dpapi").read_bytes() == b"sealed"
    assert migrate_config() == "", "it tried to move twice"


def test_a_folder_that_cannot_move_stays_in_use(home, monkeypatch):
    old = old_settings(home)

    def in_use(source, target):
        raise PermissionError("the old app has it open")

    monkeypatch.setattr(config.os, "rename", in_use)
    assert "could not be moved" in migrate_config()
    assert config_dir() == old and (old / "permissions.json").exists()


def test_a_new_folder_wins_and_the_old_one_is_left_alone(home):
    old = old_settings(home)
    (home / "Akira").mkdir()
    assert migrate_config() == "" and config_dir() == home / "Akira" and old.exists()


def test_a_fresh_install_has_nothing_to_move(home):
    assert migrate_config() == "" and config_dir() == home / "Akira"


def test_a_folder_named_by_hand_is_never_moved(home, monkeypatch, tmp_path):
    old_settings(home)
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "elsewhere"))
    assert config_dir() == tmp_path / "elsewhere" and migrate_config() == ""
    assert (home / "Protege").exists()


def test_saved_credentials_keep_the_seal_they_were_made_with():
    # Every secret saved before the rename was encrypted with this. A sweep that
    # "fixes" the old name here makes all of them unreadable.
    assert secrets._ENTROPY == b"protege.secrets.v1"
