"""The real header, project picker and collapsed workspace navigation."""
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent
PROBE = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Qt, QPointF, Q_ARG
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtTest import QTest
from akira.ui.engine import configure_application, build_engine, load
from akira.ui.shell import build_context
from akira.core.conversation import Conversation
from tools.preview import _settle
app = QGuiApplication([])
configure_application(app)
for name in ['SegUIVar.ttf', 'CascadiaMono.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
app.setFont(QFont('Segoe UI'))
ctx = build_context(persist=False)
ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []
engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.requestActivate()
QTest.qWait(50)
assert win.findChild(QObject, 'workspaceTabs') is None
header = win.findChild(QObject, 'workspaceHeader')
picker = win.findChild(QObject, 'activeProjectPicker')
sheet = win.findChild(QObject, 'projectSheet')
manage = win.findChild(QObject, 'manageActiveProject')

def capture(name):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        target = Path(os.environ['AKIRA_REVIEW_DIR']); target.mkdir(parents=True, exist_ok=True)
        _settle(win, 200)
        assert win.grabWindow().save(str(target / (name + '.png')))

def keyboard(item, key):
    QMetaObject.invokeMethod(item, 'forceActiveFocus', Qt.DirectConnection)
    QTest.keyClick(win, key)
    QTest.qWait(30)

def combo(item):
    return next(o for o in item.findChildren(QObject) if o.metaObject().className().startswith('ComboBox_'))

assert not manage.property('visible')
assert ctx.projects.create('A long expedition project name for the compact layout', '') == ''
pid = ctx.projects.currentId
assert ctx.projects.openProject('') == ''
QTest.qWait(30)
box = combo(picker)
keyboard(box, Qt.Key_Space)
QTest.keyClick(win, Qt.Key_Home)
QTest.keyClick(win, Qt.Key_Down)
QTest.keyClick(win, Qt.Key_Return)
QTest.qWait(40)
assert ctx.projects.currentId == pid
assert manage.property('visible')
keyboard(manage, Qt.Key_Return)
assert sheet.property('opened') and sheet.property('projectId') == pid
QTest.keyClick(win, Qt.Key_Escape)
assert not sheet.property('opened')

for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    for width in [900, 1440]:
        win.setWidth(width); win.setHeight(600 if width == 900 else 900)
        for sidebar in [True, False]:
            win.setProperty('sidebarOpen', sidebar)
            win.setProperty('currentNav', 'research')
            QTest.qWait(40)
            assert header.property('currentView') == 'research'
            assert win.findChild(QObject, 'collapsedWorkspacePicker').property('visible') is (not sidebar)
            for name in ['activeProjectPicker', 'manageActiveProject', 'openPermissions']:
                control = win.findChild(QObject, name)
                at = control.mapToScene(QPointF(0, 0))
                assert at.x() >= 0 and at.x() + control.width() <= width, (name, at.x(), control.width())
                assert at.y() >= 0 and at.y() + control.height() <= header.height()
            capture(f'{mode}-{width}-sidebar-{sidebar}')

mode_picker = win.findChild(QObject, 'collapsedWorkspacePicker')
keyboard(combo(mode_picker), Qt.Key_Space)
QTest.keyClick(win, Qt.Key_Home)
QTest.keyClick(win, Qt.Key_Down)
QTest.keyClick(win, Qt.Key_Down)
QTest.keyClick(win, Qt.Key_Down)
QTest.keyClick(win, Qt.Key_Return)
QTest.qWait(40)
assert win.property('currentNav') == 'documents'
assert win.findChild(QObject, 'documentsView').property('visible')

win.setProperty('currentNav', 'schedule')
assert header.property('globalContext')
assert win.findChild(QObject, 'workspaceScope').property('text') == 'Global permissions'
ctx.agents._busy = True; ctx.agents.busyChanged.emit()
assert not picker.property('enabled')
QMetaObject.invokeMethod(win, 'selectProject', Qt.DirectConnection, Q_ARG('QVariant', ''))
assert ctx.projects.currentId == pid
ctx.agents._busy = False; ctx.agents.busyChanged.emit()
assert picker.property('enabled')

# A project switch starts a fresh chat and keeps an unsent draft per project.
composer = win.findChild(QObject, 'workspaceComposer')
composer.setProperty('text', 'Draft for the expedition')
old = ctx.chat.conversationId
QMetaObject.invokeMethod(win, 'selectProject', Qt.DirectConnection, Q_ARG('QVariant', ''))
assert ctx.projects.currentId == '' and ctx.chat.conversationId != old
assert composer.property('text') == ''
composer.setProperty('text', 'Personal draft')
QMetaObject.invokeMethod(win, 'selectProject', Qt.DirectConnection, Q_ARG('QVariant', pid))
assert composer.property('text') == 'Draft for the expedition'
saved = Conversation(project=pid)
saved.add('user', 'A saved expedition question')
ctx.chat._store.save(saved)
QMetaObject.invokeMethod(win, 'selectProject', Qt.DirectConnection, Q_ARG('QVariant', ''))
assert composer.property('text') == 'Personal draft'
QMetaObject.invokeMethod(win, 'openRecent', Qt.DirectConnection, Q_ARG('QVariant', saved.id))
assert ctx.projects.currentId == pid and ctx.chat.conversationId == saved.id
assert ctx.chat.messages.count == 1 and composer.property('text') == ''

picker.picked.emit('__create_project__')
assert sheet.property('opened') and sheet.property('projectId') == ''
QMetaObject.invokeMethod(sheet, 'close', Qt.DirectConnection)
assert not warnings, '\n'.join(warnings)

# Counts update the existing rows without destroying keyboard focus. Counts
# describe pending notes / saved notices / critical findings, not unread items.
from akira.core.brain.distil import Proposal
from akira.core.review import Review, Finding
def walk(item):
    yield item
    for child in item.childItems(): yield from walk(child)
def named(name):
    return next(i for i in walk(win.contentItem()) if i.objectName() == name)
win.setProperty('sidebarOpen', True)
memory_row = named('nav_memory')
QMetaObject.invokeMethod(memory_row, 'forceActiveFocus', Qt.DirectConnection)
ctx.memory._pending.save(Proposal('abcdef1234567890', 'Lanterns', 'lanterns.md', 'Fixture note', False))
ctx.memory.pendingChanged.emit(); QTest.qWait(30)
assert memory_row.property('detail') == '1'
assert win.activeFocusItem() == memory_row
ctx.monitor.notify('Fixture notice', 'A local test notice.'); QTest.qWait(30)
assert named('nav_watching').property('detail') == '1'
assert named('nav_watching').property('detailDescription') == '1 saved notice'
ctx.schedule.on_review(Review(1, 30, [Finding('critical', 'fixture', 'Fixture finding')]))
QTest.qWait(30)
assert named('nav_schedule').property('detail') == '1'
banner = win.findChild(QObject, 'noticeBanner')
while banner.property('count'):
    QMetaObject.invokeMethod(banner, 'dismiss', Qt.DirectConnection, Q_ARG('QVariant', 0))
QMetaObject.invokeMethod(banner, 'show', Qt.DirectConnection,
    Q_ARG('QVariant', 'Project unavailable'), Q_ARG('QVariant', 'Fixture error'),
    Q_ARG('QVariant', False), Q_ARG('QVariant', ''))
QTest.qWait(30)
assert not any(i.objectName() == 'noticeDestination' and i.property('visible') for i in walk(banner))
ctx.monitor.clearNotices()
ctx.memory._pending.remove('abcdef1234567890'); ctx.memory.pendingChanged.emit()
ctx.schedule.on_review(Review(2, 30, [])); QTest.qWait(30)
assert not memory_row.property('detail') and not named('nav_watching').property('detail')
assert not named('nav_schedule').property('detail')
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close()
print('NAVIGATION_OK')
'''


def test_navigation_and_project_context(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'), QT_QPA_PLATFORM='offscreen',
               QT_QUICK_BACKEND='software', QML_DISABLE_DISK_CACHE='1')
    env.pop('PROTEGE_CONFIG_DIR', None)
    run = subprocess.run([sys.executable, '-c', PROBE, str(REPO)], env=env,
                         capture_output=True, text=True, timeout=75)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'NAVIGATION_OK' in run.stdout
