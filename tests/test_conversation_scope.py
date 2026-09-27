"""Which past conversations a search reaches: the open project's and the person's own.

Found by testing project switching with the real models: with the Car project
open, "where do the tomatoes go?" was answered "bed A", from a conversation
held in the Garden project. A conversation held in a project draws on that
project's folders, so it is kept to the project as they are.
"""

from __future__ import annotations

import json

import pytest

from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import ToolContext, default_registry


@pytest.fixture
def chats(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))
    folder = tmp_path / "cfg" / "conversations"
    folder.mkdir(parents=True)
    for cid, project, answer in (
            ("a1a1a1a1a1a1a1a1", "garden", "Tomatoes go in bed A."),
            ("b2b2b2b2b2b2b2b2", "car", "Tomatoes are not a car part."),
            ("c3c3c3c3c3c3c3c3", "", "Tomatoes like sun.")):
        (folder / f"{cid}.json").write_text(json.dumps({
            "id": cid, "title": f"Tomatoes ({project or 'personal'})", "project": project,
            "messages": [{"id": "m1", "role": "user", "text": "Where do the tomatoes go?",
                          "created": 0, "error": False},
                         {"id": "m2", "role": "assistant", "text": answer,
                          "created": 0, "error": False}]}), encoding="utf-8")
    return tmp_path


def search(tmp_path, project):
    policy = Policy()
    policy.grant("memory.read")
    context = ToolContext(policy=policy, audit=AuditLog(tmp_path / "a.jsonl"),
                          secrets=SecretStore(tmp_path / "s"),
                          extra={"project": project} if project is not None else {})
    result = default_registry().invoke("search_conversations", {"query": "tomatoes"}, context)
    assert result.ok, result.content
    return result.content


def test_a_project_reaches_its_own_conversations_and_personal_ones(chats):
    found = search(chats, "garden")
    assert "bed A" in found and "like sun" in found
    assert "not a car part" not in found


def test_another_project_does_not_reach_them(chats):
    found = search(chats, "car")
    assert "bed A" not in found and "not a car part" in found


def test_outside_any_project_only_personal_conversations_are_reached(chats):
    for project in ("", None):  # personal chat, and a scheduled job, which has none
        found = search(chats, project)
        assert "like sun" in found
        assert "bed A" not in found and "not a car part" not in found
