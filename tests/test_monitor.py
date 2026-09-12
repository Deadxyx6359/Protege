"""Watching folders (C6, local half): changes become scheduler events once they
have settled, a watch is held to `files.read` on every look, and the `notify`
action is held to `notify.send`.
"""

from __future__ import annotations

import os

import pytest

from akira.core.agents import monitor as monitor_module
from akira.core.agents.monitor import (Monitor, MonitorError, WatchStore, describe_event,
                                         register_notify_action)
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.schedule import (ActionRegistry, ActionResult, JobGrant, JobStore, OnEvent,
                                   Scheduler)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def inbox(tmp_path):
    folder = tmp_path / "Inbox"
    folder.mkdir()
    (folder / "old.pdf").write_bytes(b"already here")
    return folder


@pytest.fixture
def live(inbox):
    policy = Policy()
    policy.grant("files.read", (str(inbox),))
    return policy


class Events(list):
    def __call__(self, name, payload):
        self.append((name, payload))

    def names(self):
        return [name for name, _ in self]


def watching(tmp_path, live, events=None):
    return Monitor(WatchStore(tmp_path / "watches.json"), policy=lambda: live,
                   publish=events if events is not None else Events(),
                   audit=AuditLog(tmp_path / "audit.jsonl"))


def write(path, data=b"x"):
    path.write_bytes(data)
    stat = path.stat()
    # Move the clock on, as a real save would, so equal sizes still differ.
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))


def test_the_first_look_is_a_baseline(tmp_path, inbox, live):
    events = Events()
    monitor = watching(tmp_path, live, events)
    monitor.add(str(inbox))
    assert monitor.poll() == 0 and events == []


def test_a_new_file_is_announced_once_it_has_settled(tmp_path, inbox, live):
    events = Events()
    monitor = watching(tmp_path, live, events)
    watch = monitor.add(str(inbox))
    monitor.poll()

    write(inbox / "new.pdf")
    monitor.poll()
    assert events == [], "announced before it was seen twice"
    monitor.poll()
    assert events.names() == ["file.created", "folder.changed"]
    created, summary = events[0][1], events[1][1]
    assert created == {"watch": watch.id, "folder": watch.folder, "path": "new.pdf",
                       "name": "new.pdf"}
    assert (summary["created"], summary["paths"]) == (1, ["new.pdf"])

    monitor.poll()
    assert len(events) == 2, "the same file was announced twice"


def test_a_file_still_being_written_waits(tmp_path, inbox, live):
    events = Events()
    monitor = watching(tmp_path, live, events)
    monitor.add(str(inbox))
    monitor.poll()
    write(inbox / "big.pdf", b"part")
    monitor.poll()
    write(inbox / "big.pdf", b"part and more")
    monitor.poll()
    assert events == []
    monitor.poll()
    assert events.names() == ["file.created", "folder.changed"]


def test_changes_and_deletions_are_announced(tmp_path, inbox, live):
    events = Events()
    monitor = watching(tmp_path, live, events)
    monitor.add(str(inbox))
    monitor.poll()

    write(inbox / "old.pdf", b"edited since")
    monitor.poll()
    monitor.poll()
    assert "file.changed" in events.names()

    events.clear()
    (inbox / "old.pdf").unlink()
    monitor.poll()
    monitor.poll()
    assert events.names() == ["file.deleted", "folder.changed"]


def test_patterns_and_hidden_or_partial_files_limit_what_is_watched(tmp_path, inbox, live):
    events = Events()
    monitor = watching(tmp_path, live, events)
    monitor.add(str(inbox), ["*.PDF"])
    monitor.poll()
    for name in ("notes.txt", ".hidden.pdf", "~$draft.pdf", "file.pdf.crdownload"):
        write(inbox / name)
    (inbox / ".git").mkdir()
    write(inbox / ".git" / "HEAD.pdf")
    monitor.poll()
    monitor.poll()
    assert events == []


def test_a_watch_needs_permission_to_read_the_folder(tmp_path, inbox):
    monitor = watching(tmp_path, Policy())
    with pytest.raises(MonitorError, match="Not permitted"):
        monitor.add(str(inbox))
    with pytest.raises(MonitorError):
        watching(tmp_path, Policy()).add(str(tmp_path / "missing"))


def test_revoking_the_permission_pauses_the_watch_and_says_why(tmp_path, inbox, live):
    events = Events()
    monitor = watching(tmp_path, live, events)
    watch = monitor.add(str(inbox))
    monitor.poll()

    live.revoke("files.read")
    write(inbox / "new.pdf")
    monitor.poll()
    monitor.poll()
    assert watch.paused.startswith("Not permitted") and events == []
    assert (tmp_path / "audit.jsonl").read_text(encoding="utf-8").count("watch_folder") == 1

    live.grant("files.read", (str(inbox),))
    monitor.poll()
    assert watch.paused == ""
    monitor.poll()
    assert events == [], "what arrived while it was not looking was reported afterwards"


def test_a_folder_too_big_to_watch_is_paused(tmp_path, inbox, live, monkeypatch):
    monkeypatch.setattr(monitor_module, "MAX_FILES", 1)
    write(inbox / "second.pdf")
    monitor = watching(tmp_path, live)
    watch = monitor.add(str(inbox))
    monitor.poll()
    assert "more than 1 files" in watch.paused and "pattern" in watch.paused


def test_watches_are_kept_and_a_damaged_list_is_moved_aside(tmp_path, inbox, live):
    first = watching(tmp_path, live)
    watch = first.add(str(inbox), ["*.pdf"])
    again = watching(tmp_path, live)
    assert [(w.id, w.patterns) for w in again.watches()] == [(watch.id, ("*.pdf",))]

    (tmp_path / "watches.json").write_text("{not json", encoding="utf-8")
    broken = watching(tmp_path, live)
    assert broken.watches() == [] and "damaged" in broken.warnings[0]
    assert list(tmp_path.glob("watches.json.damaged-*"))


def test_a_folder_change_wakes_a_job_waiting_for_that_watch(tmp_path, inbox, live):
    actions, runs = ActionRegistry(), []

    def note(context):
        runs.append((context.event_name, context.event))
        return ActionResult(True, "noted")

    actions.register("note", note)
    scheduler = Scheduler(actions, policy=lambda: live, audit=AuditLog(tmp_path / "a.jsonl"),
                          secret_store=SecretStore(tmp_path / "s"),
                          store=JobStore(tmp_path / "schedule.json"))
    monitor = watching(tmp_path, live, scheduler.publish)
    watch = monitor.add(str(inbox))
    scheduler.add("New files", "note", OnEvent("folder.changed", {"watch": watch.id}, 5))

    monitor.poll()
    write(inbox / "new.pdf")
    monitor.poll()
    monitor.poll()
    scheduler.tick()
    assert [name for name, _ in runs] == ["folder.changed"]
    assert runs[0][1]["paths"] == ["new.pdf"]


def test_a_notice_needs_its_permission_and_says_what_happened(tmp_path, inbox, live):
    actions, shown = ActionRegistry(), []
    register_notify_action(actions, notify=lambda title, text: shown.append((title, text)))
    scheduler = Scheduler(actions, policy=lambda: live, audit=AuditLog(tmp_path / "a.jsonl"),
                          secret_store=SecretStore(tmp_path / "s"),
                          store=JobStore(tmp_path / "schedule.json"))
    arguments, grants = {"text": "Something arrived."}, (JobGrant("notify.send"),)
    # Its own job: a manual run starts the cooldown, which would hold back the event.
    refused = scheduler.add("Refused", "notify", OnEvent("never", {}, 5),
                            arguments=arguments, grants=grants)
    assert scheduler.run_now(refused.id).status == "failed" and shown == []

    scheduler.add("Inbox", "notify", OnEvent("folder.changed", {}, 5),
                  arguments=arguments, grants=grants)
    live.grant("notify.send")
    scheduler.publish("folder.changed", {"folder": str(inbox), "created": 1,
                                         "paths": ["new.pdf"]})
    scheduler.tick()
    [(title, text)] = shown
    assert title == "Inbox" and text.startswith("Something arrived.")
    assert "1 new" in text and "new.pdf" in text


def test_events_are_described_for_people():
    assert describe_event("file.created", {"folder": "C:/In", "path": "a.pdf"}) == \
        "a.pdf was created in C:/In."
    assert describe_event("folder.changed", {"folder": "C:/In", "changed": 2}) == \
        "In C:/In: 2 changed."
    assert describe_event("anything", {}) == "Because of “anything”."
