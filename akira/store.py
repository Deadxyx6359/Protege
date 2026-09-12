"""Atomic JSON persistence for Akira's config files.

Every write goes to a temporary file in the same directory and is then moved
into place with `os.replace`, which is atomic on both NTFS and POSIX. The vault
is a directory a user may have open in Obsidian, in a file sync tool, or in a
text editor; a half-written `manifest.json` observed by any of those is a
corrupt lock state.

A single `.bak` generation is kept for each file. Not a backup system -- a way
to recover from one bad write without needing one.

Reads are strict. A file that exists but does not parse raises. Callers must not
substitute a permissive default; `bootstrap_vault` distinguishes "absent, so
create the initial state" from "present but broken, so stop".
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .schemas import Manifest, Personality, SchemaError, Settings

PROTEGE_DIR = ".protege"
MANIFEST_NAME = "manifest.json"
SETTINGS_NAME = "settings.json"
PERSONALITY_NAME = "personality.json"
TRIPWIRE_DIR = "tripwires"


class StoreError(RuntimeError):
    """Disk-level failure reading or writing a Akira file."""


def protege_dir(vault: Path) -> Path:
    return Path(vault) / PROTEGE_DIR


def manifest_path(vault: Path) -> Path:
    return protege_dir(vault) / MANIFEST_NAME


def settings_path(vault: Path) -> Path:
    return protege_dir(vault) / SETTINGS_NAME


def personality_path(vault: Path) -> Path:
    return protege_dir(vault) / PERSONALITY_NAME


def tripwire_dir(vault: Path) -> Path:
    return protege_dir(vault) / TRIPWIRE_DIR


# ---------------------------------------------------------------------------
# Raw JSON I/O
# ---------------------------------------------------------------------------


def read_json(path: Path) -> Any | None:
    """Parse `path`, or return None if it does not exist.

    None means absent. It never means "empty" or "unreadable" -- both of those
    raise, because a caller that treats an unreadable manifest as an absent one
    would silently reset the lock state.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StoreError(f"cannot read {path}: {exc}") from exc
    if not text.strip():
        raise StoreError(f"{path} is empty; refusing to treat an empty config as a default one")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise StoreError(f"{path} is not valid JSON: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    """Write `data` to `path` atomically, rotating one backup generation."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
        # Same directory as the target: os.replace is only atomic within a
        # filesystem, and a temp dir may be on another volume.
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if path.exists():
                backup = path.with_suffix(path.suffix + ".bak")
                try:
                    os.replace(path, backup)
                except OSError:
                    # A failed backup rotation must not block the write itself.
                    pass
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise StoreError(f"cannot write {path}: {exc}") from exc


def write_text(path: Path, text: str) -> None:
    """Atomic text write, for markdown notes and memory files."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise StoreError(f"cannot write {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Typed accessors
# ---------------------------------------------------------------------------


def load_manifest(vault: Path) -> Manifest:
    """Load the manifest.

    Absent -> the initial (fully locked) manifest, which is also written to
    disk so subsequent runs are stable. Present but invalid -> SchemaError
    propagates. The caller must surface that as a hard error that blocks chat
    rather than continuing with `Manifest.initial()`: silently substituting an
    empty manifest for a corrupt one would look identical to "everything is
    locked" while actually meaning "we have no idea what is unlocked", and the
    two must not be conflated in the audit history.
    """
    raw = read_json(manifest_path(vault))
    if raw is None:
        manifest = Manifest.initial()
        save_manifest(vault, manifest)
        return manifest
    return Manifest.from_json(raw)


def save_manifest(vault: Path, manifest: Manifest) -> None:
    write_json(manifest_path(vault), manifest.to_json())


def load_settings(vault: Path) -> Settings:
    raw = read_json(settings_path(vault))
    if raw is None:
        settings = Settings(vault_path=str(vault))
        save_settings(vault, settings)
        return settings
    return Settings.from_json(raw)


def save_settings(vault: Path, settings: Settings) -> None:
    write_json(settings_path(vault), settings.to_json())


def load_personality(vault: Path) -> Personality:
    from .personality.defaults import default_personality

    raw = read_json(personality_path(vault))
    if raw is None:
        personality = default_personality()
        save_personality(vault, personality)
        return personality
    return Personality.from_json(raw)


def save_personality(vault: Path, personality: Personality) -> None:
    write_json(personality_path(vault), personality.to_json())


# ---------------------------------------------------------------------------
# First-run bootstrap
# ---------------------------------------------------------------------------


def bootstrap_vault(vault: Path) -> tuple[Manifest, Settings, Personality]:
    """Create the `.protege` control directory if absent and load all config.

    Creates nothing outside `.protege` and `projects/` -- an existing Obsidian
    vault full of the user's notes is left exactly as it is.
    """
    vault = Path(vault)
    if not vault.exists():
        raise StoreError(f"vault directory does not exist: {vault}")
    if not vault.is_dir():
        raise StoreError(f"vault path is not a directory: {vault}")

    protege_dir(vault).mkdir(parents=True, exist_ok=True)
    tripwire_dir(vault).mkdir(parents=True, exist_ok=True)
    (vault / "projects").mkdir(parents=True, exist_ok=True)
    (vault / "global" / "notes").mkdir(parents=True, exist_ok=True)

    try:
        manifest = load_manifest(vault)
        settings = load_settings(vault)
        personality = load_personality(vault)
    except SchemaError as exc:
        raise SchemaError(
            f"{exc}\n\nAkira will not start with an unreadable configuration. "
            f"Inspect the files in {protege_dir(vault)} -- a '.bak' copy of the previous "
            "version of each is kept alongside it."
        ) from exc
    return manifest, settings, personality
