"""Focus boundaries, nested approvals and model-bound keyboard controls."""
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent
PROBE = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from akira.ui.engine import configure_application, build_engine, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
ctx = build_context(persist=False); ctx.theme.reduceMotion = True; ctx.theme.mode = 'dark'
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []
engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.requestActivate(); QTest.qWait(40)

def walk(item):
    yield item
    for child in item.childItems(): yield from walk(child)

def inside(item, ancestor):
    while item:
        if item == ancestor: return True
        item = item.parentItem()
    return False

trigger = next(i for i in walk(win.contentItem()) if i.property('label') == 'Settings & connections')
QMetaObject.invokeMethod(trigger, 'forceActiveFocus', Qt.DirectConnection)
QTest.keyClick(win, Qt.Key_Space); QTest.qWait(30)
sheet = win.findChild(QObject, 'settingsSheet')
assert sheet.property('opened') and inside(win.activeFocusItem(), sheet)
seen = set()
for modifiers in [Qt.NoModifier, Qt.ShiftModifier]:
    for _ in range(45):
        QTest.keyClick(win, Qt.Key_Tab, modifiers)
        assert inside(win.activeFocusItem(), sheet), 'Tab escaped the open sheet'
        seen.add(id(win.activeFocusItem()))
assert len(seen) >= 5, 'Focus did not move among form controls'

toggle = win.findChild(QObject, 'reduceMotionToggle')
QMetaObject.invokeMethod(toggle, 'forceActiveFocus', Qt.DirectConnection)
QTest.keyClick(win, Qt.Key_Space)
assert not ctx.theme.reduceMotion and not toggle.property('checked')
ctx.theme.reduceMotion = True
assert toggle.property('checked'), 'Keyboard activation broke the model binding'

segment = next(o for o in sheet.findChildren(QObject) if o.metaObject().className().startswith('Segmented_'))
choices = segment.property('options').toVariant()
selected = segment.property('_index')
control = next(i for i in walk(segment) if i.property('index') == selected)
QMetaObject.invokeMethod(control, 'forceActiveFocus', Qt.DirectConnection)
QTest.keyClick(win, Qt.Key_Right)
assert segment.property('current') == choices[(selected + 1) % len(choices)]['id']
QTest.keyClick(win, Qt.Key_Home)
assert segment.property('current') == choices[0]['id']
QTest.keyClick(win, Qt.Key_End)
assert segment.property('current') == choices[-1]['id']

before = win.activeFocusItem()
ctx.confirm.requested.emit('focus-test', 'A synthetic approval. No action will run.')
QTest.qWait(30)
approval = win.findChild(QObject, 'confirmDialog')
assert inside(win.activeFocusItem(), approval)
QTest.keyClick(win, Qt.Key_Tab)
assert inside(win.activeFocusItem(), approval), 'Sheet shortcut stole focus from approval'
ctx.confirm.withdrawn.emit('focus-test')
QTest.qWait(30)
assert win.activeFocusItem() == before
QTest.keyClick(win, Qt.Key_Tab)
assert inside(win.activeFocusItem(), sheet)
QTest.keyClick(win, Qt.Key_Escape); QTest.qWait(30)
assert not sheet.property('opened') and win.activeFocusItem() == trigger
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('ACCESSIBILITY_OK')
'''


def test_sheet_focus_and_keyboard_controls(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'), QT_QPA_PLATFORM='offscreen',
               QT_QUICK_BACKEND='software', QML_DISABLE_DISK_CACHE='1')
    env.pop('PROTEGE_CONFIG_DIR', None)
    run = subprocess.run([sys.executable, '-c', PROBE, str(REPO)], env=env,
                         capture_output=True, text=True, timeout=65)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'ACCESSIBILITY_OK' in run.stdout
