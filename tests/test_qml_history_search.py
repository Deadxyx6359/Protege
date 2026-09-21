"""Search saved bodies through the real window, retaining project/team scope."""
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
from akira.core.conversation import Conversation
from akira.ui.run_archive import clean_record
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
for name in ['SegUIVar.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
assert not ctx.projects.create('Expedition', '')
project = ctx.projects.currentId
chat = Conversation(title='A forgotten question', project=project)
chat.add('user', 'Describe the light below the sea.')
chat.add('assistant', 'Bioluminescence comes from chemical reactions. <b>Literal markup</b>')
ctx.chat._store.save(chat)
for i in range(43):
    filler = Conversation(title='Recent conversation ' + str(i))
    filler.add('user', 'General notes'); ctx.chat._store.save(filler)
ctx.chat._refresh_recents()
assert chat.id not in [r['id'] for r in ctx.chat.recents]
def record(ident, name, project_id, task, answer):
    return clean_record({'id': ident * 32, 'kind': 'team', 'name': name, 'projectId': project_id,
        'projectName': 'Expedition' if project_id else 'Personal', 'task': task,
        'answer': answer, 'status': 'complete', 'started': time.time()})
rows = [record('a', 'software', project, 'Build a notebook', 'The parser supports fluorescence.'),
        record('b', 'research', project, 'Explain light', 'Fluorescence differs from bioluminescence.'),
        record('c', 'research', '', 'Private expedition', 'Unrelated fluorescence in another project.')]
ctx.agents._records = {r['id']: r for r in rows}
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.requestActivate(); QTest.qWait(60)
def wait(done):
    deadline = time.monotonic() + 5
    while not done() and time.monotonic() < deadline:
        QTest.qWait(10); time.sleep(.005)
    assert done(), (ctx.chat.historySearch._query, ctx.chat.historySearch.busy, ctx.chat.historySearch.note, ctx.chat.historySearch.results, warnings)
def invoke(obj, method, *args):
    QMetaObject.invokeMethod(obj, method, Qt.DirectConnection, *[Q_ARG('QVariant', arg) for arg in args])
    QTest.qWait(30)
def value(obj, prop):
    result = obj.property(prop)
    return result.toVariant() if hasattr(result, 'toVariant') else result
def capture(label):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        target = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ.get('QT_SCALE_FACTOR', '1')
        target.mkdir(parents=True, exist_ok=True); QTest.qWait(90)
        assert win.grabWindow().save(str(target / (label + '.png')))
sidebar = win.findChild(QObject, 'workspaceSidebar')
sidebar.setProperty('searchText', 'bioluminescence')
wait(lambda: len(ctx.chat.historySearch.results) == 1)
assert value(sidebar, 'filteredRecents')[0]['id'] == chat.id
assert 'chemical reactions' in value(sidebar, 'filteredRecents')[0]['snippet']
for mode in ['dark', 'light']:
    ctx.theme.mode = mode; capture(mode + '-sidebar')
# Enter uses the existing openRecent flow, including original project restoration.
assert not ctx.projects.openProject('')
wait(lambda: not sidebar.property('searchPending'))
invoke(sidebar, 'openFirstMatch')
assert ctx.chat.conversationId == chat.id and ctx.projects.currentId == project
assert not sidebar.property('searchText') and not ctx.chat.historySearch.results
sidebar.setProperty('searchText', 'does-not-exist')
wait(lambda: not sidebar.property('searchPending'))
assert win.findChild(QObject, 'sidebarSearchEmpty').property('visible')
sidebar.setProperty('searchText', '')
# Search the answer, retaining the Code team filter and current project.
history = win.findChild(QObject, 'runHistorySheet')
invoke(history, 'present', 'software')
search = win.findChild(QObject, 'taskHistorySearch')
search.setProperty('text', 'fluorescence')
wait(lambda: history.property('query') == 'fluorescence')
assert [r['id'] for r in value(history, 'saved')] == ['a' * 32]
assert history.property('selectedId') == 'a' * 32
for mode in ['dark', 'light']:
    ctx.theme.mode = mode; capture(mode + '-task-result')
search.setProperty('text', 'not-present'); wait(lambda: history.property('query') == 'not-present')
assert not value(history, 'saved') and not history.property('selectedId')
search.setProperty('text', ''); wait(lambda: history.property('query') == '')
assert history.property('selectedId') == 'a' * 32
invoke(history, 'present', '')
search.setProperty('text', 'fluorescence'); wait(lambda: history.property('query') == 'fluorescence')
assert len(value(history, 'saved')) == 2
history.setProperty('allProjects', True); QTest.qWait(50)
assert len(value(history, 'saved')) == 3
invoke(history, 'close')
# Research search does not show software tasks or other projects.
win.setProperty('currentNav', 'research')
win.findChild(QObject, 'researchView').setProperty('investigating', True)
view = win.findChild(QObject, 'researchInvestigations')
search = win.findChild(QObject, 'investigationSearch')
search.setProperty('text', 'fluorescence'); wait(lambda: view.property('query') == 'fluorescence')
assert [r['id'] for r in value(view, 'saved')] == ['b' * 32]
invoke(view, 'choose', 'b' * 32)
for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    for width, height in [(900, 600), (1440, 900)]:
        win.setWidth(width); win.setHeight(height); capture(mode + '-research-' + str(width))
search.setProperty('text', 'no-match'); wait(lambda: view.property('query') == 'no-match')
assert not value(view, 'saved') and not view.property('hasRun')
assert not ctx.projects.openProject(''); QTest.qWait(60)
assert not search.property('text') and not view.property('query')
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('HISTORY_SEARCH_UI_OK')
'''


@pytest.mark.parametrize("scale", ["1", "1.5"])
def test_saved_content_search_in_window(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1", QT_SCALE_FACTOR=scale)
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO)],
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HISTORY_SEARCH_UI_OK" in result.stdout
