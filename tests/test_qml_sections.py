"""Compact navigation and every agent's live status, without inference or network."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt, QPointF
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtTest import QTest
from akira.ui.engine import configure_application, build_engine, load
from akira.ui.shell import build_context
from akira.ui.run_archive import clean_record
app = QGuiApplication([]); configure_application(app)
QFontDatabase.addApplicationFont('C:/Windows/Fonts/SegUIVar.ttf')
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.requestActivate(); QTest.qWait(60)
def walk(item):
    yield item
    for child in item.childItems(): yield from walk(child)
def find(name):
    return next(i for i in walk(win.contentItem()) if i.objectName() == name)
def invoke(obj, method, *args):
    assert QMetaObject.invokeMethod(obj, method, Qt.DirectConnection, *[Q_ARG('QVariant', a) for a in args])
    QTest.qWait(40)
def press(item):
    invoke(item, 'forceActiveFocus'); QTest.keyClick(win, Qt.Key_Space); QTest.qWait(40)
def capture(name):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        dest = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ['QT_SCALE_FACTOR']
        dest.mkdir(parents=True, exist_ok=True)
        assert win.grabWindow().save(str(dest / (name + '.png')))
nav = [o.objectName() for o in walk(win.contentItem()) if o.objectName().startswith('nav_')]
assert nav == ['nav_chats', 'nav_library', 'nav_tools'], nav
chat_id = ctx.chat.conversationId
composer = find('workspaceComposer'); composer.setProperty('text', 'My unsent question')
press(find('nav_library'))
assert win.property('currentNav') == 'documents'
tabs = find('sectionTabs')
tabs.selected.emit('memory'); QTest.qWait(40)
assert find('memoryView').isVisible() and not find('documentsView').isVisible()
press(find('nav_tools')); assert win.property('currentNav') == 'agents'
for page, view in [('code', 'codeView'), ('research', 'researchView'), ('watching', 'watchView'), ('schedule', 'scheduleView'), ('agents', 'agentsView')]:
    tabs.selected.emit(page); QTest.qWait(40)
    assert find(view).isVisible() and win.property('currentSection') == 'tools'
    assert not composer.isVisible()
    assert find(view).mapToScene(QPointF(0, 0)).y() >= tabs.mapToScene(QPointF(0, tabs.height())).y()
    assert ctx.chat.conversationId == chat_id and composer.property('text') == 'My unsent question'
press(find('nav_library')); assert win.property('currentNav') == 'memory'
press(find('nav_tools')); assert win.property('currentNav') == 'agents'
# Every registered agent is listed, even agents outside the selected team.
for role in ctx.agents.roles:
    assert find('agentActivity_' + role['name']).property('text') == 'Idle'
record = clean_record({'id': 'a' * 32, 'kind': 'team', 'name': 'research',
    'status': 'running', 'task': 'Compare field observations',
    'members': ['gatherer', 'analyst', 'critic', 'writer'],
    'states': {'gatherer': 'Using read_file', 'analyst': 'Waiting', 'critic': 'Waiting', 'writer': 'Waiting'}})
ctx.agents._current_id = record['id']; ctx.agents._busy = True
ctx.agents._on_progress(record); ctx.agents.busyChanged.emit(); QTest.qWait(60)
assert find('agentActivity_gatherer').property('text') == 'Using read file'
assert find('agentRow_gatherer').property('working')
assert find('agentActivity_implementer').property('text') == 'Idle'
for appearance in ['dark', 'light']:
    ctx.theme.mode = appearance
    for width, height in [(900, 600), (1440, 900)]:
        win.setWidth(width); win.setHeight(height); QTest.qWait(70)
        for o in walk(find('agentPipeline')):
            if o.objectName().startswith('agentRow_'):
                at = o.mapToScene(QPointF(0, 0))
                assert at.x() >= 0 and at.x() + o.width() <= win.width()
        capture(appearance + '-agents-' + str(width))
record['states'].update(gatherer='Done', analyst='Thinking')
ctx.agents._on_progress(record.copy()); QTest.qWait(40)
assert find('agentActivity_gatherer').property('text') == 'Done'
assert find('agentActivity_analyst').property('text') == 'Thinking'
record['status'] = 'stopped'; record['states']['analyst'] = 'Stopped'
ctx.agents._busy = False; ctx.agents._on_progress(record.copy()); ctx.agents.busyChanged.emit(); QTest.qWait(40)
assert find('agentActivity_analyst').property('text') == 'Stopped'
assert find('agentActivity_writer').property('text') == 'Not run'
assert not find('agentRow_analyst').property('working')
# A new run cannot inherit the prior team's activity.
record = clean_record({'id': 'b' * 32, 'kind': 'agent', 'name': 'architect',
    'status': 'incomplete', 'members': ['architect'], 'states': {'architect': 'Failed'}})
ctx.agents._current_id = record['id']; ctx.agents._on_progress(record); QTest.qWait(40)
assert find('agentActivity_analyst').property('text') == 'Idle'
assert find('agentActivity_architect').property('text') == 'Failed'
# Scheduled roles publish through the shared trace, outside Agents.currentRun.
from akira.core.agents.trace import Kind
ctx.trace.trace.emit(Kind.STARTED, 'secretary')
ctx.trace.trace.emit(Kind.TOOL_CALL, 'secretary', tool='read_file')
QTest.qWait(40)
assert find('agentActivity_secretary').property('text') == 'Using read file'
assert find('agentRow_secretary').property('working')
ctx.trace.clear(); QTest.qWait(30)
assert find('agentRow_secretary').property('working')
ctx.trace.trace.emit(Kind.ANSWER, 'secretary', text='Done')
QTest.qWait(30)
assert find('agentActivity_secretary').property('text') == 'Done'
assert not find('agentRow_secretary').property('working')

press(find('nav_chats')); assert ctx.chat.conversationId == chat_id
assert composer.property('text') == 'My unsent question'
assert not tabs.isVisible()
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('SECTIONS_UI_OK')
'''


@pytest.mark.parametrize('scale', ['1', '1.5'])
def test_sections_and_agent_activity(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'), QT_QPA_PLATFORM='offscreen',
               QT_QUICK_BACKEND='software', QML_DISABLE_DISK_CACHE='1', QT_SCALE_FACTOR=scale)
    env.pop('PROTEGE_CONFIG_DIR', None)
    result = subprocess.run([sys.executable, '-c', PROBE, str(REPO)], env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'SECTIONS_UI_OK' in result.stdout
