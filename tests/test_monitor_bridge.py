"""The `Monitor` bridge: adding a watch is held to its permission and recorded,
and a notice from a job's thread arrives on the UI thread.
"""

from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from protege.core.agents.monitor import Monitor, WatchStore  # noqa: E402
from protege.core.permissions import AuditLog, Policy  # noqa: E402
from protege.ui.bridge.monitor import MonitorBridge  # noqa: E402


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return predicate()


@pytest.fixture
def setup(tmp_path, app):
    folder = tmp_path / "Inbox"
    folder.mkdir()
    live = Policy()
    audit = AuditLog(tmp_path / "audit.jsonl")
    monitor = Monitor(WatchStore(tmp_path / "watches.json"), policy=lambda: live,
                      publish=lambda name, payload: None, audit=audit)
    bridge = MonitorBridge(monitor, audit=audit)
    monitor.set_on_change(bridge.changed)
    return bridge, live, folder, tmp_path


def test_a_watch_needs_the_permission_and_is_recorded(setup, app):
    bridge, live, folder, tmp_path = setup
    assert bridge.addWatch(str(folder), []).startswith("Not permitted")
    live.grant("files.read", (str(folder),))

    changes = []
    bridge.watchesChanged.connect(lambda: changes.append(1))
    assert bridge.addWatch(str(folder), ["*.pdf"]) == ""
    assert pump_until(app, lambda: changes)
    [row] = bridge.watches
    assert row["patterns"] == ["*.pdf"] and row["paused"] == "" and row["lastChange"] == 0.0
    assert "watch_folder" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")

    assert bridge.removeWatch(row["id"]) == "" and bridge.watches == []
    assert bridge.removeWatch(row["id"]) == "That is not being watched."


def test_a_page_watch_needs_its_site_allowed_and_is_recorded_without_its_query(setup, app):
    bridge, live, _folder, tmp_path = setup
    address = "https://example.com/news?key=secret"
    assert bridge.addPageWatch(address, [], 0).startswith("Not permitted")
    live.grant("net.http", ("example.com",))
    assert bridge.addPageWatch(address, ["sale"], 30) == ""
    [row] = bridge.watches
    assert (row["kind"], row["url"], row["patterns"], row["every"]) == \
        ("page", "https://example.com/news?…", ["sale"], 30)
    assert (row["folder"], row["title"], row["lastLook"]) == ("", "", 0.0)
    log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "watch_page" in log and "secret" not in log
    assert bridge.addFeedWatch("https://example.com/feed.xml", [], 5).startswith(
        "A page or a feed is looked at no more often")


def test_a_notice_from_another_thread_arrives_on_this_one(setup, app):
    bridge, *_ = setup
    heard = []
    bridge.noticed.connect(lambda title, text: heard.append((title, text,
                                                             threading.get_ident())))
    worker = threading.Thread(target=bridge.notify, args=("Inbox", "Something arrived."))
    worker.start()
    worker.join()

    assert pump_until(app, lambda: heard)
    assert heard[0][:2] == ("Inbox", "Something arrived.")
    assert heard[0][2] == threading.get_ident(), "the notice was not carried to the UI thread"
    assert bridge.notices[0]["title"] == "Inbox"
    bridge.clearNotices()
    assert bridge.notices == []
