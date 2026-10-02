"""The page takes no press while a sheet, a confirmation or a link's question is over it.

A press on a sheet's button was also taken, passively, by the page control under it;
when the press closed the sheet, the release went to that control (Save in the
calendar's editor chose the day beneath it).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtQml")
REPO = Path(__file__).resolve().parent.parent

PROBE = r'''
import sys, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QMetaObject, QObject, Q_ARG, Qt
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
page = win.findChild(QQuickItem, 'workspaceLayout')
assert page.isEnabled() and not win.property('overlayUp')

for name in ('settingsSheet', 'voiceSheet', 'claudeSheet'):
    sheet = win.findChild(QObject, name)
    QMetaObject.invokeMethod(sheet, 'open'); QTest.qWait(60)
    assert win.property('overlayUp') and not page.isEnabled(), name
    QMetaObject.invokeMethod(sheet, 'close'); QTest.qWait(60)
    assert not win.property('overlayUp') and page.isEnabled(), name

# The calendar's editor, made inside its page and shown over the whole window.
win.setProperty('currentNav', 'calendar'); QTest.qWait(80)
editor = win.findChild(QObject, 'calendarEventSheet')
QMetaObject.invokeMethod(editor, 'openNew', Q_ARG('QVariant', '2026-10-02'),
                         Q_ARG('QVariant', ''), Q_ARG('QVariant', 'x')); QTest.qWait(60)
assert not page.isEnabled()
QMetaObject.invokeMethod(editor, 'close'); QTest.qWait(60)
assert page.isEnabled()

# A confirmation waits for the person, over everything.
answer = {}
asking = threading.Thread(target=lambda: answer.setdefault('ok', ctx.confirm.ask('Send it?')), daemon=True)
asking.start()
for _ in range(50):
    QTest.qWait(40)
    if win.property('overlayUp'):
        break
assert win.property('overlayUp') and not page.isEnabled()
ctx.confirm.close()   # refuses what is waiting, as closing Akira does
asking.join(5); QTest.qWait(80)
assert page.isEnabled()
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('SHEETS_OK')
'''


def test_the_page_takes_no_press_while_something_is_over_it(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1")
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO)], env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SHEETS_OK" in result.stdout
