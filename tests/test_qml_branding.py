"""Brand contrast and keyboard navigation in the actual QML window.

Separate process: other tests own a QCoreApplication or Tk interpreter.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parent.parent
PROBE = r'''
import json, sys, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context

app = QGuiApplication([])
configure_application(app)
ctx = build_context(persist=False)
ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
root = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
root.requestActivate()
QTest.qWait(50)
palette = engine.singletonInstance('Akira', 'Theme')
engine.rootContext().setContextProperty('ReviewPalette', palette)
out = {'palettes': {}, 'logos': []}
for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    app.processEvents()
    out['palettes'][mode] = {k: palette.property(k).name() for k in [
        'canvas', 'surface', 'surfaceHover', 'surfaceActive', 'overlay', 'inset',
        'textPrimary', 'textSecondary', 'textTertiary', 'textOnAccent', 'textOnDanger',
        'accent', 'accentHover', 'accentPressed', 'danger']}
expr = QQmlExpression(engine.rootContext(), root, 'ReviewPalette.contrastText("#379062")')
out['brandInk'] = expr.evaluate()[0]
assert not expr.hasError()
for obj in root.findChildren(QObject):
    if obj.metaObject().className().startswith('BrandMark_QMLTYPE'):
        out['logos'].append(obj.property('ready'))

sidebar = root.findChild(QObject, 'workspaceSidebar')
def visual_items(item):
    yield item
    for child in item.childItems():
        yield from visual_items(child)
research = next(obj for obj in visual_items(sidebar)
                if obj.metaObject().className().startswith('NavRow_QMLTYPE')
                and obj.property('label') == 'Research')
QMetaObject.invokeMethod(research, 'forceActiveFocus', Qt.DirectConnection)
QTest.keyClick(root, Qt.Key_Space)
out['keyboardNav'] = root.property('currentNav')

root.setProperty('currentNav', 'memory')
new_chat = next(obj for obj in sidebar.findChildren(QObject)
                if obj.metaObject().className().startswith('ActionButton_QMLTYPE')
                and obj.property('text') == 'New chat')
QMetaObject.invokeMethod(new_chat, 'forceActiveFocus', Qt.DirectConnection)
QTest.keyClick(root, Qt.Key_Return)
out['newChatNav'] = root.property('currentNav')

hide = next(obj for obj in sidebar.findChildren(QObject)
            if obj.metaObject().className().startswith('IconButton_QMLTYPE')
            and obj.property('label') == 'Hide sidebar')
QMetaObject.invokeMethod(hide, 'forceActiveFocus', Qt.DirectConnection)
QTest.keyClick(root, Qt.Key_Space)
out['sidebarOpen'] = root.property('sidebarOpen')
out['attachments'] = root.findChild(QObject, 'workspaceComposer').property('attachmentsAvailable')
out['newTab'] = root.findChild(QObject, 'workspaceTabs') is not None

# A long outgoing message must be reviewable at the minimum window size.
root.setWidth(900)
root.setHeight(600)
summary = 'From: review@example.test\nTo: person@example.test\nSubject: UI fixture\n\n' + ('A line of the message.\n' * 220)
answers = []
worker = threading.Thread(target=lambda: answers.append(ctx.confirm.ask(summary)))
worker.start()
for _ in range(50):
    QTest.qWait(10)
    if root.findChild(QObject, 'confirmDialog').property('visible'):
        break
QTest.qWait(50)
panel = root.findChild(QObject, 'confirmPanel')
scroll = root.findChild(QObject, 'confirmSummaryScroll')
approve = root.findChild(QObject, 'confirmAllow')
out['summaryIntact'] = root.findChild(QObject, 'confirmSummary').property('text') == summary
out['panelTop'] = panel.mapToScene(QPointF(0, 0)).y()
out['panelBottom'] = out['panelTop'] + panel.height()
out['allowBottom'] = approve.mapToScene(QPointF(0, approve.height())).y()
out['initialDecision'] = root.activeFocusItem().objectName()
out['tabOrder'] = []
for _ in range(3):
    QTest.keyClick(root, Qt.Key_Tab)
    out['tabOrder'].append(root.activeFocusItem().objectName())
QMetaObject.invokeMethod(scroll, 'forceActiveFocus', Qt.DirectConnection)
QTest.keyClick(root, Qt.Key_End)
flick = scroll.property('contentItem')
out['summaryScrollY'] = flick.property('contentY')
out['summaryEndVisible'] = (out['summaryScrollY'] + scroll.property('availableHeight')
                            >= scroll.property('contentHeight') - 1)
QTest.keyClick(root, Qt.Key_Escape)
worker.join(2)
out['answers'] = answers

# Search operates on visible names, responds to live model changes, and clears
# with Escape. It must not turn this local filter into a filesystem/network scan.
root.setProperty('sidebarOpen', True)
expression = QQmlExpression(engine.rootContext(), sidebar, 'contentMatches = null')
expression.evaluate()  # Isolate the component's name-only fallback.
assert not expression.hasError()
sidebar.setProperty('projectModel', [{'id': 'fixture-a', 'name': 'Thesis', 'color': '#379062'},
                                   {'id': 'fixture-b', 'name': 'Garden', 'color': '#379062'}])
sidebar.setProperty('recentModel', [{'id': 'fixture-c', 'title': 'Thesis outline', 'when': 'Today'}])
sidebar.setProperty('searchText', '  THESIS  ')
out['foundProjects'] = sidebar.property('filteredProjects').toVariant()
out['foundChats'] = sidebar.property('filteredRecents').toVariant()
sidebar.setProperty('recentModel', [{'id': 'fixture-d', 'title': 'Shopping list', 'when': 'Today'}])
out['refilteredChats'] = sidebar.property('filteredRecents').toVariant()
sidebar.setProperty('searchText', 'nothing matches')
out['emptySearch'] = root.findChild(QObject, 'sidebarSearchEmpty').property('visible')
search = root.findChild(QObject, 'workspaceSearch')
field = next(obj for obj in search.findChildren(QObject)
             if obj.metaObject().className().startswith('TextField_QMLTYPE'))
QMetaObject.invokeMethod(field, 'forceActiveFocus', Qt.DirectConnection)
QTest.keyClick(root, Qt.Key_Escape)
out['clearedSearch'] = sidebar.property('searchText')
ctx.close()
print(json.dumps(out))
'''


@pytest.fixture(scope='module')
def rendered(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('brand-window')
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software',
           'QML_DISABLE_DISK_CACHE': '1', 'AKIRA_CONFIG_DIR': str(tmp / 'config')}
    env.pop('PROTEGE_CONFIG_DIR', None)
    done = subprocess.run([sys.executable, '-c', PROBE, str(REPO)], cwd=tmp, env=env,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert not any(err in done.stderr for err in ['ReferenceError', 'TypeError', 'Cannot open'])
    return json.loads(done.stdout.strip().splitlines()[-1])


def contrast(a, b):
    def luminance(color):
        values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722)))
    low, high = sorted((luminance(a), luminance(b)))
    return (high + 0.05) / (low + 0.05)


def test_small_copy_and_button_states_have_readable_contrast(rendered):
    for mode, p in rendered['palettes'].items():
        for text in ['textPrimary', 'textSecondary', 'textTertiary']:
            for surface in ['canvas', 'surface', 'surfaceHover', 'surfaceActive', 'overlay', 'inset']:
                assert contrast(p[text], p[surface]) >= 4.5, (mode, text, surface)
        for state in ['accent', 'accentHover', 'accentPressed']:
            assert contrast(p['textOnAccent'], p[state]) >= 4.5, (mode, state)
        assert contrast(p['textOnDanger'], p['danger']) >= 4.5
        assert contrast(p['accent'], p['surface']) >= 4.5
    assert contrast(rendered['brandInk'], '#379062') >= 4.5


def test_approved_mark_loads_in_the_real_window(rendered):
    assert len(rendered['logos']) >= 2
    assert all(rendered['logos'])


def test_shared_controls_work_from_the_keyboard(rendered):
    assert rendered['keyboardNav'] == 'research'
    assert rendered['newChatNav'] == 'chats'
    assert rendered['sidebarOpen'] is False
    assert rendered['attachments'] is False
    assert rendered['newTab'] is False


def test_long_approval_stays_readable_and_keyboard_focus_stays_inside(rendered):
    assert rendered['summaryIntact']
    assert rendered['panelTop'] >= 0
    assert rendered['panelBottom'] <= 600
    assert rendered['allowBottom'] <= 600
    assert rendered['initialDecision'] == 'confirmRefuse'
    assert rendered['tabOrder'] == ['confirmAllow', 'confirmSummaryScroll', 'confirmRefuse']
    assert rendered['summaryScrollY'] > 0 and rendered['summaryEndVisible']
    assert rendered['answers'] == [False]


def test_sidebar_search_filters_names_and_tracks_updates(rendered):
    assert [p['name'] for p in rendered['foundProjects']] == ['Thesis']
    assert [c['title'] for c in rendered['foundChats']] == ['Thesis outline']
    assert rendered['refilteredChats'] == []
    assert rendered['emptySearch']
    assert rendered['clearedSearch'] == ''
