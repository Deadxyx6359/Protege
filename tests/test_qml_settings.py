"""Settings' pages in a list, live model choices, and compact form controls."""
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
from PySide6.QtGui import QGuiApplication, QFont, QFontDatabase
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context
from akira.ui.bridge import settings as settings_module
from akira.core.config import ModelConfig
from tools.preview import _settle
app = QGuiApplication([]); configure_application(app)
for name in ['SegUIVar.ttf', 'CascadiaMono.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
app.setFont(QFont('Segoe UI'))
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
fixture = Path(sys.argv[2]) / 'Aurora-Code-8B-Q4_K_M.gguf'
fixture.write_bytes(b'UI fixture only; never loaded')
settings_module.discover_models = lambda: [fixture]
ctx.config.models = {'chat': ModelConfig(path=str(fixture)),
                     'code': ModelConfig(path=str(fixture.parent / 'Missing-Model-Q5_K_M.gguf'))}
ctx.router.update(ctx.config)
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []
engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.requestActivate(); QTest.qWait(30)
sheet = win.findChild(QObject, 'settingsSheet')
QMetaObject.invokeMethod(sheet, 'open', Qt.DirectConnection)
tabs = win.findChild(QObject, 'settingsSections')
LABELS = {'general': 'General', 'appearance': 'Appearance', 'models': 'Models', 'voice': 'Voice',
          'firmware': 'Firmware', 'permissions': 'Permissions', 'accounts': 'Accounts',
          'search': 'Web search', 'location': 'Location', 'chats': 'Chats'}
PAGES = [('general', 'settingsGeneral', ['setupModels', 'quickSetup', 'keepRunningToggle', 'quitAkira']),
         ('appearance', 'settingsAppearance', ['appearanceModes', 'reduceMotionToggle']),
         ('models', 'settingsModels', ['manageClaude']),
         ('voice', 'voicePane', ['voiceChoice']),
         ('firmware', 'settingsFirmware', ['programmerStatus', 'cubemxStatus', 'allowBoardReading']),
         ('permissions', 'permissionsPane', ['permissionGroups']),
         ('accounts', 'accountsPane', ['accountSections']),
         ('search', 'searchPane', ['searchKey']),
         ('location', 'placePane', ['placeName']),
         ('chats', 'settingsChats', ['keepPinnedToggle', 'olderThanChoice', 'deleteOldChats', 'deleteAllChats'])]
assert [s for s, _, _ in PAGES] == [p.toVariant()['id'] if hasattr(p, 'toVariant') else p['id']
                                    for p in sheet.property('pages').toVariant()]

def walk(item):
    yield item
    for child in item.childItems(): yield from walk(child)

def find(name):
    # Made by a Repeater, an item is a child of its parent item only, so findChild misses it.
    # The voice sheet, closed, holds a pane of its own: the one shown is wanted.
    found = [i for i in walk(win.contentItem()) if i.objectName() == name]
    return next((i for i in found if i.isVisible()), found[0] if found else None)

def capture(name):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        target = Path(os.environ['AKIRA_REVIEW_DIR']); target.mkdir(parents=True, exist_ok=True)
        _settle(win, 120)
        assert win.grabWindow().save(str(target / (name + '.png')))

for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    for width in [900, 1440]:
        win.setWidth(width); win.setHeight(600 if width == 900 else 900)
        for section, page, names in PAGES:
            tabs.selected.emit(section); QTest.qWait(60)
            assert sheet.property('section') == section
            assert win.findChild(QObject, 'settingsPageTitle').property('text') == LABELS[section]
            # Only the page shown is made.
            assert win.findChild(QObject, page).property('visible'), page
            assert all(win.findChild(QObject, other) is None for _, other, _ in PAGES if other != page)
            # One walk of the window a page: one a control took over a minute in all.
            shown = {}
            for item in walk(win.contentItem()):
                if item.isVisible() and item.objectName():
                    shown.setdefault(item.objectName(), item)
            for name in names + ['settingsTab_' + s for s, _, _ in PAGES]:
                control = shown.get(name)
                assert control is not None and control.property('visible'), name
                at = control.mapToScene(QPointF(0, 0))
                assert at.x() >= 0 and at.x() + control.width() <= width, (name, at)
                assert at.y() > 0 and at.y() + control.height() <= win.height(), (name, at)
            capture(mode + '-' + str(width) + '-' + section)

# A page is chosen by mouse from the list, and the arrow keys move along it.
win.setWidth(900); win.setHeight(600); QTest.qWait(60)
def click(name):
    item = find(name)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier,
                     item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()); QTest.qWait(60)
click('settingsTab_firmware')
assert sheet.property('section') == 'firmware' and sheet.property('opened')
QTest.keyClick(win, Qt.Key_Down); QTest.qWait(60)
assert sheet.property('section') == 'permissions'
QTest.keyClick(win, Qt.Key_Up); QTest.keyClick(win, Qt.Key_Up); QTest.qWait(60)
assert sheet.property('section') == 'voice'

# Every permission can be allowed somewhere: a domain in no group could not be.
QMetaObject.invokeMethod(sheet, 'show', Qt.DirectConnection, Q_ARG('QVariant', 'permissions')); QTest.qWait(60)
pane = win.findChild(QObject, 'permissionsPane')
grouped = {d for g in pane.property('groups').toVariant() for d in g['domains']}
missing = {c['domain'] for c in ctx.permissions.catalogue} - grouped
assert not missing, missing
pane.setProperty('group', 'boards'); QTest.qWait(40)
assert find('permissionGroup_boards').property('visible')
assert not find('permissionGroup_files').property('visible')

# Firmware: the boards' permissions are allowed and taken back from their own page.
QMetaObject.invokeMethod(sheet, 'show', Qt.DirectConnection, Q_ARG('QVariant', 'firmware')); QTest.qWait(60)
policy = ctx.permissions.policy
assert not win.findChild(QObject, 'findBoards').property('enabled'), 'looking needs reading allowed'
click('allowBoardReading')
assert policy.granted('device.read') is not None
assert win.findChild(QObject, 'findBoards').property('enabled')
click('allowBoardReading')
assert policy.granted('device.read') is None and policy.granted('device.write') is None

tabs.selected.emit('models'); QTest.qWait(30)
pickers = {i.objectName(): i for i in walk(sheet) if i.objectName().startswith('modelChoice_')}
assert set(pickers) == {'modelChoice_chat', 'modelChoice_code', 'modelChoice_fast', 'modelChoice_deep'}
labels = pickers['modelChoice_chat'].property('options').toVariant()
assert any(o['label'] == 'Aurora Code 8B' and o['value'] == str(fixture) for o in labels)
assert any(o['detail'] == 'Missing' for o in pickers['modelChoice_code'].property('options').toVariant() if 'detail' in o)
ctx.agents._busy = True; ctx.agents.busyChanged.emit(); QTest.qWait(30)
assert all(not item.property('enabled') for item in pickers.values())
ctx.agents._busy = False; ctx.agents.busyChanged.emit(); QTest.qWait(30)
assert all(item.property('enabled') for item in pickers.values())
pickers['modelChoice_code'].picked.emit(str(fixture)); QTest.qWait(30)
assert ctx.config.models['code'].path == str(fixture)
assert sheet.property('availableRoutes') == 2
sheet.setProperty('modelDetails', True); QTest.qWait(30)
assert any(str(fixture) in str(i.property('text') or '') and i.property('visible') for i in walk(sheet))
capture('model-file-details')
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close()
print('SETTINGS_UI_OK')
'''


def test_settings_sections_and_model_choices(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'), QT_QPA_PLATFORM='offscreen',
               QT_QUICK_BACKEND='software', QML_DISABLE_DISK_CACHE='1', QT_SCALE_FACTOR='1.5')
    env.pop('PROTEGE_CONFIG_DIR', None)
    run = subprocess.run([sys.executable, '-c', PROBE, str(REPO), str(tmp_path)], env=env,
                         capture_output=True, text=True, timeout=150)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'SETTINGS_UI_OK' in run.stdout
