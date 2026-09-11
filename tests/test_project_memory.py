"""Memory per project (B6): a conversation remembers which project it was held
in, and what is distilled from it is proposed under that project's name.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from protege.core.brain import Vault
from protege.core.brain.distil import Distiller, PendingStore
from protege.core.conversation import Conversation
from protege.core.conversations import ConversationStore
from protege.core.projects import ProjectStore
from protege.models.scripted import ScriptedBackend


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


class Router:
    def __init__(self, *replies):
        self.backend = ScriptedBackend(replies=replies)

    @contextmanager
    def acquire(self, route):
        yield self.backend


@pytest.fixture
def vault_root(tmp_path):
    root = tmp_path / "Vault"
    (root / ".obsidian").mkdir(parents=True)
    return root


@pytest.fixture
def projects(tmp_path):
    return ProjectStore(tmp_path / "projects")


def conversation(project: str = "") -> Conversation:
    held = Conversation(project=project)
    held.add("user", "I got plot 14 at the allotment.")
    held.add("assistant", "Congratulations.")
    return held


def test_a_conversation_keeps_the_project_it_was_held_in(tmp_path):
    store = ConversationStore(tmp_path / "cfg" / "conversations")
    held = conversation("0123456789abcdef")
    store.save(held)
    assert store.load(held.id).project == "0123456789abcdef"


def test_a_conversation_saved_before_projects_has_none(tmp_path):
    directory = tmp_path / "cfg" / "conversations"
    directory.mkdir(parents=True)
    (directory / "a1b2c3d4.json").write_text(json.dumps({
        "id": "a1b2c3d4", "title": "Old",
        "messages": [{"role": "user", "text": "hello"}]}), encoding="utf-8")
    assert ConversationStore(directory).load("a1b2c3d4").project == ""


def test_what_a_project_conversation_teaches_is_proposed_under_that_project(vault_root,
                                                                         projects, tmp_path):
    garden = projects.create("Garden")
    store = ConversationStore(tmp_path / "cfg" / "conversations")
    store.save(conversation(garden.id))

    Distiller(Router("## Allotment\n- Plot 14.\n"), Vault(vault_root), projects=projects).run()
    [proposal] = PendingStore().all()
    assert proposal.target == "Memory/Garden/Allotment.md"
    assert proposal.sources[0]["project"] == "Garden"


def test_a_conversation_outside_any_project_goes_to_the_shared_memory(vault_root, projects,
                                                                     tmp_path):
    ConversationStore(tmp_path / "cfg" / "conversations").save(conversation())
    Distiller(Router("## Allotment\n- Plot 14.\n"), Vault(vault_root), projects=projects).run()
    [proposal] = PendingStore().all()
    assert proposal.target == "Memory/Allotment.md"


def test_a_removed_project_does_not_strand_its_conversations(vault_root, projects, tmp_path):
    garden = projects.create("Garden")
    ConversationStore(tmp_path / "cfg" / "conversations").save(conversation(garden.id))
    projects.remove(garden.id)
    Distiller(Router("## Allotment\n- Plot 14.\n"), Vault(vault_root), projects=projects).run()
    [proposal] = PendingStore().all()
    assert proposal.target == "Memory/Allotment.md"
