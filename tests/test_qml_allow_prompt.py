"""The question for a site or folder next to the ones allowed, in the real window."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import os, sys, threading, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from akira.core.permissions.asking import Request
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
for name in ['SegUIVar.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
assert not ctx.permissions.grant('net.http', ['en.wikipedia.org'])
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(1100); win.setHeight(700); win.requestActivate(); QTest.qWait(80)
def walk(it, name):
    for child in it.childItems():
        if child.objectName() == name and child.isVisible():
            return child
        found = walk(child, name)
        if found is not None:
            return found
    return None
def item(name):
    found = walk(win.contentItem(), name)
    assert found is not None, name
    return found
def click(it):
    at = it.mapToScene(QPointF(it.width() / 2, it.height() / 2)).toPoint()
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, at); QTest.qWait(60)
def ask(page='https://www.bbc.co.uk/news/science-12345'):
    got = []
    request = Request('net.http', 'www.bbc.co.uk', page, 'bbc.co.uk', 'researcher', 'Read a web page.')
    worker = threading.Thread(target=lambda: got.append(ctx.allow.ask(request)), daemon=True)
    worker.start()
    deadline = time.monotonic() + 5
    while walk(win.contentItem(), 'allowPrompt') is None and time.monotonic() < deadline:
        QTest.qWait(20)
    return worker, got
def settle(worker, got):
    deadline = time.monotonic() + 5
    while worker.is_alive() and time.monotonic() < deadline:
        QTest.qWait(20)
    return got[0] if got else None
prompt = win.findChild(QObject, 'allowPrompt')
assert prompt is not None and not prompt.property('visible')

worker, got = ask()
assert item('allowTitle').property('text') == 'Read a page on www.bbc.co.uk?'
assert 'science-12345' in item('allowDetail').property('text')
assert item('allowRefuse').property('activeFocus'), 'the safe answer is not focused'
if os.environ.get('AKIRA_REVIEW_DIR'):
    target = Path(os.environ['AKIRA_REVIEW_DIR']); target.mkdir(parents=True, exist_ok=True)
    for mode in ['dark', 'light']:
        ctx.theme.mode = mode; QTest.qWait(60)
        win.grabWindow().save(str(target / (mode + '-allow-prompt.png')))
click(item('allowOnce'))
assert settle(worker, got) == 'once' and not prompt.property('visible')
assert not ctx.permissions.policy.allows('net.http', 'www.bbc.co.uk')

worker, got = ask()
QTest.keyClick(win, Qt.Key_Escape)
assert settle(worker, got) == 'no'

worker, got = ask()
click(item('allowAlways'))
assert settle(worker, got) == 'always'
assert ctx.permissions.policy.allows('net.http', 'news.bbc.co.uk')
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('ALLOW_PROMPT_OK')
'''


@pytest.mark.parametrize("scale", ["1", "1.5"])
def test_the_allow_prompt_in_the_window(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1", QT_SCALE_FACTOR=scale)
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO)],
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALLOW_PROMPT_OK" in result.stdout
