"""Adding documents to the library from the window, and taking them out."""
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QMetaObject, QObject, QPointF, Q_ARG, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(1100); win.setHeight(800); QTest.qWait(80)
QMetaObject.invokeMethod(win, 'selectWorkspace', Q_ARG('QVariant', 'documents')); QTest.qWait(120)
def walk(it, name):
    for child in it.childItems():
        if child.objectName() == name and child.isVisible():
            return child
        found = walk(child, name)
        if found is not None:
            return found
    return None
def click(name):
    it = walk(win.contentItem(), name); assert it is not None, name
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier,
                     it.mapToScene(QPointF(it.width() / 2, it.height() / 2)).toPoint()); QTest.qWait(80)
assert walk(win.contentItem(), 'libraryPanel') is not None, 'no library in the Documents view'
assert walk(win.contentItem(), 'libraryAddFiles') is not None
assert walk(win.contentItem(), 'libraryAddFolder') is not None
source = Path(sys.argv[2]) / 'DS12288.md'
source.write_text('# STM32G474 datasheet\nPA0 is ADC12_IN1.', encoding='utf-8')
said = ctx.documents.addFiles([source.as_uri()]); QTest.qWait(80)
assert said == 'Added 1 file.', said
policy = ctx.permissions.policy
library = ctx.documents.libraryFolder
assert policy.allows('docs.read', library) and policy.allows('files.read', library)
assert walk(win.contentItem(), 'libraryRemove_DS12288.md') is not None
click('libraryRemove_DS12288.md')
click('libraryConfirmRemove_DS12288.md')
assert ctx.documents.library == [] and not (Path(library) / 'DS12288.md').exists()
assert source.exists(), 'the person own file was deleted'
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('LIBRARY_UI_OK')
'''


def test_the_library_in_the_window(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1")
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO), str(tmp_path)],
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LIBRARY_UI_OK" in result.stdout
