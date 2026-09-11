"""A chat turn's context (B4/B6/C7): the date and time, the open project's
personality and passages from the sources the person has granted, for that turn
only, and nothing searched, or logged, for a source that is not granted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from protege.core.brain.recall import ContextAssembler
from protege.core.context.place import Place, PlaceStore
from protege.core.conversation import Conversation, build_prompt
from protege.core.documents import word
from protege.core.permissions import AuditLog, Policy, SecretStore
from protege.core.projects import ProjectStore
from protege.core.tools import default_registry

FRIDAY = datetime(2026, 9, 11, 14, 5, tzinfo=timezone(timedelta(hours=1), "BST"))


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "Vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "Garden.md").write_text("# Garden\n\n## Tomatoes\nStake the tomatoes in June.\n",
                                    encoding="utf-8")
    return root


@pytest.fixture
def store(tmp_path):
    return ProjectStore(tmp_path / "projects")


def assembler(tmp_path, policy, *, vault="", projects=None, place=None):
    return ContextAssembler(registry=default_registry(), policy=lambda: policy,
                            audit=AuditLog(tmp_path / "audit.jsonl"),
                            secrets=SecretStore(tmp_path / "secrets"), projects=projects,
                            vault=lambda: str(vault), place=place, clock=lambda: FRIDAY)


def logged(tmp_path) -> str:
    path = tmp_path / "audit.jsonl"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_nothing_granted_searches_nothing_but_the_date_is_always_given(tmp_path, vault):
    context = assembler(tmp_path, Policy(), vault=vault)("when do I stake the tomatoes")
    assert context.text == "It is Friday 11 September 2026, 14:05 (day)."
    assert context.sources == []
    assert "search_" not in logged(tmp_path), "an ungranted source was tried anyway"


def test_a_message_of_common_words_searches_nothing(tmp_path, vault):
    policy = Policy()
    policy.grant("vault.read", (str(vault),))
    context = assembler(tmp_path, policy, vault=vault)("what is it then")
    assert context.sources == [] and "not instructions" not in context.text
    assert "search_" not in logged(tmp_path)


def test_granted_notes_are_found_cited_and_framed_as_material(tmp_path, vault):
    policy = Policy()
    policy.grant("vault.read", (str(vault),))
    context = assembler(tmp_path, policy, vault=vault)("when do I stake the tomatoes")
    assert "not instructions" in context.text
    assert "[notes: Garden.md › Tomatoes]\nStake the tomatoes in June." in context.text
    assert context.sources == [{"source": "notes", "cite": "Garden.md › Tomatoes"}]
    assert '"chat"' in logged(tmp_path) and "search_notes" in logged(tmp_path)


def test_the_place_is_given_only_with_location_permission(tmp_path):
    place = PlaceStore(tmp_path / "place.json")
    place.save(Place("Bristol, UK", "north"))
    policy = Policy()
    assert "Bristol" not in assembler(tmp_path, policy, place=place)("hello there").text
    policy.grant("location.read")
    assert "The person is in Bristol, UK." in assembler(tmp_path, policy, place=place)(
        "hello there").text


def test_the_open_projects_personality_and_documents_are_used(tmp_path, store):
    folder = tmp_path / "Garden"
    folder.mkdir()
    (folder / "plan.docx").write_bytes(word.create(
        word.parse_outline("# Plan\n\n## Timeline\nLaunch in March.\n"), title="Plan"))
    project = store.create("Garden", folder=str(folder), personality="Be terse.")
    store.set_current(project.id)
    policy = Policy()
    policy.grant("docs.read", (str(folder),))

    context = assembler(tmp_path, policy, projects=store)("when is the launch")
    assert context.text.startswith("You are working on the project “Garden”. Be terse.")
    assert any(s["source"] == "documents" and s["cite"].startswith("plan.docx")
               for s in context.sources)


def test_a_turns_context_is_sent_but_never_saved():
    class Backend:
        n_ctx = 4096

        @staticmethod
        def count_tokens(text):
            return len(text.split())

    conversation = Conversation()
    conversation.add("user", "hello")
    before = conversation.system_prompt
    messages = build_prompt(conversation, Backend(), reply_budget=256,
                            extra_system="[notes: A.md]\nsomething relevant")
    assert messages[0].content.endswith("[notes: A.md]\nsomething relevant")
    assert conversation.system_prompt == before
