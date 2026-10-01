"""Adding the whole-web search's key, in the real Accounts sheet, by mouse and keys."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtQml")
REPO = Path(__file__).resolve().parent.parent

PROBE = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from akira.core.net.search import TAVILY_SECRET
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context

app = QGuiApplication([]); configure_application(app)
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
ctx.permissions.policy.grant("web.search")
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(1100); win.setHeight(760); win.requestActivate(); QTest.qWait(80)
sheet = win.findChild(QObject, 'accountsSheet')

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
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier,
                     it.mapToScene(QPointF(it.width() / 2, it.height() / 2)).toPoint()); QTest.qWait(80)
def run(js):
    expression = QQmlExpression(QQmlEngine.contextForObject(sheet), sheet, js)
    result = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    QTest.qWait(60)
    # evaluate() gives the value and whether it was undefined.
    return result[0] if isinstance(result, tuple) else result

# From Settings, straight to the key: on its fourth tab, Search was not found.
settings = win.findChild(QObject, 'settingsSheet')
QMetaObject.invokeMethod(settings, 'open'); QTest.qWait(150)
assert item('openSearch').property('text') == 'Add key'
click(item('openSearch')); QTest.qWait(120)
assert sheet.property('opened') and not settings.property('opened')
assert run('section') == 'search'
assert item('searchSetup') and walk(win.contentItem(), 'searchConnected') is None
add = item('connectSearch')
assert not add.property('enabled'), 'nothing to add yet'

# What is not a key is refused before anything is sent, and the field is cleared.
click(item('searchKey'))
for ch in 'my password':
    QTest.keyClick(win, ch)
QTest.qWait(40)
assert run('searchKey') == 'my password'
click(item('connectSearch'))
assert 'That is not a Tavily key' in item('accountFeedback').property('text')
assert run('searchKey') == '' and not ctx.accounts._vault.has(TAVILY_SECRET)

# With a key kept, the section says how many searches were made, and the key can go.
vault = ctx.accounts._vault
vault.put(TAVILY_SECRET, 'tvly-dev-0123456789abcdef')
ctx.accounts.searchChanged.emit(); QTest.qWait(80)
assert walk(win.contentItem(), 'searchKey') is None
assert item('searchUsage').property('text') == '0 of 950 searches this month'
click(item('disconnectSearch'))
assert not vault.has(TAVILY_SECRET)
assert 'Removed. Searches go to DuckDuckGo again.' in item('accountFeedback').property('text')
assert item('searchKey')

# Closed, a key half typed is forgotten.
click(item('searchKey'))
for ch in 'tvly-half':
    QTest.keyClick(win, ch)
QMetaObject.invokeMethod(sheet, 'close', Qt.DirectConnection); QTest.qWait(80)
assert run('searchKey') == ''
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('SEARCH_KEY_OK')
'''


def test_adding_and_removing_the_search_key_in_the_window(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1")
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO)], env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SEARCH_KEY_OK" in result.stdout
