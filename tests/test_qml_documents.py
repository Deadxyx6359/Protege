"""Exercise the real Documents workspace in an isolated Qt process."""
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent
PROBE = r'''
import os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Qt
from PySide6.QtGui import QGuiApplication, QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlExpression
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context
from tools.preview import _settle

app = QGuiApplication([])
configure_application(app)
for font in ['SegUIVar.ttf', 'CascadiaMono.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts') / font))
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
app.setFont(QFont('Segoe UI'))
ctx = build_context(persist=False)
ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
errors = []
engine.warnings.connect(lambda warnings: errors.extend(str(w) for w in warnings))
window = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
window.setWidth(1280); window.setHeight(800)
window.setProperty('currentNav', 'documents')
window.requestActivate()
view = window.findChild(QObject, 'documentsView')
assert view.property('visible') and window.property('fullPage')
assert not window.findChild(QObject, 'workspaceComposer').property('visible')
folder = Path(sys.argv[2]) / 'Expedition'
folder.mkdir()
(folder / 'Archive').mkdir()
(folder / 'Field notes.md').write_text('# Into the abyss\n\nLanternfish light the way.\n\n'
    '<img src="file://elsewhere">\n\n' + '\n'.join('Observation %d: glass sponges on the reef.' % i for i in range(80)), encoding='utf-8')
(folder / 'Schedule.txt').write_text('Depart at dawn.\nReturn before nightfall.', encoding='utf-8')

def wait():
    end = time.monotonic() + 8
    while ctx.documents.busy and time.monotonic() < end:
        QTest.qWait(10)
    assert not ctx.documents.busy
    QTest.qWait(50)

def capture(name):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        target = Path(os.environ['AKIRA_REVIEW_DIR']); target.mkdir(parents=True, exist_ok=True)
        _settle(window, 250)
        assert window.grabWindow().save(str(target / (name + '.png')))

def items(item):
    yield item
    for child in item.childItems():
        yield from items(child)

for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    ctx.documents.invalidate()
    view.setProperty('searchMode', 'names')
    capture(mode + '-documents-empty')
    assert ctx.permissions.grant('files.read', [str(folder)]) == ''
    assert ctx.permissions.grant('docs.read', [str(folder)]) == ''
    ctx.documents.openFolder(str(folder)); wait()
    assert not ctx.documents.error and len(ctx.documents.entries) == 3
    capture(mode + '-documents-folder')
    search = window.findChild(QObject, 'documentSearch')
    search.setProperty('text', 'FIELD')
    QTest.qWait(30)
    assert window.findChild(QObject, 'documentList').property('count') == 1
    search.setProperty('text', '')
    ctx.documents.previewFile(str(folder / 'Field notes.md')); wait()
    preview = window.findChild(QObject, 'documentPreviewText')
    assert '<img src="file://elsewhere">' in preview.property('text')
    expression = QQmlExpression(engine.rootContext(), preview, 'textFormat === 0')  # PlainText
    assert expression.evaluate()[0] and not expression.hasError()
    assert preview.property('readOnly') and preview.property('selectByMouse')
    capture(mode + '-documents-preview')
    window.setWidth(900); window.setHeight(600)
    QTest.qWait(50)
    assert not view.property('wide')
    back = next(i for i in items(view) if i.property('text') == 'Back to files' and i.property('visible'))
    capture(mode + '-documents-compact')
    QMetaObject.invokeMethod(back, 'forceActiveFocus', Qt.DirectConnection)
    QTest.keyClick(window, Qt.Key_Return)
    assert not ctx.documents.selected
    listing = window.findChild(QObject, 'documentList')
    listing.setProperty('currentIndex', 1)
    QMetaObject.invokeMethod(listing, 'forceActiveFocus', Qt.DirectConnection)
    QTest.keyClick(window, Qt.Key_Return); wait()
    assert ctx.documents.selected['name'] == 'Field notes.md'
    window.setWidth(1280); window.setHeight(800)
    view.setProperty('searchMode', 'contents')
    search.setProperty('text', 'lanternfish')
    QMetaObject.invokeMethod(view, 'runSearch', Qt.DirectConnection); wait()
    assert ctx.documents.passages
    capture(mode + '-documents-search')
    # Real shell connections clear the screen on project changes and revocation.
    assert ctx.projects.create('Another project ' + mode, str(folder)) == ''
    assert not ctx.documents.preview and not ctx.documents.folder
    ctx.documents.openFolder(str(folder)); wait()
    ctx.permissions.revoke('files.read')
    assert not ctx.documents.entries and not ctx.documents.folder
    ctx.documents.openFolder(str(folder)); wait()
    assert 'Not permitted' in ctx.documents.error
    capture(mode + '-documents-refusal')

assert not errors, '\n'.join(errors)
ctx.close(); window.close()
print('DOCUMENTS_UI_OK')
'''


def test_documents_workspace(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
               QML_DISABLE_DISK_CACHE='1', AKIRA_CONFIG_DIR=str(tmp_path / 'config'))
    env.pop('PROTEGE_CONFIG_DIR', None)
    run = subprocess.run([sys.executable, '-c', PROBE, str(REPO), str(tmp_path)],
                         capture_output=True, text=True, env=env, timeout=70)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'DOCUMENTS_UI_OK' in run.stdout
