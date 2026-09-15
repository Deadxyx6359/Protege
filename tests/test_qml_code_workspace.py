"""Code workflow, plain-text patches and compact layouts at two display scales."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parent.parent
PROBE = r'''
import os, sys, time, subprocess
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Qt, QPointF
from PySide6.QtGui import QGuiApplication, QFont, QFontDatabase
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context
from akira.core.tools.builtin import coding
from tools.preview import _settle
app = QGuiApplication([]); configure_application(app)
for name in ['SegUIVar.ttf', 'CascadiaMono.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
app.setFont(QFont('Segoe UI'))
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []
engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.requestActivate()
win.setProperty('currentNav', 'code')
QTest.qWait(40)
view = win.findChild(QObject, 'codeView')
sheet = win.findChild(QObject, 'codeReviewSheet')
review = win.findChild(QObject, 'codeReviewButton')
assert view.property('visible') and not review.property('visible')

def press(item):
    QMetaObject.invokeMethod(item, 'forceActiveFocus', Qt.DirectConnection)
    QTest.keyClick(win, Qt.Key_Return); QTest.qWait(30)

def wait():
    deadline = time.monotonic() + 12
    while ctx.coding.busy and time.monotonic() < deadline:
        QTest.qWait(10)
        time.sleep(.005)  # Let Python's pipe-reader threads run between Qt waits.
    if ctx.coding.busy:
        import faulthandler
        faulthandler.dump_traceback()
    assert not ctx.coding.busy, ctx.coding.operation
    QTest.qWait(50)

def capture(name):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        target = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ.get('QT_SCALE_FACTOR', '1')
        target.mkdir(parents=True, exist_ok=True)
        _settle(win, 150)
        assert win.grabWindow().save(str(target / (name + '.png')))

press(win.findChild(QObject, 'codeProjectSetup'))
project_sheet = win.findChild(QObject, 'projectSheet')
assert project_sheet.property('opened')
QTest.keyClick(win, Qt.Key_Escape)
folder = Path(sys.argv[2]) / 'Aurora project'; folder.mkdir()
def git(*args):
    return subprocess.run(['git', '-C', str(folder), *args], check=True, capture_output=True, text=True).stdout
git('init', '--initial-branch=main')
path = folder / 'scene.py'
path.write_text('before\n' * 80, encoding='utf-8')
note = folder / 'observations.txt'
note.write_text('earlier observation\n', encoding='utf-8')
git('add', 'scene.py', 'observations.txt')
git('-c', 'user.name=Preview', '-c', 'user.email=ui@example.test', '-c', 'commit.gpgSign=false', 'commit', '-m', 'Compose a quiet scene')
path.write_text('after <img src="https://example.test/private">\n' * 80 + '#' * 320, encoding='utf-8')
note.write_text('new observation\n', encoding='utf-8')
created = ctx.projects.create('Aurora - a long project name', str(folder))
assert created == '', created
assert review.property('visible')
press(review); wait()
assert sheet.property('opened') and 'Not permitted' in ctx.coding.error
capture('permission-needed')
QTest.keyClick(win, Qt.Key_Escape)
assert win.activeFocusItem() == review
assert ctx.permissions.grant('vcs.read', [str(folder)]) == ''
for appearance in ['dark', 'light']:
    ctx.theme.mode = appearance
    for width in [900, 1440]:
        win.setWidth(width); win.setHeight(600 if width == 900 else 900)
        capture(appearance + '-' + str(width) + '-code')
        press(review); wait()
        text = win.findChild(QObject, 'codeReviewText')
        assert '<img src=' in text.property('text') and text.property('readOnly')
        expr = QQmlExpression(engine.rootContext(), text, 'textFormat === 0')
        assert expr.evaluate()[0] and not expr.hasError()
        for name in ['codeReviewModes', 'codeReviewRefresh', 'codeReviewText']:
            item = win.findChild(QObject, name)
            at = item.mapToScene(QPointF(0, 0))
            assert at.x() >= 0 and at.y() >= 0 and at.y() < win.height(), (name, at)
        # Long lines stay selectable and scroll rather than widening the sheet.
        assert text.width() > win.width()
        capture(appearance + '-' + str(width) + '-patch')
        assert len(ctx.coding.patches) == 2
        selected = next(p['id'] for p in ctx.coding.patches if p['label'] == 'observations.txt')
        picker = win.findChild(QObject, 'codePatchPicker')
        picker.picked.emit(selected); QTest.qWait(40)
        assert 'new observation' in text.property('text') and 'a/scene.py' not in text.property('text')
        quick_document = text.property('textDocument')
        document = quick_document.textDocument()
        block = document.begin(); highlighted = False
        while block.isValid():
            if block.text() == '+new observation':
                highlighted = bool(block.layout().formats())
            block = block.next()
        assert highlighted, 'plain-text additions should receive diff formatting'
        capture(appearance + '-' + str(width) + '-selected-file')
        picker.picked.emit(''); QTest.qWait(20)
        for i in range(25):
            QTest.keyClick(win, Qt.Key_Tab, Qt.ShiftModifier if i % 3 == 0 else Qt.NoModifier)
            assert sheet.property('ownsFocus')
        modes = win.findChild(QObject, 'codeReviewModes')
        modes.selected.emit('staged'); wait()
        assert ctx.coding.preview == 'No staged changes.'
        modes.selected.emit('history'); wait()
        assert 'Compose a quiet scene' in ctx.coding.preview
        capture(appearance + '-' + str(width) + '-history')
        modes.selected.emit('working'); wait()
        QTest.keyClick(win, Qt.Key_Escape)
        assert not sheet.property('opened')

ctx.permissions.revoke('vcs.read')
assert not ctx.coding.preview and not ctx.coding.folder
# No editor process is actually launched by the preview.
coding._find_vscode = lambda: None
assert ctx.permissions.grant('files.read', [str(folder)]) == ''
press(win.findChild(QObject, 'codeEditorButton')); wait()
assert 'VS Code was not found' in ctx.coding.error
assert not ctx.agents.busy
ctx.projects.openProject('')
assert not ctx.coding.error and not ctx.coding.notice and not ctx.coding.folder
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close()
print('CODE_UI_OK')
'''


@pytest.mark.parametrize('scale', ['1', '1.5'])
def test_code_workspace(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'), QT_QPA_PLATFORM='offscreen',
               QT_QUICK_BACKEND='software', QML_DISABLE_DISK_CACHE='1', QT_SCALE_FACTOR=scale)
    env.pop('PROTEGE_CONFIG_DIR', None)
    run = subprocess.run([sys.executable, '-c', PROBE, str(REPO), str(tmp_path)], env=env,
                         capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'CODE_UI_OK' in run.stdout
