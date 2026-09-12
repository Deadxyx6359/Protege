"""The views that make the backend usable, driven in the real interface.

Until these, nothing in the window used the Confirm, Permissions, Agents or
AgentTrace bridges: an irreversible action waited five minutes for a dialog
that did not exist and was refused, nothing could be granted, and agents could
be neither started nor watched. Each test runs the application's own window
offscreen, in its own process (it needs a QGuiApplication, and this process may
hold a QCoreApplication), with its settings in a temporary folder.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtQuick")

REPO = Path(__file__).resolve().parents[1]

PROBE = r"""
import json, os, sys, threading, time
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
from akira.core.agents.trace import Kind
from akira.ui.engine import build_engine, load
from akira.ui.shell import MAIN_QML, build_context

ctx = build_context(persist=False)
engine, theme = build_engine(theme=ctx.theme, context=ctx.as_context())
root = load(engine, MAIN_QML)
out = {}

def pump(seconds, until=lambda: False):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not until():
        app.processEvents()
        time.sleep(0.01)

def call(obj, name, *args):
    QMetaObject.invokeMethod(obj, name, Qt.DirectConnection, *[Q_ARG("QVariant", a) for a in args])

def plain(value):
    return value.toVariant() if hasattr(value, "toVariant") else value

# -- the confirmation ---------------------------------------------------------
dialog = root.findChild(QObject, "confirmDialog")
answers = []
def worker(summary):
    answers.append(ctx.confirm.ask(summary))
first = threading.Thread(target=worker, args=("Delete notes.md in C:/Notes",))
first.start()
pump(5, lambda: bool(dialog.property("visible")))
out["shown"] = bool(dialog.property("visible"))
out["summary"] = root.findChild(QObject, "confirmSummary").property("text")
call(dialog, "answer", True)
first.join(5)
pump(0.2)
out["hidden_after"] = not bool(dialog.property("visible"))
second = threading.Thread(target=worker, args=("Run build.py",))
second.start()
pump(5, lambda: bool(dialog.property("visible")))
call(dialog, "answer", False)
second.join(5)
out["answers"] = answers

# -- the permissions ----------------------------------------------------------
sheet = root.findChild(QObject, "permissionsSheet")
policy = ctx.permissions.policy
call(sheet, "setGranted", "notify.send", True)
out["notify"] = policy.granted("notify.send") is not None
call(sheet, "addScope", "net.http", "https://example.com/page")
out["refusal"] = sheet.property("notice")
out["refused_held"] = policy.granted("net.http") is not None
call(sheet, "addScope", "net.http", "example.com")
call(sheet, "addScope", "net.http", "docs.example.org")
out["sites"] = list(policy.granted("net.http").scopes)
call(sheet, "removeScope", "net.http", "example.com")
out["after_remove"] = list(policy.granted("net.http").scopes)
call(sheet, "removeScope", "net.http", "docs.example.org")
out["net_gone"] = policy.granted("net.http") is None
call(sheet, "setGranted", "notify.send", False)
out["notify_gone"] = policy.granted("notify.send") is None

# -- the agents ---------------------------------------------------------------
root.setProperty("currentNav", "agents")
pump(0.5)
view = root.findChild(QObject, "agentsView")
out["agents_visible"] = bool(view.property("visible"))
out["pipeline"] = root.findChild(QObject, "agentPipeline") is not None
trace = ctx.trace.trace
trace.emit(Kind.STARTED, "research", text="What changed?")
trace.emit(Kind.STARTED, "gatherer", text="What changed?")
trace.emit(Kind.TOOL_CALL, "gatherer", tool="read_file")
trace.emit(Kind.ANSWER, "gatherer", text="found three notes")
trace.emit(Kind.MESSAGE, "gatherer", to="analyst", text="found three notes")
trace.emit(Kind.STARTED, "analyst", text="What changed?")
pump(1, lambda: (plain(view.property("status")) or {}).get("analyst") == "working")
out["status"] = plain(view.property("status"))
out["passed"] = plain(view.property("passed"))

# -- where you are ------------------------------------------------------------
place = root.findChild(QObject, "placeSheet")
out["place_sheet"] = place is not None
# Granted outside the sheet, as another screen would, so the sheet's own copy
# of the grants is stale: allowing the weather's site must not drop this one.
policy.grant("net.http", ("example.com",))
call(place, "allowSite")
out["weather_site"] = sorted(policy.granted("net.http").scopes)
call(place, "setLocated", True)
out["located"] = policy.granted("location.read") is not None
call(place, "removeSite")
out["site_removed"] = sorted(policy.granted("net.http").scopes)
call(place, "setLocated", False)
out["unlocated"] = policy.granted("location.read") is None

# -- watching -----------------------------------------------------------------
root.setProperty("currentNav", "watching")
pump(0.3)
watching = root.findChild(QObject, "watchView")
out["watch_visible"] = bool(watching.property("visible"))
inbox = os.path.join(os.getcwd(), "inbox").replace("\\", "/")
os.makedirs(inbox)
watching.setProperty("kind", "folder")
watching.setProperty("folder", inbox)
call(watching, "submit")
out["folder_needs"] = watching.property("needs")
out["folder_refusal"] = watching.property("notice")
call(watching, "allowAndWatch")
out["watched"] = [[w["kind"], w["folder"]] for w in ctx.monitor.watches]
read = policy.granted("files.read")
out["read_scopes"] = list(read.scopes) if read else []
first = ctx.monitor.watches[0]["id"] if ctx.monitor.watches else ""
out["paired"] = [j["action"] for j in ctx.schedule.jobs if j["watch"] == first]
out["notices_needed"] = watching.property("needs")
call(watching, "allowNotices")
out["notices_allowed"] = policy.granted("notify.send") is not None
# A feed on a site not allowed yet: that site is added, and every other kept.
watching.setProperty("kind", "feed")
watching.setProperty("address", "https://news.example.org/feed.xml?key=private")
call(watching, "submit")
out["feed_needs"] = watching.property("needs")
call(watching, "allowAndWatch")
out["sites_after_feed"] = sorted(policy.granted("net.http").scopes)
out["feed_urls"] = [w["url"] for w in ctx.monitor.watches if w["kind"] == "feed"]
call(watching, "forget", first)
out["after_forget"] = [w["kind"] for w in ctx.monitor.watches]
out["jobs_after_forget"] = [j["name"] for j in ctx.schedule.jobs if j["watch"] == first]

# -- what must reach the person -----------------------------------------------
banner = root.findChild(QObject, "noticeBanner")
ctx.monitor.notify("Watching inbox", "In inbox: 1 new. <b>report.pdf</b>")
pump(0.3)
out["banners"] = banner.property("count")
ctx.schedule.criticalFound.emit(2)
pump(0.3)
out["banners_after_critical"] = banner.property("count")
out["critical_banners"] = banner.property("criticalCount")
out["notices"] = [n["title"] for n in ctx.monitor.notices]

# -- the schedule and the review ----------------------------------------------
from akira.core.review import Finding, Review, ensure_review_job
ensure_review_job(ctx.scheduler)
root.setProperty("currentNav", "schedule")
pump(0.3)
schedule = root.findChild(QObject, "scheduleView")
out["schedule_visible"] = bool(schedule.property("visible"))
def job(job_id):
    return next((j for j in ctx.schedule.jobs if j["id"] == job_id), None)
review_id = next(j["id"] for j in ctx.schedule.jobs if j["action"] == "security_review")
call(schedule, "removeJob", review_id)
out["review_kept"] = job(review_id) is not None
out["review_refusal"] = schedule.property("notice")
call(schedule, "pauseJob", review_id)
out["review_enabled"] = job(review_id)["enabled"]
told = next(j["id"] for j in ctx.schedule.jobs if j["action"] == "notify")
call(schedule, "pauseJob", told)
out["paused"] = not job(told)["enabled"]
call(schedule, "resumeJob", told)
out["resumed"] = job(told)["enabled"]
call(schedule, "removeJob", told)
out["removed"] = job(told) is None
ctx.schedule.on_review(Review(time.time(), 30, [Finding(
    "critical", "wide-read", "Reading is allowed across the whole of C:/",
    detail="files.read covers C:/", suggestion="Narrow it to the folders in use.",
    capability="files.read")]))
pump(0.3)
def texts_under(item):
    # The visual tree: what a ScrollView holds is not among its QObject children.
    found = []
    for child in item.childItems():
        value = child.property("text")
        if isinstance(value, str):
            found.append(value)
        found.extend(texts_under(child))
    return found
texts = texts_under(schedule)
out["finding_shown"] = "Reading is allowed across the whole of C:/" in texts
out["suggestion_shown"] = "Narrow it to the folders in use." in texts
print(json.dumps(out))
"""


@pytest.fixture
def run(tmp_path):
    def go(probe: str) -> tuple[dict, str]:
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
               "AKIRA_CONFIG_DIR": str(tmp_path / "cfg")}
        env.pop("PROTEGE_CONFIG_DIR", None)
        done = subprocess.run([sys.executable, "-c", probe, str(REPO)], env=env, cwd=tmp_path,
                              capture_output=True, text=True, timeout=180)
        assert done.returncode == 0, done.stderr[-3000:]
        return json.loads(done.stdout.strip().splitlines()[-1]), done.stderr
    return go


def test_the_views_work_in_the_window(run):
    out, errors = run(PROBE)
    assert out["shown"], "an agent asked and no dialog appeared"
    assert out["summary"] == "Delete notes.md in C:/Notes"
    assert out["hidden_after"] and out["answers"] == [True, False]

    assert out["notify"] and out["notify_gone"]
    assert "not a site" in out["refusal"] and not out["refused_held"], \
        "an address was granted as if it were a site"
    assert out["sites"] == ["example.com", "docs.example.org"]
    assert out["after_remove"] == ["docs.example.org"] and out["net_gone"]

    assert out["agents_visible"] and out["pipeline"]
    assert out["status"]["gatherer"] == "done" and out["status"]["analyst"] == "working"
    assert out["passed"] == {"gatherer>analyst": True}

    assert out["place_sheet"]
    assert out["weather_site"] == ["example.com", "open-meteo.com"], \
        "allowing the weather's site dropped a site allowed elsewhere"
    assert out["located"] and out["unlocated"]
    assert out["site_removed"] == ["example.com"]

    assert out["watch_visible"]
    assert out["folder_needs"] == "folder" and "Not permitted" in out["folder_refusal"]
    assert [kind for kind, _ in out["watched"]] == ["folder"]
    assert [Path(folder).name for _, folder in out["watched"]] == ["inbox"]
    assert [Path(scope).name for scope in out["read_scopes"]] == ["inbox"], \
        "more than the watched folder was allowed"
    assert out["paired"] == ["notify"], "asked to be told, and no notice job waits on the watch"
    assert out["notices_needed"] == "notices" and out["notices_allowed"]
    assert out["feed_needs"] == "site"
    assert out["sites_after_feed"] == ["example.com", "news.example.org"], \
        "allowing the feed's site dropped a site allowed elsewhere"
    # The key a private feed keeps in its query is never shown, only that there was one.
    assert out["feed_urls"] == ["https://news.example.org/feed.xml?…"]
    assert out["after_forget"] == ["feed"] and out["jobs_after_forget"] == [], \
        "a removed watch left its notice job waiting for events that will never come"

    assert out["banners"] == 1 and out["notices"] == ["Watching inbox"]
    assert out["banners_after_critical"] == 2 and out["critical_banners"] == 1

    assert out["schedule_visible"]
    assert out["review_kept"] and "cannot be removed" in out["review_refusal"], \
        "the security review could be removed from the window"
    assert out["review_enabled"], "the security review could be paused from the window"
    assert out["paused"] and out["resumed"] and out["removed"]
    assert out["finding_shown"] and out["suggestion_shown"]

    script_errors = [line for line in errors.splitlines()
                     if "TypeError" in line or "ReferenceError" in line]
    assert script_errors == [], "\n".join(script_errors)
