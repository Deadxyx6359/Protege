"""The rename to Akira: the settings folder moves to its new name once, whole,
and is never lost on the way; saved credentials keep the seal they were made with.
"""

from __future__ import annotations

from pathlib import Path

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


def test_a_new_folder_with_settings_wins_and_the_old_one_is_left_alone(home):
    old = old_settings(home)
    (home / "Akira").mkdir()
    (home / "Akira" / "config.json").write_text("{}", encoding="utf-8")
    assert migrate_config() == "" and config_dir() == home / "Akira" and old.exists()


def qt_cache(home):
    """What any run of the window leaves in the new folder by itself."""
    compiled = home / "Akira" / config.QT_FOLDER / "cache" / "qmlcache" / "main.qmlc"
    compiled.parent.mkdir(parents=True)
    compiled.write_bytes(b"compiled")
    return compiled


def test_the_windows_own_cache_does_not_hide_the_old_folder(home):
    # Found on the person's machine: a test run had made Akira\Akira\cache, and
    # the next start would have opened an empty settings folder.
    old = old_settings(home)
    qt_cache(home)
    assert config_dir() == old, "Qt's cache was taken for settings"


def test_the_move_carries_the_cache_along(home):
    old = old_settings(home)
    compiled = qt_cache(home)
    assert migrate_config().startswith("Moved the settings folder")
    new = home / "Akira"
    assert config_dir() == new and not old.exists()
    assert (new / "permissions.json").read_text(encoding="utf-8") == '{"grants": []}'
    assert (new / "secrets" / "canvas_token.dpapi").read_bytes() == b"sealed"
    assert compiled.read_bytes() == b"compiled"


def test_if_the_move_fails_the_cache_goes_back_and_the_next_try_works(home, monkeypatch):
    old = old_settings(home)
    compiled = qt_cache(home)
    real = config.os.rename

    def old_app_open(source, target):
        if Path(source) == old:
            raise PermissionError("the old app has it open")
        return real(source, target)

    monkeypatch.setattr(config.os, "rename", old_app_open)
    assert "could not be moved" in migrate_config()
    assert config_dir() == old and compiled.read_bytes() == b"compiled"
    assert not (old / config.QT_FOLDER).exists(), "the cache was left in the settings"

    monkeypatch.setattr(config.os, "rename", real)
    assert migrate_config().startswith("Moved the settings folder")
    assert (home / "Akira" / "permissions.json").exists() and compiled.read_bytes() == b"compiled"


def test_an_empty_new_folder_does_not_hide_the_old_one(home):
    old = old_settings(home)
    (home / "Akira").mkdir()
    assert config_dir() == old
    assert migrate_config().startswith("Moved the settings folder")
    assert (home / "Akira" / "permissions.json").exists()


def test_qt_names_its_cache_folder_as_the_move_expects():
    engine = pytest.importorskip("akira.ui.engine")
    named = {}

    class Recorder:
        def __getattr__(self, name):
            return lambda value: named.__setitem__(name, value)

    engine.configure_application(Recorder())
    # Qt's cache goes in %LOCALAPPDATA%\<organisation>\<application>.
    assert named["setOrganizationName"] == config.APP_DIR
    assert named["setApplicationName"] == config.QT_FOLDER


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
