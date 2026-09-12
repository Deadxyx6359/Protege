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
import json, sys, threading, time
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

    script_errors = [line for line in errors.splitlines()
                     if "TypeError" in line or "ReferenceError" in line]
    assert script_errors == [], "\n".join(script_errors)
