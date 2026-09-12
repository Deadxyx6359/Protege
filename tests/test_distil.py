"""Memory distillation (B5): conversations become proposals, never notes, until a
person accepts them; proposals are deduplicated against the vault and each
other; and the job reads only with the permissions it is given.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from akira.core.brain import ConflictError, Index, Vault
from akira.core.brain.distil import (DISTIL_ACTION, Distiller, PendingStore, accept,
                                       ensure_distil_job, new_lines, parse_notes,
                                       register_distil_action, vault_of)
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.schedule import ActionRegistry, JobStore, Scheduler
from akira.models.base import ModelUnavailable
from akira.models.scripted import ScriptedBackend


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


class Router:
    """Hands out one scripted backend, or fails to load one."""

    def __init__(self, *replies, fail=None):
        self.backend = ScriptedBackend(replies=replies)
        self.fail = fail

    @contextmanager
    def acquire(self, route):
        if self.fail is not None:
            raise self.fail
        yield self.backend


def save_conversation(directory, cid, title, *turns):
    directory.mkdir(parents=True, exist_ok=True)
    messages = [{"id": f"m{n}", "role": role, "text": text, "created": 0, "error": False}
                for n, (role, text) in enumerate(turns)]
    (directory / f"{cid}.json").write_text(
        json.dumps({"id": cid, "title": title, "messages": messages}), encoding="utf-8")


ALLOTMENT = (("user", "I got plot 14 at the allotment."),
             ("assistant", "Congratulations. When do you start?"),
             ("user", "April."),
             ("assistant", "Then plan the beds in March."))


@pytest.fixture
def chats(tmp_path):
    directory = tmp_path / "cfg" / "conversations"
    save_conversation(directory, "a1b2c3d4", "Allotment", *ALLOTMENT)
    return directory


@pytest.fixture
def vault_root(tmp_path):
    root = tmp_path / "Vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "Garden.md").write_text("# Garden\n- Tomatoes go in after the last frost.\n",
                                    encoding="utf-8")
    return root


def distil(vault_root, router, **kwargs):
    return Distiller(router, Vault(vault_root), **kwargs).run()


# -- reading the model's answer ------------------------------------------------------------


def test_a_models_answer_is_read_as_notes():
    text = ("Here you go.\n\n## Allotment\n- Plot 14.\n- Starts in April.\n\n"
            "## Planning: beds?\n- Plan them in March.\n")
    assert parse_notes(text) == [("Allotment", "- Plot 14.\n- Starts in April."),
                                 ("Planning beds", "- Plan them in March.")]
    assert parse_notes("NOTHING") == []


def test_only_lines_the_note_does_not_already_say_are_kept():
    existing = "# Garden\n- Tomatoes go in after the last frost.\n"
    proposed = "- tomatoes go in after the last frost\n- Basil beside them."
    assert new_lines(existing, proposed) == "- Basil beside them."


# -- proposing -------------------------------------------------------------------------------


def test_a_conversation_becomes_a_proposal_not_a_note(vault_root, chats, tmp_path):
    router = Router("## Allotment\n- Plot 14, from April.\n- Plan the beds in March.\n")
    report = distil(vault_root, router)
    assert (report.read, report.proposed) == (1, 1)

    [proposal] = PendingStore().all()
    assert proposal.target == "Memory/Allotment.md" and not proposal.adds_to
    assert "Plot 14" in proposal.body and "“Allotment”" in proposal.body
    assert not (vault_root / "Memory").exists(), "a proposal was written into the vault"
    index = Index(Vault(vault_root), path=tmp_path / "index.sqlite")
    index.refresh()
    assert index.search("plot") == [], "unreviewed model output can be searched"

    [system, user] = router.backend.calls[0]
    assert "worth" in system.content and "plot 14" in user.content


def test_reasoning_is_not_kept_as_a_note(vault_root, chats):
    distil(vault_root, Router("<think>They seem keen on plots.</think>## Allotment\n- Plot 14.\n"))
    [proposal] = PendingStore().all()
    assert "keen" not in proposal.body


def test_a_known_subject_becomes_an_addition_of_only_what_is_new(vault_root, chats):
    distil(vault_root, Router("## Garden\n- Tomatoes go in after the last frost.\n"
                              "- Basil goes beside them.\n"))
    [proposal] = PendingStore().all()
    assert proposal.adds_to and proposal.target == "Garden.md"
    assert "Basil" in proposal.body and "Tomatoes" not in proposal.body


def test_a_close_name_counts_as_the_same_subject(vault_root, chats):
    distil(vault_root, Router("## Gardens\n- Basil beside the tomatoes.\n"))
    [proposal] = PendingStore().all()
    assert proposal.target == "Garden.md"


def test_a_proposal_that_says_nothing_new_is_dropped(vault_root, chats):
    report = distil(vault_root, Router("## garden\n- Tomatoes go in after the last frost.\n"))
    assert (report.proposed, report.already_known) == (0, 1)
    assert PendingStore().all() == []


def test_two_conversations_proposing_one_note_make_one_proposal(vault_root, chats):
    save_conversation(chats, "e5f6a7b8", "Seeds",
                      ("user", "Which seeds for plot 14?"), ("assistant", "Broad beans first."))
    distil(vault_root, Router("## Allotment\n- Plot 14.\n",
                              "## Allotment\n- Plot 14.\n- Broad beans first.\n"))
    [proposal] = PendingStore().all()
    assert proposal.body.count("Plot 14") == 1 and "Broad beans" in proposal.body
    assert [s["title"] for s in proposal.sources] == ["Allotment", "Seeds"]


def test_a_conversation_is_read_once_and_then_only_what_came_after(vault_root, chats):
    router = Router("NOTHING", "## Allotment\n- Water butts arrive in May.\n")
    assert distil(vault_root, router).read == 1
    # Unchanged, so the model is not asked again: the scripted backend would fail.
    assert distil(vault_root, router).read == 0

    save_conversation(chats, "a1b2c3d4", "Allotment", *ALLOTMENT,
                      ("user", "The water butts arrive in May."),
                      ("assistant", "Put them by the shed."))
    assert distil(vault_root, router).read == 1
    prompt = router.backend.calls[-1][1].content
    assert "water butts" in prompt and "plot 14" not in prompt and "read before" in prompt


def test_a_model_that_cannot_load_leaves_conversations_for_next_time(vault_root, chats):
    report = distil(vault_root, Router(fail=ModelUnavailable("no model is configured")))
    assert report.read == 0 and report.errors
    assert distil(vault_root, Router("NOTHING")).read == 1


def test_closing_stops_the_run(vault_root, chats):
    report = Distiller(Router("NOTHING"), Vault(vault_root)).run(is_cancelled=lambda: True)
    assert report.cancelled and report.read == 0


# -- accepting -------------------------------------------------------------------------------


def test_accepting_a_new_note_writes_it_through_the_vault(vault_root, chats):
    distil(vault_root, Router("## Allotment\n- Plot 14.\n"))
    [proposal] = PendingStore().all()
    assert accept(PendingStore(), proposal.id, Vault(vault_root)) == "Memory/Allotment.md"
    assert "Plot 14" in (vault_root / "Memory" / "Allotment.md").read_text(encoding="utf-8")
    assert PendingStore().all() == []


def test_an_accepted_addition_can_be_undone(vault_root, chats):
    distil(vault_root, Router("## Garden\n- Basil beside them.\n"))
    [proposal] = PendingStore().all()
    vault = Vault(vault_root)
    accept(PendingStore(), proposal.id, vault)
    text = (vault_root / "Garden.md").read_text(encoding="utf-8")
    assert "Tomatoes go in" in text and "Basil beside them" in text

    [(version, _)] = vault.history("Garden.md")
    vault.restore("Garden.md", version)
    assert "Basil" not in (vault_root / "Garden.md").read_text(encoding="utf-8")


def test_a_note_edited_since_the_proposal_is_not_overwritten(vault_root, chats):
    distil(vault_root, Router("## Garden\n- Basil beside them.\n- Water in the morning.\n"))
    [proposal] = PendingStore().all()
    (vault_root / "Garden.md").write_text(
        "# Garden\n- Tomatoes go in after the last frost.\n- Water in the morning.\n",
        encoding="utf-8")

    with pytest.raises(ConflictError):
        accept(PendingStore(), proposal.id, Vault(vault_root))
    [rebased] = PendingStore().all()
    assert "Basil" in rebased.body and "Water in the morning" not in rebased.body

    accept(PendingStore(), rebased.id, Vault(vault_root))
    text = (vault_root / "Garden.md").read_text(encoding="utf-8")
    assert text.count("Water in the morning") == 1 and "Basil" in text


# -- the job ---------------------------------------------------------------------------------


def scheduler_for(tmp_path, live, router):
    actions = ActionRegistry()
    register_distil_action(actions, router=router)
    return Scheduler(actions, policy=lambda: live, audit=AuditLog(tmp_path / "audit.jsonl"),
                     secret_store=SecretStore(tmp_path / "secrets"),
                     store=JobStore(tmp_path / "schedule.json"))


def test_the_job_needs_both_permissions_and_writes_only_proposals(vault_root, chats, tmp_path):
    live = Policy()
    live.grant("vault.read", (str(vault_root),))
    scheduler = scheduler_for(tmp_path, live, Router("## Allotment\n- Plot 14.\n"))
    job = ensure_distil_job(scheduler, str(vault_root))

    refused = scheduler.run_now(job.id)
    assert refused.status == "failed" and "Remember past conversations" in refused.summary

    live.grant("memory.read")
    before = sorted(p.relative_to(vault_root) for p in vault_root.rglob("*"))
    assert scheduler.run_now(job.id).status == "ok"
    assert len(PendingStore().all()) == 1
    assert sorted(p.relative_to(vault_root) for p in vault_root.rglob("*")) == before
    assert DISTIL_ACTION in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_one_memory_job_follows_the_chosen_vault(vault_root, tmp_path):
    scheduler = scheduler_for(tmp_path, Policy(), Router())
    first = ensure_distil_job(scheduler, str(vault_root))
    assert ensure_distil_job(scheduler, str(vault_root)).id == first.id

    other = tmp_path / "Other"
    other.mkdir()
    moved = ensure_distil_job(scheduler, str(other))
    assert [job.id for job in scheduler.find(DISTIL_ACTION)] == [moved.id]
    assert vault_of(scheduler) == str(other)
