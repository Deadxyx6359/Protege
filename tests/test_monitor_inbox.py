"""Watching an inbox (C6 over C5): known by its messages, held to `mail.read` for the
address on every look, paused with the connection's reason, remembered across a
restart. The inbox is a stand-in; nothing here reaches Google.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from akira.core.agents.monitor import Monitor, MonitorError, WatchStore, describe_event
from akira.core.connect import google
from akira.core.connect import inbox as gmail_inbox
from akira.core.connect.google import AccountStore, GoogleAccounts
from akira.core.permissions import AuditLog, Policy, SecretStore

ADDRESS = "akira.helper@gmail.com"


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


class FakeInbox:
    def __init__(self):
        self.mail, self.problem, self.asked = [], "", 0
        self.addresses = {ADDRESS}

    def connected(self, address):
        return address in self.addresses

    def recent(self, address):
        self.asked += 1
        if self.problem:
            raise RuntimeError(self.problem)
        return list(self.mail)


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    def later(self, seconds=3600):
        self.now += seconds


class Events(list):
    def __call__(self, name, payload):
        self.append((name, payload))

    def names(self):
        return [name for name, _ in self]


def message(ident, subject, sender="Bank <alerts@bank.example>", snippet="Your statement"):
    return SimpleNamespace(id=ident, sender=sender, subject=subject,
                           date="Fri, 11 Sep 2026 09:00", snippet=snippet)


@pytest.fixture
def world(tmp_path):
    policy = Policy()
    policy.grant("mail.read", (ADDRESS,))
    inbox, clock, events = FakeInbox(), Clock(), Events()

    def make():
        return Monitor(WatchStore(tmp_path / "watches.json"), policy=lambda: policy,
                       publish=events, audit=AuditLog(tmp_path / "audit.jsonl"), inbox=inbox,
                       clock=clock)

    return SimpleNamespace(make=make, inbox=inbox, clock=clock, events=events, policy=policy,
                           tmp=tmp_path)


def test_an_inbox_watch_needs_a_connected_address_and_mail_read(world):
    monitor = world.make()
    with pytest.raises(MonitorError, match="not connected for mail"):
        monitor.add_inbox("someone@gmail.com")
    with pytest.raises(MonitorError, match="not a mail address"):
        monitor.add_inbox("akira")
    world.policy.revoke("mail.read")
    with pytest.raises(MonitorError, match="Not permitted"):
        monitor.add_inbox(ADDRESS)
    world.policy.grant("mail.read", (ADDRESS,))
    with pytest.raises(MonitorError, match="15 minutes"):
        monitor.add_inbox(ADDRESS, every_s=60)
    watch = monitor.add_inbox("Akira.Helper@gmail.com", ["invoice"])
    assert (watch.kind, watch.address, watch.patterns, watch.every_s, watch.target) == \
        ("inbox", ADDRESS, ("invoice",), 3600, ADDRESS)
    assert monitor.add_inbox(ADDRESS, ["Invoice"]) is watch
    assert world.inbox.asked == 0, "adding a watch read the inbox"


def test_the_first_look_is_a_baseline_and_new_mail_is_reported(world):
    monitor = world.make()
    watch = monitor.add_inbox(ADDRESS)
    world.inbox.mail = [message("m1", "Old news")]
    monitor.poll()
    assert world.events == [], "mail already there was reported as new"
    world.inbox.mail = [message("m2", "Your statement is ready"), message("m1", "Old news")]
    world.clock.later()
    monitor.poll()
    assert world.events.names() == ["mail.item", "mail.changed"]
    item, changed = world.events[0][1], world.events[1][1]
    assert (item["watch"], item["address"], item["subject"], item["id"]) == \
        (watch.id, ADDRESS, "Your statement is ready", "m2")
    assert changed["new"] == 1 and changed["subjects"] == ["Your statement is ready"]


def test_an_inbox_is_read_no_more_often_than_asked(world):
    monitor = world.make()
    monitor.add_inbox(ADDRESS)
    monitor.poll()
    monitor.poll()
    assert world.inbox.asked == 1
    world.clock.later()
    monitor.poll()
    assert world.inbox.asked == 2


def test_words_narrow_what_is_reported(world):
    monitor = world.make()
    monitor.add_inbox(ADDRESS, ["invoice"])
    monitor.poll()
    world.inbox.mail = [message("a", "Invoice 42"), message("b", "Lunch?", sender="Sam")]
    world.clock.later()
    monitor.poll()
    assert [p["subject"] for name, p in world.events if name == "mail.item"] == ["Invoice 42"]


def test_a_problem_with_the_sign_in_pauses_the_watch_and_keeps_what_was_seen(world):
    monitor = world.make()
    watch = monitor.add_inbox(ADDRESS)
    world.inbox.mail = [message("m1", "Old news")]
    monitor.poll()
    world.inbox.problem = "Google no longer accepts Akira's sign-in. Connect it again."
    world.clock.later()
    monitor.poll()
    assert watch.paused == world.inbox.problem and world.events == []
    world.inbox.problem = ""
    world.inbox.mail = [message("m2", "New"), message("m1", "Old news")]
    world.clock.later()
    monitor.poll()
    assert watch.paused == "" and [p["subject"] for n, p in world.events if n == "mail.item"] == ["New"]


def test_revoking_mail_read_pauses_the_watch_and_forgets(world):
    monitor = world.make()
    watch = monitor.add_inbox(ADDRESS)
    world.inbox.mail = [message("m1", "Old news")]
    monitor.poll()
    world.policy.revoke("mail.read")
    world.clock.later()
    monitor.poll()
    assert watch.paused.startswith("Not permitted")
    world.policy.grant("mail.read", (ADDRESS,))
    world.inbox.mail = [message("m2", "Arrived meanwhile"), message("m1", "Old news")]
    world.clock.later()
    monitor.poll()
    assert world.events == [], "mail that arrived while it could not look was reported"
    assert "watch_inbox" in (world.tmp / "audit.jsonl").read_text(encoding="utf-8")


def test_what_was_seen_is_kept_across_a_restart(world):
    monitor = world.make()
    monitor.add_inbox(ADDRESS)
    world.inbox.mail = [message("m1", "Old news")]
    monitor.poll()
    restarted = world.make()
    assert [w.kind for w in restarted.watches()] == ["inbox"]
    world.inbox.mail = [message("m2", "While closed"), message("m1", "Old news")]
    world.clock.later()
    restarted.poll()
    assert [p["subject"] for n, p in world.events if n == "mail.item"] == ["While closed"]


def test_notices_say_what_arrived():
    assert describe_event("mail.changed", {"address": ADDRESS, "new": 2,
                                           "subjects": ["Invoice 42", "Receipt"]}) == \
        f"2 new in {ADDRESS}. Invoice 42; Receipt"
    assert describe_event("mail.item", {"from": "Bank", "subject": "Statement"}) == \
        "From Bank: Statement."


def test_the_gmail_inbox_is_connected_mail_and_reads_the_last_week(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.json")
    store.save(google.Account(ADDRESS, ("mail",), 1.0))
    store.save(google.Account("calendar.only@gmail.com", ("calendar",), 1.0))
    asked = []

    def search(accounts, address, query, *, policy, audit, actor, limit=10):
        asked.append((address, query, actor))
        return [message("m1", "Hello")]

    monkeypatch.setattr(gmail_inbox.gmail, "search", search)
    inbox = gmail_inbox.GmailInbox(GoogleAccounts(vault=SecretStore(tmp_path / "s"), store=store),
                                   policy=lambda: Policy())
    assert inbox.connected(ADDRESS) and not inbox.connected("calendar.only@gmail.com")
    assert [m.subject for m in inbox.recent(ADDRESS)] == ["Hello"]
    assert asked == [(ADDRESS, "in:inbox newer_than:8d", "monitor")]


def test_the_bridge_adds_an_inbox_and_says_why_not():
    pytest.importorskip("PySide6.QtCore")
    from akira.ui.bridge.monitor import MonitorBridge

    policy = Policy()
    policy.grant("mail.read", (ADDRESS,))
    bridge = MonitorBridge(Monitor(WatchStore(), policy=lambda: policy, publish=lambda *a: None,
                                   inbox=FakeInbox()), audit=AuditLog())
    assert "not connected" in bridge.addInboxWatch("someone@gmail.com", [], 0)
    assert bridge.addInboxWatch(ADDRESS, ["invoice"], 30) == ""
    [row] = bridge.watches
    assert (row["kind"], row["address"], row["url"], row["every"]) == ("inbox", ADDRESS, "", 30)
