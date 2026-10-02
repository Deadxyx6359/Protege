"""Choosing Claude in the real window: the Model menu, and the key sheet it opens."""

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
from PySide6.QtCore import QMetaObject, QObject, Q_ARG
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context

app = QGuiApplication([]); configure_application(app)
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(1100); win.setHeight(760); QTest.qWait(100)

menu = win.findChild(QQuickItem, 'chatModel')
assert menu is not None and menu.isVisible(), 'the Model menu is in the composer'
sheet = win.findChild(QObject, 'claudeSheet')
assert not sheet.property('opened')

composer = win.findChild(QObject, 'workspaceComposer')
QMetaObject.invokeMethod(composer, 'modelSelected', Q_ARG('QString', 'claude')); QTest.qWait(120)
assert sheet.property('opened'), 'no key yet: the key sheet opens'
assert ctx.chat.model == 'local', 'not chosen until a key is in'
connect = win.findChild(QQuickItem, 'connectClaude')
assert connect.isVisible() and not connect.property('enabled'), 'nothing to connect yet'
assert win.findChild(QQuickItem, 'claudeKey').isVisible()
QMetaObject.invokeMethod(sheet, 'close'); QTest.qWait(80)
assert not warnings, '\n'.join(warnings)
ctx.close(); print('CLAUDE_OK')
'''


def test_choosing_claude_without_a_key_opens_the_key_sheet(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1")
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO)], env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CLAUDE_OK" in result.stdout
