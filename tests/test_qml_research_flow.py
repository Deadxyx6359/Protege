"""Retrieved context and an editable team task, without model or network work."""
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent
PROBE = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Qt, QPointF
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from akira.core.conversation import Message
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
agents = win.findChild(QObject, 'agentsView')
composer = win.findChild(QObject, 'workspaceComposer')
sources = research.findChild(QObject, 'contextSources')

def capture(name):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        out = Path(os.environ['AKIRA_REVIEW_DIR']); out.mkdir(parents=True, exist_ok=True)
        _settle(win, 220)
        assert win.grabWindow().save(str(out / (name + '.png')))

def press(item):
    QMetaObject.invokeMethod(item, 'forceActiveFocus', Qt.DirectConnection)
    QTest.keyClick(win, Qt.Key_Space); QTest.qWait(40)

literal = '<img src="file://remote/private"> Long source title kept as text'
for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    ctx.chat.messages.reset([Message('user', 'What does the evidence say?'),
        Message('assistant', 'The field notes point to a seasonal migration. Compare the survey methods before drawing a stronger conclusion.')])
    ctx.chat._set_sources([{'source': 'documents', 'cite': literal}] + [
        {'source': 'notes', 'cite': 'Expedition log %d — observations and limitations' % n} for n in range(14)],
        '15 passages were retrieved from documents and notes.')
    QTest.qWait(40)
    assert sources.property('visible')
    press(sources.findChild(QObject, 'contextSourcesToggle'))
    assert sources.property('expanded')
    capture(mode + '-retrieved-context-compact')
    source_bottom = sources.mapToScene(QPointF(0, sources.height())).y()
    composer_top = composer.mapToScene(QPointF(0, 0)).y()
    assert source_bottom <= composer_top and sources.height() < 220
    texts = [o for o in sources.findChildren(QObject) if o.property('text') == literal]
    # Repeater delegates can be visual children rather than QObject children.
    def walk(item):
        yield item
        for child in item.childItems(): yield from walk(child)
    texts += [o for o in walk(sources) if o.property('text') == literal]
    assert texts
    expression = QQmlExpression(engine.rootContext(), texts[0], 'textFormat === 0')
    assert expression.evaluate()[0] and not expression.hasError()
    scroll = sources.findChild(QObject, 'contextSourcesScroll').property('contentItem')
    assert scroll.property('contentHeight') > scroll.height()
    scroll.setProperty('contentY', scroll.property('contentHeight') - scroll.height())
    assert scroll.property('contentY') > 0
    ctx.chat.newChat(); QTest.qWait(30)
    assert not sources.property('visible')
    capture(mode + '-research-compact')

folder = Path(sys.argv[2]) / 'Expedition'; folder.mkdir()
assert ctx.projects.create('Ocean research', str(folder)) == ''
composer.setProperty('text', 'Compare the evidence for deep sea migrations.')
before = ctx.trace.events.count
press(research.findChild(QObject, 'prepareResearchTeam'))
assert win.property('currentNav') == 'agents'
assert agents.property('chosen') == 'team:research'
assert agents.property('taskDraft') == 'Compare the evidence for deep sea migrations.'
assert agents.property('folder') == str(folder.resolve())
assert not ctx.agents.busy and ctx.trace.events.count == before
assert not ctx.permissions.policy.granted('docs.read')
for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    capture(mode + '-prepared-research-task')
task = win.findChild(QObject, 'agentTask')
assert task.mapToScene(QPointF(0, 0)).y() >= 68
assert win.findChild(QObject, 'agentStart').mapToScene(QPointF(0, 34)).y() <= 600
assert not win.findChild(QObject, 'agentPipeline').property('visible')
agents.setProperty('showTeamDetails', True); QTest.qWait(30)
assert win.findChild(QObject, 'agentPipeline').property('visible')
agents.setProperty('showTeamDetails', False)

win.setProperty('currentNav', 'code')
composer.setProperty('text', 'Build a local expedition notebook.')
capture('code-team-entry')
press(win.findChild(QObject, 'workspacePrimaryAction'))
assert agents.property('chosen') == 'team:software'
assert agents.property('taskDraft') == 'Build a local expedition notebook.'
assert not ctx.agents.busy
task.setProperty('text', 'x' * 4001)
assert not win.findChild(QObject, 'agentStart').property('enabled')
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close()
print('RESEARCH_FLOW_OK')
'''


def test_research_context_and_team_drafts(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'), QT_QPA_PLATFORM='offscreen',
               QT_QUICK_BACKEND='software', QML_DISABLE_DISK_CACHE='1')
    env.pop('PROTEGE_CONFIG_DIR', None)
    run = subprocess.run([sys.executable, '-c', PROBE, str(REPO), str(tmp_path)],
                         env=env, capture_output=True, text=True, timeout=75)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'RESEARCH_FLOW_OK' in run.stdout
