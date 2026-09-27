"""One live transcript, routed by kind, with entirely fake inference/research."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import os, sys, time, threading
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, str(Path(sys.argv[1]) / 'tests'))
from test_unified_chat import Backend
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt, QPointF
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlExpression
from akira.core.brain.research import Findings
from akira.core.conversation import Cancelled
from akira.core.conversations import ConversationStore
from akira.core.config import AppConfig, ModelConfig
from akira.core.models import ModelRouter
from akira.models.base import GenerationResult
from akira.ui.bridge.chat import ChatBridge
from akira.ui.engine import configure_application, build_engine, load
from akira.ui.shell import build_context
from akira.security.qtguard import refused

app = QGuiApplication([]); configure_application(app)
QFontDatabase.addApplicationFont('C:/Windows/Fonts/SegUIVar.ttf')
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
fake = Path(sys.argv[2]) / 'fake.gguf'; fake.write_bytes(b'gguf')
config = AppConfig(models={'chat': ModelConfig(path=str(fake)), 'code': ModelConfig(path=str(fake))})
router = ModelRouter(config); backend = Backend(); routes = []
@contextmanager
def acquire(route):
    routes.append(route); yield backend
router.acquire = acquire
steps = ['Researching', 'Searching the web for “ocean currents”', 'Reading en.wikipedia.org',
         'Reading budget.xlsx', 'Searching your files']
gates = [threading.Event() for _ in steps]
citations = [{'source': 'web', 'cite': 'https://en.wikipedia.org/wiki/Ocean'},
             {'source': 'files', 'cite': 'budget.xlsx'},
             {'source': 'files', 'cite': '<img src="https://outside.invalid/private">.txt'}]
def research(question, *, on_step, is_cancelled, **kwargs):
    for step, gate in zip(steps, gates):
        on_step(step)
        while not gate.wait(.01):
            if is_cancelled(): raise Cancelled()
    return Findings(material='Ocean currents affect climate.', sources=citations, note='')
chat = ChatBridge(router, config, ConversationStore(Path(sys.argv[2]) / 'chats'), researcher=research)
ctx.chat = chat
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.requestActivate(); QTest.qWait(60)
def find(name): return win.findChild(QObject, name)
def wait(done):
    until = time.monotonic() + 5
    while not done() and time.monotonic() < until:
        QTest.qWait(10); time.sleep(.005)
    assert done()
def invoke(obj, method, *args):
    assert QMetaObject.invokeMethod(obj, method, Qt.DirectConnection, *[Q_ARG('QVariant', a) for a in args])
    QTest.qWait(30)
def walk(item):
    yield item
    for child in item.childItems(): yield from walk(child)
def capture(name):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        out = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ['QT_SCALE_FACTOR']
        out.mkdir(parents=True, exist_ok=True)
        assert win.grabWindow().save(str(out / (name + '.png')))
mode = find('chatMode'); composer = find('workspaceComposer'); label = find('chatIntentModel')
assert mode.property('current') == 'auto'
assert find('workspaceScene') is None
assert not hasattr(chat, 'switchWorkspace')
conversation = chat.conversationId
for pinned, expected in [('everyday', 'Everyday'), ('code', 'Code')]:
    # Use the actual keyboard-operated dropdown, not a bridge-only call.
    box = next(o for o in mode.findChildren(QObject) if o.metaObject().className().startswith('ComboBox_'))
    invoke(box, 'forceActiveFocus'); QTest.keyClick(win, Qt.Key_Space); QTest.keyClick(win, Qt.Key_Home)
    for _ in range(['auto', 'everyday', 'code', 'research'].index(pinned)):
        QTest.keyClick(win, Qt.Key_Down)
    QTest.keyClick(win, Qt.Key_Return); QTest.qWait(30)
    assert chat.mode == pinned
    chat.send('Hello'); wait(lambda: not chat.busy)
    assert chat.intentLabel == expected and label.property('text') == expected + ' · ' + chat.routeLabel
    assert chat.conversationId == conversation
composer.setProperty('text', 'Keep this draft')
for page in ['code', 'research', 'chats']:
    invoke(win, 'selectWorkspace', page)
    assert chat.conversationId == conversation and chat.messages.count == 4
    assert composer.property('text') == 'Keep this draft'
    assert composer.property('visible') == (page == 'chats')
assert len(chat.recents) == 1
mode.picked.emit('research'); QTest.qWait(20)
chat.send('Compare ocean currents')
for index, step in enumerate(steps):
    wait(lambda: find('chatStage').property('text') == step)
    QTest.qWait(40)
    stage = find('chatStage')
    assert stage.property('visible') and stage.width() > 0
    assert stage.mapToScene(QPointF(0, stage.height())).y() <= composer.mapToScene(QPointF(0, 0)).y()
    assert label.property('text') == 'Research · ' + chat.routeLabel
    if index == 0:
        # A choice during a turn is for the next message, not the current answer.
        mode.picked.emit('everyday'); QTest.qWait(20)
        assert chat.mode == 'everyday' and chat.intentLabel == 'Research'
    capture('research-step-' + str(index))
    gates[index].set()
wait(lambda: not chat.busy)
source = find('contextSources'); assert source.property('visible')
invoke(source.findChild(QObject, 'contextSourcesToggle'), 'forceActiveFocus')
QTest.keyClick(win, Qt.Key_Space); QTest.qWait(50)
assert source.property('expanded')
transcript = find('chatTranscript')
assert transcript.property('contentY') >= transcript.property('contentHeight') - transcript.height() - 1
shown = [o for o in walk(source) if o.objectName() == 'chatSourceCitation']
assert [o.property('text') for o in shown] == [c['cite'] for c in citations]
assert all(QQmlExpression(engine.rootContext(), o, 'textFormat === 0').evaluate()[0] for o in shown)
assert not refused
for appearance in ['dark', 'light']:
    ctx.theme.mode = appearance; QTest.qWait(40)
    assert source.mapToScene(QPointF(0, source.height())).y() <= composer.mapToScene(QPointF(0, 0)).y()
    assert label.mapToScene(QPointF(label.width(), label.height())).x() <= win.width()
    capture(appearance + '-one-chat-sources')
chat.send('Hello again'); wait(lambda: not chat.busy)
assert chat.intentLabel == 'Everyday' and chat.conversationId == conversation
mode.picked.emit('auto'); QTest.qWait(20)
chat.send('Write a Python function to reverse a string'); wait(lambda: not chat.busy)
assert chat.intentLabel == 'Code'
# Backend-added provenance and arithmetic lines remain visible in normal reply text.
reply = 'An answer.\n\nNote: nothing from Wikipedia was read for this answer.\n\nCorrection: 2 + 2 = 5 is wrong; it comes to 4.'
def answer(messages, *, on_token=None, **kwargs):
    if on_token: on_token(reply)
    return GenerationResult(text=reply)
backend.generate = answer
chat.send('Hello'); wait(lambda: not chat.busy); QTest.qWait(40)
texts = [str(o.property('text') or '') for o in walk(find('mainChatView'))]
assert any('Note: nothing from Wikipedia' in t and 'Correction: 2 + 2 = 5' in t for t in texts)
# Stop through the composer reaches the researcher cancellation callback.
gates = [threading.Event() for _ in steps]
mode.picked.emit('research'); QTest.qWait(20); before = len(routes)
chat.send('Look up ocean currents'); wait(lambda: find('chatStage').property('text') == 'Researching')
composer.stopped.emit(); wait(lambda: not chat.busy)
assert len(routes) == before
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('ONE_CHAT_UI_OK')
'''


@pytest.mark.parametrize('scale', ['1', '1.5'])
def test_one_chat_ui(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'), QT_QPA_PLATFORM='offscreen',
               QT_QUICK_BACKEND='software', QML_DISABLE_DISK_CACHE='1', QT_SCALE_FACTOR=scale)
    env.pop('PROTEGE_CONFIG_DIR', None)
    result = subprocess.run([sys.executable, '-c', PROBE, str(REPO), str(tmp_path)],
                            env=env, capture_output=True, text=True, timeout=65, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ONE_CHAT_UI_OK' in result.stdout
