"""The complete Research flow through real QML and a scripted local agent team."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import json, os, sys, time, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, str(Path(sys.argv[1]) / 'tests'))
from test_investigations import Router
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt, QPointF
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from akira.ui.engine import configure_application, build_engine, load
from akira.ui.shell import build_context
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
win.setProperty('currentNav', 'research')
research = win.findChild(QObject, 'researchView')
view = win.findChild(QObject, 'researchInvestigations')
composer = win.findChild(QObject, 'workspaceComposer')
source_sheet = win.findChild(QObject, 'researchSourceSheet')
task = win.findChild(QObject, 'investigationTask')
scroller = win.findChild(QObject, 'investigationScroll').property('contentItem')

def settle_until(done):
    deadline = time.monotonic() + 8
    while not done() and time.monotonic() < deadline:
        QTest.qWait(10); time.sleep(.005)
    assert done()

def invoke(obj, name, *args):
    assert QMetaObject.invokeMethod(obj, name, Qt.DirectConnection, *[Q_ARG('QVariant', a) for a in args])
    QTest.qWait(25)

def press(item):
    assert item and item.property('enabled')
    invoke(item, 'forceActiveFocus')
    QTest.keyClick(win, Qt.Key_Space); QTest.qWait(30)

def walk(item):
    yield item
    for child in item.childItems(): yield from walk(child)

def find(name):
    return next(o for o in walk(win.contentItem()) if o.objectName() == name)

def capture(name):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        target = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ.get('QT_SCALE_FACTOR', '1')
        target.mkdir(parents=True, exist_ok=True)
        _settle(win, 180)
        assert win.grabWindow().save(str(target / (name + '.png')))

folder = Path(sys.argv[2]) / 'Expedition'; folder.mkdir()
paper = folder / 'Deep sea observations.txt'
literal = '<img src="https://outside.invalid/pixel"> This must remain plain text.'
paper.write_text(literal + '\n' + '\n'.join('Survey %d: light levels varied with depth. Methods need comparison.' % i for i in range(250)), encoding='utf-8')
assert ctx.projects.create('Ocean research', str(folder)) == ''
project_id = ctx.projects.currentId
ctx.permissions.policy.grant('files.read', (str(folder),))
ctx.permissions.grantsChanged.emit()
call = '<tool_call>' + json.dumps({'name': 'read_file', 'arguments': {'path': str(paper)}}) + '</tool_call>'
answer = '## What the evidence supports\n\nLight levels change with depth, but this record alone does not establish a migration pattern.\n\n### Next steps\n\n- Compare sampling times and methods.\n- Look for independent observations.\n- Keep seasonal differences separate from measurement effects.'
gate = threading.Event()
ctx.agents._router = Router([call, 'Found a local survey.', 'Distinguish sampling from behavior.', 'A single survey is not enough.', answer], gate=gate)
composer.setProperty('text', 'What does the field survey tell us about deep sea migrations?')
press(win.findChild(QObject, 'prepareResearchTeam'))
assert research.property('investigating') and not composer.property('visible')
assert task.property('text') == composer.property('text')
assert not ctx.agents.busy
task.setProperty('text', 'x' * 4001)
assert not win.findChild(QObject, 'investigationStart').property('enabled')
task.setProperty('text', 'What does the field survey tell us about deep sea migrations?')
press(win.findChild(QObject, 'investigationStart'))
assert ctx.agents.busy
ident = ctx.agents.currentRun['id']
assert view.property('selectedId') == ident
capture('research-running-compact')
win.setProperty('currentNav', 'code'); QTest.qWait(30)
gate.set(); settle_until(lambda: not ctx.agents.busy)
assert ctx.agents.record(ident)['status'] == 'complete'
win.setProperty('currentNav', 'research'); QTest.qWait(40)
assert view.property('selectedId') == ident
assert win.findChild(QObject, 'investigationAnswer').property('content') == answer
for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    for size in [(900, 600), (1440, 900)]:
        win.setWidth(size[0]); win.setHeight(size[1]); scroller.setProperty('contentY', 0)
        capture(mode + '-research-result-' + str(size[0]))
    source = find('investigationSource0')
    scroller.setProperty('contentY', max(0, source.mapToScene(QPointF(0, 0)).y() - 220))
    capture(mode + '-research-material')
    press(source)
    assert source_sheet.property('opened')
    body = win.findChild(QObject, 'researchSourceBody')
    assert literal in body.property('text')
    expression = QQmlExpression(engine.rootContext(), body, 'textFormat === 0')
    assert expression.evaluate()[0] and not expression.hasError()
    assert body.width() > 400 and body.height() > 100
    capture(mode + '-research-source')
    QTest.keyClick(win, Qt.Key_Escape); QTest.qWait(30)
    assert not source_sheet.property('opened') and not ctx.agents.sourcePreview

# No result is silently attached to another project; the per-project draft returns.
invoke(view, 'prepare', 'Unsent second inquiry')
assert ctx.projects.openProject('') == ''
QTest.qWait(40)
assert not view.property('hasRun') and not task.property('text')
assert not view.property('saved').toVariant()
task.setProperty('text', 'Personal question')
assert ctx.projects.openProject(project_id) == ''
QTest.qWait(40)
assert task.property('text') == 'Unsent second inquiry'
invoke(view, 'choose', ident)
press(find('investigationSource0'))
assert source_sheet.property('opened') and 'no longer in memory' in source_sheet.property('notice')
QTest.keyClick(win, Qt.Key_Escape); QTest.qWait(30)
view.setProperty('confirmingDelete', True)
press(win.findChild(QObject, 'investigationDelete'))
settle_until(lambda: not ctx.agents.archiveBusy)
assert not ctx.agents.record(ident) and not view.property('hasRun')

# Code and Agents can recover the same archived result without re-running it.
output = folder / 'Expedition report.md'
write = '<tool_call>' + json.dumps({'name': 'write_file', 'arguments': {'path': str(output), 'content': 'Written report.\n' + literal}}) + '</tool_call>'
ctx.permissions.policy.grant('files.write', (str(folder),))
ctx.agents._confirm = lambda summary: True  # Approves only this isolated fixture write.
ctx.agents._router = Router(['Plan', write, 'Implementation', 'Review of the local project.'])
ctx.agents.runTeam('software', 'Build a local expedition notebook.', str(folder))
settle_until(lambda: not ctx.agents.busy)
software_id = ctx.agents.currentRun['id']
win.setProperty('currentNav', 'code'); QTest.qWait(30)
history = win.findChild(QObject, 'runHistorySheet')
press(win.findChild(QObject, 'codeHistoryButton'))
assert history.property('opened') and history.property('selectedId') == software_id
assert ctx.agents.currentRun['artifacts'][0]['path'] == str(output)
assert win.findChild(QObject, 'taskHistoryAnswer').property('content') == 'Review of the local project.'
for mode in ['dark', 'light']:
    ctx.theme.mode = mode; win.setWidth(900); win.setHeight(600)
    capture(mode + '-software-history-compact')
# Reading the output has its own grant, even after a successful write.
ctx.permissions.revoke('files.read')
press(find('runArtifact0'))
artifact = win.findChild(QObject, 'artifactSheet')
assert artifact.property('opened') and not ctx.documents.busy
press(win.findChild(QObject, 'artifactPreview'))
settle_until(lambda: not ctx.documents.busy)
assert ctx.documents.error and not ctx.documents.preview
assert ctx.permissions.grant('files.read', [str(folder)]) == ''
press(win.findChild(QObject, 'artifactPreview'))
settle_until(lambda: not ctx.documents.busy)
text = win.findChild(QObject, 'artifactPreviewText')
assert literal in text.property('text')
expression = QQmlExpression(engine.rootContext(), text, 'textFormat === 0')
assert expression.evaluate()[0]
capture('output-preview-compact')
QTest.keyClick(win, Qt.Key_Escape); QTest.qWait(30)
assert not artifact.property('opened') and not ctx.documents.preview
assert history.property('opened')
QTest.keyClick(win, Qt.Key_Escape); QTest.qWait(30)
win.setProperty('currentNav', 'agents'); QTest.qWait(30)
press(win.findChild(QObject, 'agentHistoryButton'))
assert history.property('opened') and history.property('teamFilter') == ''
assert history.property('selectedId') == software_id
history.setProperty('confirmingDelete', True)
press(win.findChild(QObject, 'taskHistoryDelete'))
settle_until(lambda: not ctx.agents.archiveBusy)
assert not ctx.agents.record(software_id)
QTest.keyClick(win, Qt.Key_Escape); QTest.qWait(30)
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close()
print('INVESTIGATIONS_OK')
'''


@pytest.mark.parametrize("scale", ["1", "1.5"])
def test_research_investigation_lifecycle(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'), QT_QPA_PLATFORM='offscreen',
               QT_QUICK_BACKEND='software', QML_DISABLE_DISK_CACHE='1', QT_SCALE_FACTOR=scale)
    env.pop('PROTEGE_CONFIG_DIR', None)
    run = subprocess.run([sys.executable, '-c', PROBE, str(REPO), str(tmp_path)],
                         env=env, capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'INVESTIGATIONS_OK' in run.stdout
