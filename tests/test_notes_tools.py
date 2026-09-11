"""The vault tools (B2): the permission each needs, read-before-write, the daily
note, undo, and the paths this code works out for itself.
"""

from __future__ import annotations

from datetime import date

import pytest

from protege.core.permissions import AuditLog, Policy, SecretStore
from protege.core.tools import ToolContext, default_registry


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def root(tmp_path):
    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "daily-notes.json").write_text('{"folder": "Daily"}', encoding="utf-8")
    (vault / "Projects").mkdir()
    (vault / "Projects" / "Garden.md").write_text("# Garden\nPlant #tomatoes. See [[Seeds]].\n",
                                                  encoding="utf-8")
    (vault / "Seeds.md").write_text("# Seeds\nTomato seeds for the [[Garden]].\n", encoding="utf-8")
    return vault


def ctx(tmp_path, *grants):
    policy = Policy()
    for capability, scope in grants:
        policy.grant(capability, (str(scope),))
    return ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"), actor="tester")


def call(name, arguments, context):
    return default_registry().invoke(name, arguments, context)


def version_from(result) -> str:
    return result.data["version"]


def test_notes_need_vault_permission_not_file_permission(root):
    files = Policy()
    files.grant("files.read", (str(root),))
    assert "read_note" not in {t.name for t in default_registry().available(files)}
    notes = Policy()
    notes.grant("vault.read", (str(root),))
    names = {t.name for t in default_registry().available(notes)}
    assert {"search_notes", "read_note", "note_history"} <= names
    assert not {"write_note", "append_to_note", "add_to_daily_note", "restore_note"} & names


def test_writing_notes_does_not_stop_to_ask_because_it_can_be_undone():
    tools = {t.name: t for t in default_registry()._tools.values()}
    for name in ("write_note", "append_to_note", "add_to_daily_note", "restore_note"):
        assert tools[name].reversible, name


def test_search_reaches_only_the_granted_folder(root, tmp_path):
    """The vault root is above the grant; the notes above it are not read."""
    context = ctx(tmp_path, ("vault.read", root / "Projects"))
    result = call("search_notes", {"vault": str(root / "Projects"), "query": "tomato"}, context)
    assert result.ok and "Projects/Garden.md" in result.content
    assert "Seeds.md" not in result.content


def test_reading_a_note_shows_links_backlinks_and_version(root, tmp_path):
    result = call("read_note", {"path": str(root / "Projects" / "Garden.md")},
                  ctx(tmp_path, ("vault.read", root)))
    assert result.ok
    assert "Tags: #tomatoes" in result.content
    assert "Links to: Seeds.md" in result.content and "Linked from: Seeds.md" in result.content
    assert f"version {version_from(result)}" in result.content


def test_replacing_a_note_needs_the_version_that_was_read(root, tmp_path):
    context = ctx(tmp_path, ("vault.read", root), ("vault.write", root))
    path = str(root / "Seeds.md")
    blind = call("write_note", {"path": path, "content": "# Mine\n"}, context)
    assert not blind.ok and "read_note" in blind.content

    seen = version_from(call("read_note", {"path": path}, context))
    replaced = call("write_note", {"path": path, "content": "# Mine\n", "version": seen}, context)
    assert replaced.ok and "restore_note" in replaced.content


def test_a_stale_version_is_refused_with_the_reason(root, tmp_path):
    context = ctx(tmp_path, ("vault.read", root), ("vault.write", root))
    path = root / "Seeds.md"
    seen = version_from(call("read_note", {"path": str(path)}, context))
    path.write_text("# Seeds\nEdited on the phone.\n", encoding="utf-8")
    result = call("write_note", {"path": str(path), "content": "# Mine", "version": seen}, context)
    assert not result.ok and "changed after it was read" in result.content
    assert "Edited on the phone" in path.read_text(encoding="utf-8")


def test_a_new_note_is_created_without_a_version(root, tmp_path):
    context = ctx(tmp_path, ("vault.write", root))
    result = call("write_note", {"path": str(root / "Projects" / "Plan.md"), "content": "# Plan\n"},
                  context)
    assert result.ok and (root / "Projects" / "Plan.md").exists()


def test_appending_to_a_note(root, tmp_path):
    context = ctx(tmp_path, ("vault.write", root))
    result = call("append_to_note", {"path": str(root / "Seeds.md"), "text": "- basil",
                                     "heading": "To buy"}, context)
    assert result.ok and "under “To buy”" in result.content
    assert (root / "Seeds.md").read_text(encoding="utf-8").endswith("## To buy\n- basil\n")


def test_the_daily_note_goes_where_obsidian_expects_it(root, tmp_path):
    context = ctx(tmp_path, ("vault.write", root))
    result = call("add_to_daily_note", {"vault": str(root), "text": "- watered", "heading": "Log"},
                  context)
    assert result.ok
    today = root / "Daily" / f"{date.today().isoformat()}.md"
    assert today.read_text(encoding="utf-8") == "## Log\n- watered\n"


def test_the_daily_note_cannot_escape_the_granted_folder(root, tmp_path):
    """The folder given was checked; the daily note's own path must be too."""
    context = ctx(tmp_path, ("vault.write", root / "Projects"))
    result = call("add_to_daily_note", {"vault": str(root / "Projects"), "text": "- x"}, context)
    assert not result.ok and "outside what may be written" in result.content
    assert not (root / "Daily").exists()


def test_history_and_restore_through_the_tools(root, tmp_path):
    context = ctx(tmp_path, ("vault.read", root), ("vault.write", root))
    path = str(root / "Seeds.md")
    original = (root / "Seeds.md").read_text(encoding="utf-8")
    seen = version_from(call("read_note", {"path": path}, context))
    call("write_note", {"path": path, "content": "# Gone\n", "version": seen}, context)

    history = call("note_history", {"path": path}, context)
    assert history.ok and history.data["versions"]
    restored = call("restore_note", {"path": path, "version": history.data["versions"][0]}, context)
    assert restored.ok
    assert (root / "Seeds.md").read_text(encoding="utf-8") == original


def test_the_gatherer_can_search_and_read_notes():
    from protege.core.agents.roles import ANALYST, GATHERER

    assert {"search_notes", "read_note"} <= set(GATHERER.tools)
    assert "read_note" in ANALYST.tools
