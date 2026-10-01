"""Adding documents to the library from the window, and taking them out."""
import os
from pathlib import Path
import subprocess
import sys
import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import sys, os, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QMetaObject, QObject, QPointF, Q_ARG, Qt
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
QFontDatabase.addApplicationFont('C:/Windows/Fonts/SegUIVar.ttf')
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
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
ctx.documents.openFolder(library)
deadline = time.monotonic() + 5
while ctx.documents.busy and time.monotonic() < deadline: QTest.qWait(20)
assert ctx.documents.folder
open_folder = ctx.documents.folder
ctx.documents.previewFile(str(Path(library) / 'DS12288.md'))
deadline = time.monotonic() + 5
while ctx.documents.busy and time.monotonic() < deadline: QTest.qWait(20)
selected_path = ctx.documents.selected['path']
assert selected_path
assert walk(win.contentItem(), 'libraryPanel') is None
click('toggleDocumentLibrary')
assert walk(win.contentItem(), 'libraryPanel') is not None
assert ctx.documents.folder == open_folder
for mode in ['light', 'dark']:
    ctx.theme.mode = mode
    win.setWidth(900); win.setHeight(600); QTest.qWait(80)
    actions = walk(win.contentItem(), 'documentActions')
    for button in actions.childItems():
        if button.isVisible():
            pos = button.mapToScene(QPointF(0, 0))
            assert pos.x() >= 0 and pos.x() + button.width() <= win.width()
    if os.environ.get('AKIRA_REVIEW_DIR'):
        out = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ['QT_SCALE_FACTOR']
        out.mkdir(parents=True, exist_ok=True)
        assert win.grabWindow().save(str(out / ('library-' + mode + '.png')))
click('toggleDocumentLibrary')
assert walk(win.contentItem(), 'libraryPanel') is None
assert ctx.documents.folder == open_folder
assert ctx.documents.selected['path'] == selected_path
click('toggleDocumentLibrary')
click('libraryRemove_DS12288.md')
click('libraryConfirmRemove_DS12288.md')
assert ctx.documents.library == [] and not (Path(library) / 'DS12288.md').exists()
assert source.exists(), 'the person own file was deleted'
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('LIBRARY_UI_OK')
'''


@pytest.mark.parametrize('scale', ['1', '1.5'])
def test_the_library_in_the_window(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1", QT_SCALE_FACTOR=scale)
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO), str(tmp_path)],
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LIBRARY_UI_OK" in result.stdout
