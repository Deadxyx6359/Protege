"""The interface's own ways out: the QML engine refuses the network, and a
picture in a message is served as a link rather than loaded.

Nothing here could leave the machine even if the guard failed: every address is
127.0.0.1, at a port nothing listens on.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtNetwork")

from PySide6.QtCore import QCoreApplication, QUrl  # noqa: E402
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest  # noqa: E402

from akira.core.conversation import Message  # noqa: E402
from akira.security import qtguard  # noqa: E402
from akira.security.qtguard import RefusingAccessManager, inert_markdown  # noqa: E402
from akira.ui.bridge.chat import MessageListModel  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def finished(app, reply, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not reply.isFinished() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return reply.isFinished()


# -- the access manager ------------------------------------------------------------------------


def test_a_web_address_is_refused_without_being_sent(app):
    manager = RefusingAccessManager()
    reply = manager.get(QNetworkRequest(QUrl("https://127.0.0.1:9/picture.png?said=secret")))
    assert finished(app, reply)
    assert reply.error() != QNetworkReply.NetworkError.NoError
    assert reply.url().isEmpty(), "the request still carried its address"
    assert qtguard.refused[-1] == "https://127.0.0.1:9/picture.png?…"


def test_a_file_on_another_machine_is_refused(app):
    # file://server/share is a network share on Windows, not a file here.
    manager = RefusingAccessManager()
    reply = manager.get(QNetworkRequest(QUrl("file://127.0.0.1/share/picture.png")))
    assert finished(app, reply)
    assert reply.error() != QNetworkReply.NetworkError.NoError and reply.url().isEmpty()


def test_a_file_on_this_computer_still_loads(app, tmp_path):
    local = tmp_path / "note.txt"
    local.write_bytes(b"from this computer")
    manager = RefusingAccessManager()
    reply = manager.get(QNetworkRequest(QUrl.fromLocalFile(str(local))))
    assert finished(app, reply)
    assert reply.error() == QNetworkReply.NetworkError.NoError
    assert reply.readAll().data() == b"from this computer"


# -- the engine the application uses ----------------------------------------------------------

# Every way QML fetches by itself. The probe runs in its own process because it
# needs a QGuiApplication, and this one may already hold a QCoreApplication.
QML = """
import QtQuick
Window {
    width: 200; height: 200; visible: true
    Image { source: "https://127.0.0.1:9/image.png?said=secret" }
    Text { y: 40; textFormat: Text.MarkdownText; text: "![a](https://127.0.0.1:9/markdown.png)" }
    Text { y: 80; text: "<b>x</b><img src='https://127.0.0.1:9/html.png'>" }
    FontLoader { source: "https://127.0.0.1:9/font.ttf" }
    Component.onCompleted: {
        var request = new XMLHttpRequest();
        request.open("GET", "https://127.0.0.1:9/xhr");
        request.send();
    }
}
"""

PROBE = r"""
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
from akira.security import qtguard
from akira.ui.engine import build_engine
engine, theme = build_engine()
engine.loadData(sys.argv[2].encode(), QUrl.fromLocalFile(os.path.join(sys.argv[1], "probe.qml")))
wanted, deadline = int(sys.argv[3]), time.monotonic() + 10
while len(set(qtguard.refused)) < wanted and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
print(json.dumps(sorted(set(qtguard.refused))))
"""

EXPECTED = sorted(["https://127.0.0.1:9/image.png?…", "https://127.0.0.1:9/markdown.png",
                   "https://127.0.0.1:9/html.png", "https://127.0.0.1:9/font.ttf",
                   "https://127.0.0.1:9/xhr"])


def test_the_applications_engine_refuses_every_way_qml_fetches(tmp_path):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-c", PROBE, str(REPO), QML, str(len(EXPECTED))],
                          env=env, capture_output=True, text=True, timeout=120, cwd=tmp_path)
    assert done.returncode == 0, done.stderr[-2000:]
    assert json.loads(done.stdout.strip().splitlines()[-1]) == EXPECTED


# -- pictures in messages ----------------------------------------------------------------------


@pytest.mark.parametrize("markdown,inert", [
    ("![a](https://x.example/p.png)", "\\![a](https://x.example/p.png)"),
    ("![a][r]\n\n[r]: file://server/share/p.png", "\\![a][r]\n\n[r]: file://server/share/p.png"),
    ("![a](//server/share/p.png)", "\\![a](//server/share/p.png)"),
    ("!![a](u)", "!\\![a](u)"),
    ("\\![a](u)", "\\![a](u)"),
    ("\\\\![a](u)", "\\\\\\![a](u)"),
    ("Hello! [a link](u) and `code`.", "Hello! [a link](u) and `code`."),
])
def test_a_picture_in_markdown_becomes_a_link(markdown, inert):
    assert inert_markdown(markdown) == inert
    assert inert_markdown(inert) == inert, "making it inert twice changed it"


def test_the_chat_serves_pictures_as_links_and_keeps_the_words(app):
    model = MessageListModel()
    said = "Here: ![chart](file://server/share/chart.png)"
    reply, failure = Message("assistant", said), Message("assistant", "![x](y)", error=True)
    typed = Message("user", "What is ![this](y)?")
    model.reset([reply, failure, typed])
    shown = model.data(model.index(0, 0), MessageListModel.TextRole)
    assert shown == "Here: \\![chart](file://server/share/chart.png)"
    assert reply.text == said, "the transcript was changed"
    assert model.data(model.index(1, 0), MessageListModel.TextRole) == "![x](y)", \
        "an error is plain text and was altered"
    assert model.data(model.index(2, 0), MessageListModel.TextRole) == "What is ![this](y)?", \
        "the person's own words are plain text and were altered"
