"""Review and explicitly publish a pipeline draft through the real UI and policy."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from akira.core.making.pipeline import Draft, Target
from akira.ui.engine import configure_application, build_engine, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
for name in ['SegUIVar.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
folder = Path(sys.argv[2]) / 'output'; folder.mkdir()
target = folder / 'weekly.md'
literal = '<img src="https://outside.invalid/image">'
body = '# Garden dispatch\n\n' + literal + '\n\nThe beans are up and the garden is ready for spring.'
ctx.drafts.store.add(Draft('first', 'Weekly garden', 'Write a short garden update.', 'Garden dispatch', body,
    'Check the dates and make the next steps clear. ' + literal, Target('file', path=str(target)), time.time()))
ctx.drafts.store.add(Draft('second', 'Ocean notes', 'Write a field note.', 'Ocean dispatch', 'Ocean notes.',
    'Clear.', Target('file', path=str(folder / 'ocean.md')), time.time()))
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.setProperty('currentNav', 'schedule'); QTest.qWait(60)
sheet = win.findChild(QObject, 'draftsSheet')
def invoke(obj, method, *args):
    assert QMetaObject.invokeMethod(obj, method, Qt.DirectConnection, *[Q_ARG('QVariant', a) for a in args])
    QTest.qWait(50)
def walk(item):
    yield item
    for child in item.childItems(): yield from walk(child)
def find(name):
    return next(i for i in walk(win.contentItem()) if i.objectName() == name)
def press(item):
    assert item.property('enabled')
    win.requestActivate(); invoke(item, 'forceActiveFocus'); QTest.keyClick(win, Qt.Key_Space); QTest.qWait(60)
def capture(label):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        p = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ.get('QT_SCALE_FACTOR', '1')
        p.mkdir(parents=True, exist_ok=True); QTest.qWait(80)
        assert win.grabWindow().save(str(p / (label + '.png')))
def finish_publish():
    deadline = time.monotonic() + 5
    while ctx.drafts.publishing and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    QTest.qWait(40)
    assert not ctx.drafts.publishing
capture('schedule')
press(find('openContentDrafts'))
assert sheet.property('opened') and not target.exists()
capture('draft-list')
press(find('reviewDraft_first'))
editor = find('draftEditor')
assert editor.property('text') == body
assert QQmlExpression(engine.rootContext(), editor, 'textFormat === 0').evaluate()[0]
assert str(target) in find('draftTarget').property('text')
editor.setProperty('text', body + '\nEdited by the person.'); QTest.qWait(30)
press(find('draftBack'))
assert sheet.property('selectedId') == 'first' and 'Save' in sheet.property('notice')
press(find('draftSave'))
assert ctx.drafts.text('first').endswith('Edited by the person.') and not target.exists()
for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    invoke(find('draftBack'), 'forceActiveFocus')
    invoke(sheet, 'scrollToTop'); capture(mode + '-draft-review')
    invoke(find('draftPublish'), 'forceActiveFocus'); capture(mode + '-draft-publish')
    # Exact destination is in the same visible action block, never hidden behind disclosure.
    destination = find('draftTarget')
    assert destination.mapToScene(destination.boundingRect().center()).y() > 120
    assert destination.mapToScene(destination.boundingRect().center()).y() < win.height() - 50
press(find('draftPublish')); finish_publish()
assert not target.exists() and ctx.drafts.waitingCount == 2
assert 'Not published' in sheet.property('notice')
ctx.permissions.policy.grant('files.write', (str(folder),))
ctx.permissions.grantsChanged.emit()
press(find('draftPublish')); finish_publish()
assert target.read_text(encoding='utf-8').rstrip().endswith('Edited by the person.')
assert ctx.drafts.waitingCount == 1 and not find('draftPublish').property('visible')
press(find('draftBack')); press(find('reviewDraft_second'))
press(find('draftDiscard'))
assert ctx.drafts.waitingCount == 1
press(find('draftDiscard'))
assert ctx.drafts.waitingCount == 0 and not (folder / 'ocean.md').exists()
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('DRAFT_UI_OK')
'''


@pytest.mark.parametrize('scale', ['1', '1.5'])
def test_review_edit_publish_and_discard(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'), QT_QPA_PLATFORM='offscreen',
               QT_QUICK_BACKEND='software', QML_DISABLE_DISK_CACHE='1', QT_SCALE_FACTOR=scale)
    env.pop('PROTEGE_CONFIG_DIR', None)
    result = subprocess.run([sys.executable, '-c', PROBE, str(REPO), str(tmp_path)],
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'DRAFT_UI_OK' in result.stdout
