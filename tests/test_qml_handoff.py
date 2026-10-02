""""Do it" under an answer in the real window: offered, pressed, and the team at work."""

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
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context

app = QGuiApplication([]); configure_application(app)
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
chat = ctx.chat
handed = []
chat._hand_off = lambda task, folder: handed.append((task, folder)) or ""
chat._folder = lambda: "C:\\work\\SharpLCD"
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(1100); win.setHeight(760); QTest.qWait(100)

row = win.findChild(QQuickItem, 'handOffRow')
assert row is not None and not row.isVisible(), 'nothing to do yet'
chat._conversation.add('user', 'Write the refresh function.')
chat._conversation.add('assistant', 'Add this to Core/Src/sharp_lcd.c:\n```c\nvoid R(void) {}\n```')
chat._model.reset(chat._conversation.messages); QTest.qWait(150)
assert row.isVisible(), 'offered under an answer with work in it'
note = win.findChild(QObject, 'handOffNote')
assert note.property('text') == 'The software team makes these changes in SharpLCD, asking before each one.', note.property('text')

button = win.findChild(QQuickItem, 'handOffButton')
centre = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, centre); QTest.qWait(150)
assert len(handed) == 1 and handed[0][1] == 'C:\\work\\SharpLCD', handed
assert chat.handingOff
assert note.property('text') == 'The software team is working on it.'
assert not button.isVisible() and win.findChild(QQuickItem, 'handOffStop').isVisible()

chat.hand_off_finished(True, 'Wrote it, and it builds.', 'answered'); QTest.qWait(150)
assert chat._conversation.messages[-1].text.startswith('**The software team finished.**')
assert not warnings, '\n'.join(warnings)
ctx.close(); print('HANDOFF_OK')
'''


def test_do_it_is_offered_pressed_and_shows_the_team_at_work(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1")
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO)], env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HANDOFF_OK" in result.stdout
