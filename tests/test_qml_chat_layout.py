"""What sits under the last reply is not covered by the composer, or by what is behind it."""

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
from PySide6.QtCore import QObject, QPointF
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context

app = QGuiApplication([]); configure_application(app)
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
ctx.theme.mode = sys.argv[2]
chat = ctx.chat
chat._conversation.add("user", "Who won the game this week?")
chat._conversation.add("assistant", "The Broncos won 30-26.")
chat._model.reset(chat._conversation.messages)
chat._sources = [{"source": "web", "cite": "https://www.denverbroncos.com"}]
chat._context_note = "Read 1 page, 1 search."
chat.sourcesChanged.emit()
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(1100); win.setHeight(760); QTest.qWait(200)

def scene_rect(item):
    top = item.mapToScene(QPointF(0, 0))
    return top.y(), top.y() + item.height()

note = win.findChild(QQuickItem, 'contextSources')
backing = win.findChild(QQuickItem, 'composerBacking')
composer = win.findChild(QQuickItem, 'workspaceComposer')
assert note is not None and note.isVisible() and note.height() > 0
_, note_bottom = scene_rect(note)
above = scene_rect(backing)[0] if backing is not None and backing.isVisible() else scene_rect(composer)[0]
assert note_bottom <= above, (note_bottom, above)
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('LAYOUT_OK')
'''


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_the_context_note_is_clear_of_the_composer(tmp_path, mode):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1")
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO), mode], env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LAYOUT_OK" in result.stdout
