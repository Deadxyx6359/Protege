"""The real window, closed with Akira kept running, and with it not; and Ctrl+Q.

In a Python of its own: quitting is for the whole process.
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
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QMetaObject, QObject, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context

class Tray:
    def __init__(self): self.messages = []
    def showMessage(self, title, text, icon, msecs): self.messages.append(title)
    def hide(self): pass

app = QGuiApplication([]); configure_application(app)
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
ctx.config.preload = False  # coming back would load the real model
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(1100); win.setHeight(760); QTest.qWait(100)
background, tray = ctx.background, Tray()
exits = []
background._leave = exits.append
background._priority = lambda on: None  # test_quiet tests the real one
background.attach(app, win, call_window=win.findChild(QWindow, 'voiceCallWindow'), tray=tray)

# Closed with Akira kept running: hidden, not gone, and said once.
assert background.hidesOnClose and not app.quitOnLastWindowClosed()
win.close(); QTest.qWait(80)
assert not win.isVisible() and background.hidden
assert tray.messages == ['Akira is still running'], tray.messages
background.showWindow(); QTest.qWait(80)
assert win.isVisible() and not background.hidden
win.close(); QTest.qWait(80)
assert tray.messages == ['Akira is still running'], 'told once'
background.showWindow(); QTest.qWait(80)

# The setting, in Settings: off, closing quits as it always did.
settings = win.findChild(QObject, 'settingsSheet')
QMetaObject.invokeMethod(settings, 'open'); QTest.qWait(80)
toggle = win.findChild(QObject, 'keepRunningToggle')
assert toggle is not None and toggle.property('checked')
assert win.findChild(QObject, 'quitAkira') is not None
background.keepRunning = False; QTest.qWait(40)
assert not toggle.property('checked') and app.quitOnLastWindowClosed()
background.keepRunning = True; QTest.qWait(40)
QMetaObject.invokeMethod(settings, 'close'); QTest.qWait(80)

# The icon's "New chat" reaches the window's own.
QMetaObject.invokeMethod(win, 'newChat'); QTest.qWait(40)

# Ctrl+Q ends Akira, past a window that would otherwise hide itself.
win.requestActivate(); QTest.qWait(40)
QTest.keyClick(win, Qt.Key_Q, Qt.ControlModifier); QTest.qWait(80)
assert background.quitting and exits == [0], exits
assert not win.isVisible()
assert not warnings, '\n'.join(warnings)
ctx.close(); print('BACKGROUND_OK')
'''


def test_the_window_closes_to_the_clock_and_ctrl_q_quits(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1")
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO)], env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BACKGROUND_OK" in result.stdout
