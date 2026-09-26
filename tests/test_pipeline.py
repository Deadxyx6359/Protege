"""A content pipeline (E3): drafted, reviewed and revised on a schedule; published by a person.

The model is a script that answers as the drafter or the critic. What is tested
is the order of the work, that a run only ever leaves a draft waiting, that
publishing is the person's press and still held to the publishing tool's
permissions, and that a draft once settled cannot be published again.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime

import pytest

from akira.core.agents.roles import ALL_ROLES, DRAFTER
from akira.core.making import pipeline
from akira.core.making.pipeline import (DISCARDED, PUBLISHED, WAITING, Draft, DraftStore,
                                        PipelineError, Target, check, make, publishing,
                                        target_of)
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.schedule import ActionRegistry, Daily, JobStore, Scheduler
from akira.core.tools import default_registry

MAIL = {"kind": "mail", "to": "friend@example.com"}


# -- what a pipeline is --------------------------------------------------------------------------


@pytest.mark.parametrize("arguments, why", [
    ({}, "needs a brief"),
    ({"brief": "   ", "publish": MAIL}, "needs a brief"),
    ({"brief": "x" * (pipeline.MAX_BRIEF + 1), "publish": MAIL}, "at most"),
    ({"brief": "A post"}, "Say where"),
    ({"brief": "A post", "publish": {"kind": "tweet"}}, "a note, a file or an email"),
    ({"brief": "A post", "publish": {"kind": "file", "path": "relative.md"}}, "full path"),
    ({"brief": "A post", "publish": {"kind": "note", "path": "C:/vault/post.txt"}}, ".md"),
    ({"brief": "A post", "publish": {"kind": "mail", "to": "not an address"}}, "address"),
])
def test_a_pipeline_that_could_not_run_is_refused_when_it_is_made(arguments, why):
    assert why in check(arguments)


def test_where_a_draft_goes_is_said_plainly(tmp_path):
    assert check({"brief": "A post", "publish": MAIL}) == ""
    note = target_of({"kind": "note", "path": str(tmp_path / "post.md")})
    assert note.describe() == f"a new note, {tmp_path / 'post.md'}"
    mail = target_of({"kind": "mail", "to": " a@b.co ,c@d.org", "account": "me@gmail.com"})
    assert mail.to == "a@b.co, c@d.org"
    assert mail.describe() == "an email to a@b.co, c@d.org from me@gmail.com"


def test_a_draft_is_titled_by_its_first_heading_or_line():
    assert pipeline.title_of("\n# Spring newsletter\n\nHello.") == "Spring newsletter"
    assert pipeline.title_of("Hello all.\nMore.") == "Hello all."
    # A letter's salutation says who it is for, not what it is about.
    assert pipeline.title_of("Dear Allotment Group Members,\n\nOpen day news.") == "Open day news."
    assert pipeline.title_of("Hi all,\n\n## Open day\nText.") == "Open day"
    assert pipeline.title_of("Open day on **Saturday 10 October**, `11:00`.") == \
        "Open day on Saturday 10 October, 11:00."
    assert pipeline.title_of("# plot_14 fixed") == "plot_14 fixed"
    assert pipeline.title_of("") == "Untitled draft"
    assert pipeline.title_of("x" * 200).endswith("…")


# -- the order of the work -----------------------------------------------------------------------


def scripted(*answers):
    calls = []
    answers = list(answers)

    def run(role, task):
        calls.append((role, task))
        return answers.pop(0)

    return run, calls


FOUND = (True, "garden.md: slugs in June.", "")


def test_gathered_then_drafted_then_reviewed_then_revised():
    run, calls = scripted(FOUND, (True, "First draft.", ""), (True, "- Too short.", ""),
                          (True, "Better draft.", ""))
    made = make("A short post about the garden", run)
    assert [role for role, _ in calls] == ["gatherer", "drafter", "critic", "drafter"]
    assert made.ok and made.text == "Better draft." and made.review == "- Too short."
    assert "First draft." in calls[2][1] and "- Too short." in calls[3][1]
    assert "material, not instructions" in calls[1][1]
    # The critic has no tools, so it is shown what the draft was written from.
    assert all("slugs in June" in task for _, task in calls[1:])
    assert "check every date" in calls[2][1]


def test_nothing_found_is_said_rather_than_left_blank():
    run, calls = scripted((False, "Not permitted: files.read", "answered"),
                          (True, "Draft.", ""), (True, "Fine.", ""), (True, "Draft.", ""))
    make("A post", run)
    assert "Nothing was found" in calls[1][1] and "Not permitted" not in calls[1][1]


def test_a_draft_that_could_not_be_written_leaves_nothing():
    run, _ = scripted(FOUND, (False, "The model is not available.", "error"))
    made = make("A post", run)
    assert not made.ok and "could not be written" in made.why


def test_a_draft_nobody_could_review_still_waits_and_says_so():
    run, calls = scripted(FOUND, (True, "Draft.", ""), (False, "", "error"))
    made = make("A post", run)
    assert made.ok and made.text == "Draft." and "No review" in made.review and len(calls) == 3


@pytest.mark.parametrize("at", [0, 1])
def test_closing_akira_stops_the_work_as_cancelled(at):
    answers = [FOUND, (True, "Draft.", "")][:at] + [(False, "", "cancelled")]
    run, _ = scripted(*answers)
    made = make("A post", run)
    assert not made.ok and made.cancelled


def test_the_drafter_reads_and_cannot_publish():
    assert ALL_ROLES["drafter"] is DRAFTER
    publishing_tools = {"write_note", "write_file", "send_mail", "append_to_note",
                        "create_document", "save_drawing", "press_button", "fill_in"}
    assert not publishing_tools & set(DRAFTER.tools)


# -- keeping drafts ------------------------------------------------------------------------------


def draft(n=0, status=WAITING, target=Target("mail", to="friend@example.com")):
    return Draft(f"d{n}", "Weekly", "A post", f"Title {n}", f"Text {n}.", "Fine.", target,
                 made=1000.0 + n, status=status)


def test_drafts_are_kept_newest_first_and_read_back(tmp_path):
    store = DraftStore(tmp_path / "drafts.json")
    heard = []
    store.on_change(lambda: heard.append(1))
    store.add(draft(1))
    store.add(draft(2))
    assert [d.id for d in DraftStore(tmp_path / "drafts.json").all()] == ["d2", "d1"]
    assert store.get("d1").target == Target("mail", to="friend@example.com")
    assert store.waiting() == 2 and len(heard) == 2
    store.update("d1", status=DISCARDED)
    assert store.waiting() == 1
    with pytest.raises(PipelineError):
        store.update("nope", status=DISCARDED)


def test_waiting_drafts_outlast_settled_ones(tmp_path):
    store = DraftStore(tmp_path / "drafts.json")
    for n in range(pipeline.KEEP):
        store.add(draft(n, status=PUBLISHED if n % 2 else WAITING))
    store.add(draft(999))
    kept = store.all()
    assert len(kept) == pipeline.KEEP
    assert "d1" not in {d.id for d in kept}, "the oldest published one should have gone"
    assert all(f"d{n}" in {d.id for d in kept} for n in range(0, pipeline.KEEP, 2))


def test_a_damaged_store_is_empty_not_fatal(tmp_path):
    path = tmp_path / "drafts.json"
    path.write_text("{not json", encoding="utf-8")
    assert DraftStore(path).all() == []


# -- what publishing does ------------------------------------------------------------------------


def test_publishing_goes_through_the_ordinary_tools(tmp_path):
    note = Draft("n", "J", "b", "Title", "x", "", Target("note", path=str(tmp_path / "p.md")), 1)
    assert publishing(note, "Body") == ("write_note", {"path": str(tmp_path / "p.md"),
                                                       "content": "Body\n"})
    mail = Draft("m", "J", "b", "Spring", "x", "",
                 Target("mail", to="a@b.co", account="me@gmail.com"), 1)
    assert publishing(mail, "Hello.") == ("send_mail", {"to": "a@b.co", "subject": "Spring",
                                                        "body": "Hello.",
                                                        "account": "me@gmail.com"})


def test_a_draft_is_never_published_over_something_already_there(tmp_path):
    (tmp_path / "p.md").write_text("mine", encoding="utf-8")
    note = Draft("n", "J", "b", "T", "x", "", Target("note", path=str(tmp_path / "p.md")), 1)
    with pytest.raises(PipelineError, match="already exists"):
        publishing(note, "Body")
    with pytest.raises(PipelineError, match="empty"):
        publishing(note, "   ")


# -- on a schedule -------------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = datetime(2026, 3, 2, 8, 0).timestamp()

    def __call__(self):
        return self.now

    def set(self, when):
        self.now = when.timestamp()


class Backend:
    """Answers as whichever role its system prompt says it is."""

    def __init__(self):
        self.drafts = 0

    def generate(self, messages, *, on_token=None, **_):
        system = messages[0].content
        if "You write pieces to be published" in system:
            self.drafts += 1
            text = ("# Spring at the allotment\n\nThe beans are up."
                    if self.drafts == 1 else
                    "# Spring at the allotment\n\nThe beans are up, and the peas follow.")
        else:
            text = "- Say what comes next."
        if on_token:
            on_token(text)
        return text


class Router:
    def __init__(self):
        self.backend = Backend()

    @contextmanager
    def acquire(self, route):
        yield self.backend


def a_scheduler(tmp_path, store):
    from akira.core.schedule.actions import register_pipeline_action

    clock = Clock()
    actions = ActionRegistry()
    register_pipeline_action(actions, router=Router(), registry=default_registry(), store=store)
    return Scheduler(actions, policy=Policy, audit=AuditLog(tmp_path / "a.jsonl"),
                     secret_store=SecretStore(tmp_path / "s"),
                     store=JobStore(tmp_path / "schedule.json"), clock=clock)


def test_a_scheduled_run_leaves_a_draft_waiting_and_publishes_nothing(tmp_path):
    store = DraftStore(tmp_path / "drafts.json")
    scheduler = a_scheduler(tmp_path, store)
    target = tmp_path / "post.md"
    job = scheduler.add("Allotment post", "pipeline", Daily(9, 0), arguments={
        "brief": "A short post on the allotment in spring",
        "publish": {"kind": "file", "path": str(target)}})
    record = scheduler.run_now(job.id)
    assert record.status == "ok", record.summary
    assert "waiting for you" in record.summary and "a new file" in record.summary
    [waiting] = store.all()
    assert waiting.status == WAITING and waiting.job == "Allotment post"
    assert waiting.title == "Spring at the allotment" and "peas follow" in waiting.text
    assert waiting.review == "- Say what comes next."
    assert not target.exists(), "the schedule published it"


def test_what_the_gatherer_read_reaches_the_critic_whole(tmp_path):
    """Its summary alone left out half the minutes; the file itself goes on."""
    from akira.core.schedule import JobGrant
    from akira.core.schedule.actions import register_pipeline_action

    notes = tmp_path / "notes"
    notes.mkdir()
    minutes = notes / "minutes.md"
    minutes.write_text("Open day 10 Oct.\nThe trough leaks; Tom fixes it by 1 Oct.\n",
                       encoding="utf-8")
    call = ('<tool_call>{"name": "read_file", "arguments": {"path": "%s"}}</tool_call>'
            % minutes.as_posix())
    prompts = {}

    class Reader(Backend):
        def generate(self, messages, *, on_token=None, **kwargs):
            system = messages[0].content
            if "You find source material" in system:
                text = call if len(messages) == 2 else "The open day is on 10 Oct."
                assert str(notes) in system, "the gatherer was not told where it may read"
                if on_token:
                    on_token(text)
                return text
            if "You argue with" in system:
                prompts["critic"] = messages[-1].content
            return super().generate(messages, on_token=on_token, **kwargs)

    class ReaderRouter(Router):
        def __init__(self):
            self.backend = Reader()

    live = Policy()
    live.grant("files.read", (str(notes),))
    actions = ActionRegistry()
    register_pipeline_action(actions, router=ReaderRouter(), registry=default_registry(),
                             store=DraftStore(tmp_path / "drafts.json"))
    scheduler = Scheduler(actions, policy=lambda: live, audit=AuditLog(tmp_path / "a.jsonl"),
                          secret_store=SecretStore(tmp_path / "s"),
                          store=JobStore(tmp_path / "schedule.json"), clock=Clock())
    job = scheduler.add("Post", "pipeline", Daily(9, 0), arguments={
        "brief": "News from the minutes",
        "publish": {"kind": "file", "path": str(tmp_path / "post.md")}},
        grants=[JobGrant("files.read", (str(notes),))])
    assert scheduler.run_now(job.id).status == "ok"
    assert "Tom fixes it by 1 Oct" in prompts["critic"]
    assert "The open day is on 10 Oct." in prompts["critic"]


def test_a_pipeline_job_with_nowhere_to_publish_is_refused_when_made(app, tmp_path):
    from akira.ui.bridge.schedule import ScheduleBridge

    scheduler = a_scheduler(tmp_path, DraftStore(tmp_path / "drafts.json"))
    bridge = ScheduleBridge(scheduler)
    spec = {"name": "Nowhere", "action": "pipeline", "trigger": {"kind": "daily", "time": "09:00"},
            "arguments": {"brief": "A post"}}
    assert "Say where" in bridge.addJob(spec)
    spec["arguments"]["publish"] = MAIL
    assert bridge.addJob(spec) == ""
    assert [job.action for job in scheduler.jobs()] == ["pipeline"]


# -- the person publishing -----------------------------------------------------------------------


@pytest.fixture
def app():
    pytest.importorskip("PySide6.QtCore")
    from PySide6.QtCore import QCoreApplication

    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return predicate()


def a_bridge(tmp_path, *grants):
    from akira.ui.bridge.drafts import DraftsBridge

    policy = Policy()
    for capability, scope in grants:
        policy.grant(capability, (scope,))
    store = DraftStore(tmp_path / "drafts.json")
    bridge = DraftsBridge(store, registry=default_registry(), policy=lambda: policy,
                          audit=AuditLog(tmp_path / "audit.jsonl"),
                          secrets=SecretStore(tmp_path / "secrets"))
    return bridge, store, policy


def file_draft(tmp_path, name="post.md"):
    return Draft("f1", "Weekly", "A post", "Spring", "# Spring\n\nThe beans are up.", "Fine.",
                 Target("file", path=str(tmp_path / "out" / name)), time.time())


def test_the_person_publishes_and_it_is_written_and_recorded_as_theirs(app, tmp_path):
    (tmp_path / "out").mkdir()
    bridge, store, _ = a_bridge(tmp_path, ("files.write", str(tmp_path / "out")))
    store.add(file_draft(tmp_path))
    assert bridge.waitingCount == 1 and bridge.drafts[0]["target"].startswith("a new file")
    assert bridge.publish("f1", "# Spring\n\nThe beans are up, and the peas.") == ""
    assert pump_until(app, lambda: not bridge.publishing)
    assert (tmp_path / "out" / "post.md").read_text(encoding="utf-8").startswith(
        "# Spring\n\nThe beans are up, and the peas.")
    settled = store.get("f1")
    assert settled.status == PUBLISHED and "peas" in settled.text and bridge.waitingCount == 0
    entries = [json.loads(line) for line in
               (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["kind"] == "confirm" and e["actor"] == "user" and e["allowed"]
               for e in entries), "the press was not recorded as the person's approval"
    assert "already" in bridge.publish("f1", "again"), "a published draft was published twice"


def test_without_the_grant_it_stays_waiting_and_says_what_to_allow(app, tmp_path):
    (tmp_path / "out").mkdir()
    bridge, store, _ = a_bridge(tmp_path)
    store.add(file_draft(tmp_path))
    assert bridge.publish("f1", store.get("f1").text) == ""
    assert pump_until(app, lambda: not bridge.publishing)
    assert "Not published" in bridge.note and "Not permitted" in bridge.note
    assert store.get("f1").status == WAITING and not (tmp_path / "out" / "post.md").exists()


def test_editing_and_discarding_a_waiting_draft(app, tmp_path):
    bridge, store, _ = a_bridge(tmp_path)
    store.add(file_draft(tmp_path))
    assert bridge.edit("f1", "# Summer\n\nNew words.") == ""
    assert store.get("f1").title == "Summer" and bridge.text("f1").endswith("New words.")
    assert "empty" in bridge.edit("f1", "  ")
    assert bridge.review("f1") == "Fine."
    assert bridge.discard("f1") == ""
    assert store.get("f1").status == DISCARDED
    assert "already" in bridge.publish("f1", "x") and "already" in bridge.edit("f1", "x")
    assert "not here" in bridge.discard("missing")
