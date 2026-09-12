"""Ranking by meaning as well as words (B4): the index with an embedding model.

A fake model stands in for the real one. It knows which words mean the same
thing, so each test can say what meaning ought to find. The last test loads the
real model from models/embed/ when it is there.
"""

from __future__ import annotations

import contextlib
import math
import os
import sqlite3

import pytest

from akira.core import config
from akira.core.brain import Vault, embed
from akira.core.brain.index import Index, anywhere, sweep
from akira.core.config import config_dir, discover_models
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import default_registry
from akira.core.tools.builtin import knowledge
from akira.core.tools.schema import ToolContext


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))
    yield
    embed.use(None)


MEANINGS = {"garden": 0, "allotment": 0, "plot": 0, "vegetables": 0,
            "tax": 1, "return": 1, "invoice": 1, "accountant": 1,
            "dog": 2, "walk": 2}


class Fake:
    """Words that mean the same thing point the same way."""

    def __init__(self, model="fake-embed", fail=False):
        self.model, self.fail, self.calls = model, fail, []

    def embed(self, texts, *, query=False):
        if self.fail:
            raise RuntimeError("the model would not load")
        self.calls.append((len(texts), query))
        vectors = []
        for text in texts:
            vector = [0.0, 0.0, 0.0, 0.05]
            for word in text.lower().replace(".", " ").replace(",", " ").split():
                if word in MEANINGS:
                    vector[MEANINGS[word]] += 1.0
            norm = math.sqrt(sum(x * x for x in vector))
            vectors.append([x / norm for x in vector])
        return vectors


@pytest.fixture
def root(tmp_path):
    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    for rel, text in (("Allotment.md", "# Allotment\nPlot 14, by the water butt."),
                      ("Taxes.md", "# Taxes\nThe tax return goes to the accountant in January."),
                      ("Walks.md", "# Walks\nThe dog walk is at seven.")):
        (vault / rel).write_text(text, encoding="utf-8")
    return vault


def ready(root, tmp_path, embedder=None, name="index.sqlite"):
    index = Index(Vault(root), path=tmp_path / name, embedder=embedder)
    index.refresh()
    index.embed_pending()
    return index


def found(index, query):
    return [r.rel for r in index.search(query)]


def stored(path) -> list[tuple[str, str]]:
    with contextlib.closing(sqlite3.connect(path)) as db:
        return sorted(db.execute("SELECT c.rel, v.model FROM vectors v JOIN chunks c ON c.id = v.chunk"))


def test_meaning_finds_what_the_words_miss(root, tmp_path):
    assert found(ready(root, tmp_path, name="words.sqlite"), "garden") == []
    assert found(ready(root, tmp_path, Fake()), "garden") == ["Allotment.md"]


def test_what_both_find_comes_first(root, tmp_path):
    index = ready(root, tmp_path, Fake())
    results = index.search("tax")
    assert results[0].rel == "Taxes.md" and results[0].complete
    assert "Allotment.md" not in [r.rel for r in results]


def test_a_question_about_nothing_there_still_finds_nothing(root, tmp_path):
    assert found(ready(root, tmp_path, Fake()), "zebra") == []


def test_vectors_are_stored_in_batches_and_only_once(root, tmp_path):
    fake = Fake()
    index = Index(Vault(root), path=tmp_path / "index.sqlite", embedder=fake)
    index.refresh()
    assert index.embed_pending(budget_s=0) == 0, "a search with no time to spare waited anyway"
    assert index.embed_pending() == 3 and fake.calls == [(3, False)]
    assert index.embed_pending() == 0, "sections were embedded twice"


def test_a_changed_note_is_embedded_again_and_a_removed_one_leaves_no_vector(root, tmp_path):
    index = ready(root, tmp_path, Fake())
    note = root / "Allotment.md"
    note.write_text("# Allotment\nPlot 15 now, nearer the gate.", encoding="utf-8")
    stat = note.stat()
    os.utime(note, (stat.st_atime + 10, stat.st_mtime + 10))
    (root / "Taxes.md").unlink()
    index.refresh()
    assert [rel for rel, _ in stored(index.path)] == ["Walks.md"]
    assert index.embed_pending() == 1
    assert [rel for rel, _ in stored(index.path)] == ["Allotment.md", "Walks.md"]


def test_vectors_from_another_model_are_never_compared(root, tmp_path):
    ready(root, tmp_path, Fake("model-a"))
    other = Index(Vault(root), path=tmp_path / "index.sqlite", embedder=Fake("model-b"))
    assert found(other, "garden") == [], "one model's vectors were read as another's"
    assert other.embed_pending() == 3
    assert found(other, "garden") == ["Allotment.md"]
    assert {model for _, model in stored(other.path)} == {"model-b"}


def test_a_model_that_fails_leaves_the_search_to_words(root, tmp_path):
    index = Index(Vault(root), path=tmp_path / "index.sqlite", embedder=Fake(fail=True))
    assert [r.rel for r in knowledge.search_index(index, "tax")] == ["Taxes.md"]


def test_the_sweep_takes_a_notes_vectors_with_it(root):
    index = Index(Vault(root), embedder=Fake())
    index.refresh()
    index.embed_pending()
    kept = Policy()
    kept.grant("vault.read", (str(root / "Allotment.md"),))
    sweep(anywhere(kept))
    [path] = sorted((config_dir() / "index").glob("*.sqlite"))
    assert stored(path) == [("Allotment.md", "fake-embed")]


def test_an_index_made_before_vectors_is_swept_not_thrown_away(root):
    Index(Vault(root)).refresh()
    [path] = sorted((config_dir() / "index").glob("*.sqlite"))
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TABLE vectors")
    kept = Policy()
    kept.grant("vault.read", (str(root / "Walks.md"),))
    report = sweep(anywhere(kept))
    assert report.removed == 0 and report.dropped == 2 and path.exists()


def test_an_embedding_model_is_never_taken_for_a_chat_model(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_MIN_MODEL_BYTES", 4)
    for name in ("Qwen3-8B-Q4_K_M.gguf", "nomic-embed-text-v1.5.Q8_0.gguf"):
        (tmp_path / name).write_bytes(b"GGUF" + b"\0" * 16)
    assert [p.name for p in discover_models(tmp_path)] == ["Qwen3-8B-Q4_K_M.gguf"]


def test_search_notes_ranks_by_meaning_once_the_application_turns_it_on(root, tmp_path):
    policy = Policy()
    policy.grant("vault.read", (str(root),))
    context = ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                          secrets=SecretStore(tmp_path / "secrets"))
    words_only = default_registry().invoke("search_notes", {"vault": str(root), "query": "garden"},
                                           context)
    assert "Nothing in the notes matches" in words_only.content
    embed.use(Fake())
    by_meaning = default_registry().invoke("search_notes", {"vault": str(root), "query": "garden"},
                                           context)
    assert by_meaning.ok and "Allotment.md" in by_meaning.content


def test_the_real_model_ranks_by_meaning():
    model = embed.local()
    if model is None:
        pytest.skip("no embedding model in models/embed")
    passages = model.embed(["The allotment is plot 14, by the water butt.",
                            "The quarterly tax return is due in January."])
    [question] = model.embed(["where is my garden plot"], query=True)
    assert len(question) == 768

    def near(vector):
        return sum(a * b for a, b in zip(question, vector))

    assert near(passages[0]) > near(passages[1]) + 0.1
