"""Persistence: atomicity, bootstrap, and refusal to guess at corrupt files."""

from __future__ import annotations

import json

import pytest

from akira import store
from akira.schemas import Manifest, SchemaError


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    return root


def test_bootstrap_creates_control_directory_and_defaults(vault):
    manifest, settings, personality = store.bootstrap_vault(vault)
    assert store.manifest_path(vault).is_file()
    assert store.settings_path(vault).is_file()
    assert store.personality_path(vault).is_file()
    assert store.tripwire_dir(vault).is_dir()
    assert manifest.unlocked_topics == ()
    assert settings.system_prompt == ""
    assert personality.traits


def test_bootstrap_leaves_existing_vault_content_alone(vault):
    note = vault / "Welcome.md"
    note.write_text("my notes", encoding="utf-8")
    (vault / "Attachments").mkdir()
    store.bootstrap_vault(vault)
    assert note.read_text(encoding="utf-8") == "my notes"
    assert (vault / "Attachments").is_dir()


def test_bootstrap_is_idempotent(vault):
    store.bootstrap_vault(vault)
    manifest = store.load_manifest(vault).with_unlocked("physics")
    store.save_manifest(vault, manifest)
    reloaded, _, _ = store.bootstrap_vault(vault)
    assert reloaded.unlocked_topics == ("physics",)


def test_missing_manifest_creates_a_fully_locked_one(vault):
    store.protege_dir(vault).mkdir(parents=True)
    manifest = store.load_manifest(vault)
    assert manifest.unlocked_topics == ()
    assert store.manifest_path(vault).is_file()


def test_corrupt_manifest_raises_rather_than_resetting(vault):
    # The critical distinction. "Absent" means create a locked manifest.
    # "Present but unreadable" means stop -- we do not know what is unlocked,
    # and quietly substituting an empty manifest would be indistinguishable
    # from a legitimate fully-locked state while erasing the audit history.
    store.protege_dir(vault).mkdir(parents=True)
    store.manifest_path(vault).write_text("{ not json", encoding="utf-8")
    with pytest.raises(store.StoreError):
        store.load_manifest(vault)


def test_empty_manifest_file_raises(vault):
    store.protege_dir(vault).mkdir(parents=True)
    store.manifest_path(vault).write_text("", encoding="utf-8")
    with pytest.raises(store.StoreError):
        store.load_manifest(vault)


def test_schema_invalid_manifest_raises(vault):
    store.protege_dir(vault).mkdir(parents=True)
    store.manifest_path(vault).write_text(json.dumps({"unlocked_topics": ["BAD ID"]}), encoding="utf-8")
    with pytest.raises(SchemaError):
        store.load_manifest(vault)


def test_bootstrap_surfaces_schema_errors_with_recovery_hint(vault):
    store.protege_dir(vault).mkdir(parents=True)
    store.manifest_path(vault).write_text(json.dumps({"trust_tier": 9}), encoding="utf-8")
    with pytest.raises(SchemaError, match=r"\.bak"):
        store.bootstrap_vault(vault)


def test_write_is_atomic_and_leaves_no_temp_files(vault):
    store.bootstrap_vault(vault)
    for _ in range(5):
        store.save_manifest(vault, store.load_manifest(vault).with_unlocked("physics"))
    leftovers = list(store.protege_dir(vault).glob("*.tmp"))
    assert leftovers == []


def test_write_rotates_one_backup_generation(vault):
    store.bootstrap_vault(vault)
    store.save_manifest(vault, Manifest.initial().with_unlocked("first"))
    store.save_manifest(vault, Manifest.initial().with_unlocked("second"))
    backup = store.manifest_path(vault).with_suffix(".json.bak")
    assert backup.is_file()
    assert json.loads(backup.read_text(encoding="utf-8"))["unlocked_topics"] == ["first"]
    assert store.load_manifest(vault).unlocked_topics == ("second",)


def test_bootstrap_rejects_missing_vault(tmp_path):
    with pytest.raises(store.StoreError):
        store.bootstrap_vault(tmp_path / "does-not-exist")


def test_bootstrap_rejects_file_as_vault(tmp_path):
    target = tmp_path / "afile"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(store.StoreError):
        store.bootstrap_vault(target)


def test_saved_json_is_human_readable(vault):
    # The vault is a plain directory the user is expected to be able to inspect
    # and hand-edit. Minified JSON would undercut that.
    store.bootstrap_vault(vault)
    text = store.manifest_path(vault).read_text(encoding="utf-8")
    assert "\n  " in text
    assert text.endswith("\n")
