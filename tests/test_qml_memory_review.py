"""Review provenance and a full proposal before an explicit, guarded save."""
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
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt, QPointF
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from akira.core.brain.distil import PendingStore, Proposal
from akira.ui.engine import configure_application, build_engine, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
for name in ['SegUIVar.ttf', 'CascadiaMono.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
vault = Path(sys.argv[2]) / 'Vault'; (vault / '.obsidian').mkdir(parents=True)
ctx.memory.setVault(str(vault))
ctx.permissions.policy.grant('vault.read', (str(vault),))
assert not ctx.projects.create('Ocean expedition', '')
project = ctx.projects.currentId
literal = '<img src="file://outside.invalid/probe"> Keep this as plain text.'
body = '# Field notes\n\n' + literal + '\n\n' + ('A long paragraph of observations that should wrap inside the review, even at a compact window size. ' * 8)
pending = PendingStore()
pending.save(Proposal('a' * 16, 'Ocean field notes', 'Memory/Ocean.md', body, False,
    sources=[{'title': 'Expedition planning', 'project': project}, {'title': 'Tidal observations', 'project': project}], created=time.time()))
pending.save(Proposal('b' * 16, 'Garden notes', 'Memory/Garden.md', '# Seeds\nPlant in spring.', False,
    sources=[{'title': 'Spring planting'}], created=time.time()))
ctx.memory.on_proposed()
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.setProperty('currentNav', 'memory'); win.requestActivate(); QTest.qWait(80)
view = win.findChild(QObject, 'memoryView')
def invoke(obj, name, *args):
    assert QMetaObject.invokeMethod(obj, name, Qt.DirectConnection, *[Q_ARG('QVariant', a) for a in args])
    QTest.qWait(60)
def walk(item):
    yield item
    for child in item.childItems(): yield from walk(child)
def find(name):
    return next(o for o in walk(win.contentItem()) if o.objectName() == name)
def press(item):
    invoke(item, 'forceActiveFocus'); QTest.keyClick(win, Qt.Key_Space); QTest.qWait(80)
def capture(label):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        folder = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ.get('QT_SCALE_FACTOR', '1')
        folder.mkdir(parents=True, exist_ok=True); QTest.qWait(90)
        assert win.grabWindow().save(str(folder / (label + '.png')))
assert not win.findChild(QObject, 'memorySetup').property('visible')
assert not find('memoryAccept_' + 'a' * 16).property('visible')
search = win.findChild(QObject, 'memorySearch')
search.setProperty('text', 'tidal'); QTest.qWait(50)
assert len(view.property('filtered').toVariant()) == 1
assert not (vault / 'Memory/Ocean.md').exists()
press(find('memoryReview_' + 'a' * 16))
preview = find('memoryPreview_' + 'a' * 16)
assert preview.property('visible') and literal in preview.property('text')
assert QQmlExpression(engine.rootContext(), preview, 'textFormat === 0 && readOnly && selectByMouse').evaluate()[0]
assert preview.width() > 350 and preview.implicitHeight() > 200
for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    for width, height in [(900, 600), (1440, 900)]:
        win.setWidth(width); win.setHeight(height)
        win.findChild(QObject, 'memoryScroll').property('contentItem').setProperty('contentY', 0)
        capture(mode + '-review-' + str(width))
# A save without writing permission is refused and leaves the proposal intact.
press(find('memoryAccept_' + 'a' * 16))
assert view.property('needs') == 'write' and ctx.memory.pendingCount == 2
assert not (vault / 'Memory/Ocean.md').exists()
ctx.permissions.policy.grant('vault.write', (str(vault / 'Memory'),))
ctx.permissions.grantsChanged.emit()
press(find('memoryAccept_' + 'a' * 16))
assert (vault / 'Memory/Ocean.md').exists() and ctx.memory.pendingCount == 1
assert not view.property('reviewing')
search.setProperty('text', ''); QTest.qWait(50)
press(find('memoryReview_' + 'b' * 16))
press(find('memoryReject_' + 'b' * 16))
assert ctx.memory.pendingCount == 0 and not (vault / 'Memory/Garden.md').exists()
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('MEMORY_REVIEW_OK')
'''


@pytest.mark.parametrize("scale", ["1", "1.5"])
def test_memory_review_and_scoped_save(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1", QT_SCALE_FACTOR=scale)
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO), str(tmp_path)],
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MEMORY_REVIEW_OK" in result.stdout
