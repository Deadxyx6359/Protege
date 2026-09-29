"""The library: documents added from the window, folders read in place, and the chat
answering about a chip from them."""

from __future__ import annotations

from pathlib import Path

import pytest

from akira.core.documents.library import Library
from akira.core.permissions import AuditLog, Policy, SecretStore

from tests.test_grounding import AKIRA, G4, QUESTION


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def sdk(tmp_path):
    root = tmp_path / "STM32Cube_FW_G4"
    for rel, text in G4.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def doc(folder, name, text="text"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


# -- the library itself -------------------------------------------------------------------------


def test_files_are_copied_into_the_projects_own_library(tmp_path):
    library = Library(tmp_path / "library")
    source = doc(tmp_path / "downloads", "notes.md")
    added, problems = library.add_files("p1", [source])
    assert problems == [] and added == [tmp_path / "library" / "p1" / "notes.md"]
    again, _ = library.add_files("p1", [source])
    assert again[0].name == "notes (2).md", "an added file replaced one already there"
    assert source.exists(), "the person's own file was moved"
    assert [e.name for e in library.entries("p1")] == ["notes (2).md", "notes.md"]
    assert library.entries("") == [], "a project's documents showed outside it"


def test_what_cannot_be_read_is_refused_with_a_reason(tmp_path):
    library = Library(tmp_path / "library")
    added, problems = library.add_files("", [doc(tmp_path, "tool.exe"), tmp_path / "missing.pdf"])
    assert added == [] and "not a kind of file" in problems[0] and "not a file" in problems[1]


def test_a_folder_is_read_where_it_is_and_given_back(tmp_path, sdk):
    library = Library(tmp_path / "library")
    assert library.add_folder("", sdk, ["docs.read"]) == ""
    assert sdk in library.folders("p1"), "the person's own folders are read in a project too"
    assert library.entries("")[0].kind == "folder"
    why, granted = library.remove("", str(sdk))
    assert why == "" and granted == ["docs.read"] and sdk.exists()
    assert library.folders("") == []


def test_a_whole_drive_or_the_library_itself_is_not_a_folder_to_add(tmp_path):
    library = Library(tmp_path / "library")
    (tmp_path / "library" / "personal").mkdir(parents=True)
    assert "whole drive" in library.add_folder("", Path(tmp_path.anchor), [])
    assert "library" in library.add_folder("", tmp_path / "library" / "personal", [])


def test_only_the_librarys_own_copies_are_deleted(tmp_path):
    library = Library(tmp_path / "library")
    outside = doc(tmp_path / "desktop", "keep.md")
    assert library.remove("", str(outside))[0] == "That is not in the library."
    assert outside.exists()
    (added,), _ = library.add_files("", [outside])
    assert library.remove("", str(added)) == ("", []) and not added.exists()


# -- adding from the window ----------------------------------------------------------------------


@pytest.fixture
def bridge(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    from akira.ui.bridge.documents import DocumentsBridge
    policy = Policy()
    allowed, taken = [], []

    def allow(capability, folder):
        held = policy.granted(capability)
        policy.grant(capability, ((*held.scopes, folder) if held else (folder,)))
        allowed.append((capability, folder))
        return ""

    made = DocumentsBridge(policy=lambda: policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                           secrets=SecretStore(tmp_path / "secrets"),
                           library=Library(tmp_path / "library"), project=lambda: "",
                           allow=allow, narrow=lambda c, f: taken.append((c, f)))
    yield made, policy, allowed, taken
    made.close()


def test_adding_files_allows_reading_the_library(bridge, tmp_path):
    documents, policy, allowed, _ = bridge
    source = doc(tmp_path / "downloads", "DS12288.pdf")
    said = documents.addFiles([source.as_uri()])
    assert said == "Added 1 file."
    folder = str(tmp_path / "library" / "personal")
    assert {c for c, f in allowed if f == folder} == {"files.read", "docs.read"}
    assert [e["name"] for e in documents.library] == ["DS12288.pdf"]
    assert documents.library[0]["sizeLabel"]


def test_a_folder_added_and_removed_takes_back_only_what_adding_allowed(bridge, sdk):
    documents, policy, allowed, taken = bridge
    policy.grant("files.read", (str(sdk),))          # held already, before adding
    assert documents.addFolder(sdk.as_uri()) == ""
    assert allowed == [("docs.read", str(sdk))]
    assert documents.removeFromLibrary(str(sdk)) == ""
    assert taken == [("docs.read", str(sdk))]


# -- the chat, answering from the library -------------------------------------------------------


def chat_with(tmp_path, folders, reply):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    from contextlib import contextmanager
    from akira.core.brain.grounding import Grounder, HeaderIndex
    from akira.core.config import AppConfig, ModelConfig
    from akira.core.conversations import ConversationStore
    from akira.core.models import ModelRouter
    from akira.ui.bridge import ChatBridge
    from tests.test_chat_bridge import SlowBackend

    model = tmp_path / "fake.gguf"
    model.write_bytes(b"gguf")
    config = AppConfig(models={"chat": ModelConfig(path=str(model), max_tokens=64),
                               "code": ModelConfig(path=str(model), max_tokens=64)})
    router = ModelRouter(config)
    backend = SlowBackend([reply], delay=0)
    prompts = []

    @contextmanager
    def acquire(route):
        original = backend.generate

        def generate(messages, **kwargs):
            prompts.append(messages)
            return original(messages, **kwargs)
        backend.generate = generate
        yield backend
        backend.generate = original

    router.acquire = acquire
    grounder = Grounder(lambda: list(folders), lambda path: True,
                        HeaderIndex(tmp_path / "headers.json"))
    bridge = ChatBridge(router, config, ConversationStore(tmp_path / "chats"), ground=grounder)
    return bridge, prompts


def finished(bridge):
    from tests.test_chat_bridge import pump_until, texts
    assert pump_until(lambda: not bridge.busy)
    return texts(bridge)[-1]


def test_the_f4_answer_is_flagged_under_it(tmp_path, sdk):
    bridge, prompts = chat_with(tmp_path, [sdk], AKIRA)
    bridge.send(QUESTION)
    answer = finished(bridge)
    assert "Check before using:" in answer and "`ADC_SAMPLETIME_480CYCLES`" in answer
    system = prompts[0][0].content
    assert "ADC_SAMPLETIME_640CYCLES_5" in system, "the real names were not given first"
    assert "Do not write the whole program" in system, "asked to be taught, it was not told"
    assert any(s["source"] == "files" and "library files" in s["cite"] for s in bridge.lastSources)


def test_with_nothing_to_check_against_the_answer_says_so_first(tmp_path):
    bridge, prompts = chat_with(tmp_path, [], "Use ADC_CHANNEL_1 on PA0.")
    bridge.send("How do I read PA0 with the ADC on an STM32G474?")
    answer = finished(bridge)
    assert answer.startswith("**Not checked:** nothing on this computer documents the STM32G474")
    assert "cannot check exact names" in prompts[0][0].content


def test_a_question_about_no_chip_is_left_alone(tmp_path, sdk):
    bridge, prompts = chat_with(tmp_path, [sdk], "Use sorted().")
    bridge.send("How do I sort a list in Python?")
    answer = finished(bridge)
    assert answer == "Use sorted()." and "library files" not in prompts[0][0].content


def test_the_chat_searches_the_library_documents(tmp_path):
    from akira.core.brain.recall import ContextAssembler
    from akira.core.tools import default_registry
    folder = tmp_path / "library" / "personal"
    doc(folder, "pins.md", "# Pinout\nPA0 is ADC12_IN1 on the STM32G474, on the A0 header.")
    policy = Policy()
    policy.grant("docs.read", (str(folder),))
    policy.grant("files.read", (str(folder),))
    assembler = ContextAssembler(registry=default_registry(), policy=lambda: policy,
                                 audit=AuditLog(tmp_path / "audit.jsonl"),
                                 secrets=SecretStore(tmp_path / "secrets"),
                                 library=lambda: [folder])
    context = assembler("Which ADC input is PA0 on the STM32G474?")
    assert "ADC12_IN1" in context.text
    assert any("pins.md" in s["cite"] for s in context.sources)


def test_a_document_too_large_to_search_is_said_to_be(bridge, tmp_path, monkeypatch):
    import akira.ui.bridge.documents as documents_module
    documents, _, _, _ = bridge
    monkeypatch.setattr(documents_module, "MAX_DOCUMENT_BYTES", 10)
    source = doc(tmp_path / "downloads", "RM0440.pdf", "x" * 50)
    said = documents.addFiles([source.as_uri()])
    assert said.startswith("Added 1 file.") and "kept but not searched" in said
