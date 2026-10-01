"""Theme-only artwork, readable chat, and animation lifecycle in the real window."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import os, sys, time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtTest import QTest
from akira.ui.engine import configure_application, build_engine, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
QFontDatabase.addApplicationFont('C:/Windows/Fonts/SegUIVar.ttf')
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
ctx = build_context(persist=False); ctx.theme.mode = 'light'; ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
def find(name): return win.findChild(QObject, name)
def wait(check):
    deadline = time.monotonic() + 5
    while not check() and time.monotonic() < deadline: QTest.qWait(20)
    assert check()
def capture(name):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        out = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ['QT_SCALE_FACTOR']
        out.mkdir(parents=True, exist_ok=True)
        assert win.grabWindow().save(str(out / (name + '.png')))
scene = find('chatMegastructure'); chat = find('mainChatView')
cave = find('chatCaveGarden')
assert not cave.isVisible() and not cave.property('moving')
wait(lambda: scene.property('ready'))
assert scene.isVisible() and chat.property('onScene')
assert not scene.property('moving')
assert not find('megastructureArtwork').property('smooth')
assert not find('chatReadingSurface').isVisible()
for w, h in [(1440,900), (900,600)]:
    win.setWidth(w); win.setHeight(h); QTest.qWait(100)
    capture('light-empty-' + str(w))
composer = find('workspaceComposer'); composer.setProperty('text', 'Keep my draft')
ctx.chat.messages.reset([
    SimpleNamespace(id='one', role='user', text='How should I organize a research project?', error=False),
    SimpleNamespace(id='two', role='assistant', error=False, text='Start with a clear question, then keep your sources and findings together.\n\n**A simple structure**\n\n1. Write the question you want to answer.\n2. Collect a few reliable sources.\n3. Record what each source supports.\n4. Keep open questions in a separate note.\n\nThis gives you a useful starting point without making the project harder to maintain.')])
QTest.qWait(100)
assert find('chatReadingSurface').isVisible()
assert find('chatReadingSurface').property('opacity') >= .97
for w, h in [(1440,900), (900,600)]:
    win.setWidth(w); win.setHeight(h); QTest.qWait(100)
    capture('light-chat-' + str(w))
ctx.theme.reduceMotion = False; QTest.qWait(100)
assert scene.property('moving')
beacons = find('megastructureBeacons')
before = beacons.property('opacity'); QTest.qWait(250)
assert abs(beacons.property('opacity') - before) > .001
win.hide(); QTest.qWait(40); assert not scene.property('moving')
win.show(); QTest.qWait(50); assert scene.property('moving')
win.showMinimized(); QTest.qWait(50); assert not scene.property('moving')
win.showNormal(); QTest.qWait(50); assert scene.property('moving')
for page in ['agents', 'documents', 'code', 'research']:
    QMetaObject.invokeMethod(win, 'selectWorkspace', Qt.DirectConnection, Q_ARG('QVariant', page))
    QTest.qWait(40)
    assert not scene.isVisible() and not scene.property('moving')
QMetaObject.invokeMethod(win, 'selectWorkspace', Qt.DirectConnection, Q_ARG('QVariant', 'chats'))
QTest.qWait(40); assert scene.isVisible() and scene.property('moving')
ctx.theme.mode = 'dark'; QTest.qWait(100)
assert not scene.isVisible() and not scene.property('moving') and chat.property('onScene')
wait(lambda: cave.property('ready'))
assert cave.isVisible() and cave.property('moving')
assert not find('caveGardenArtwork').property('smooth')
assert find('caveGardenArtwork').property('sourceSize') == find('megastructureArtwork').property('sourceSize')
assert find('chatReadingSurface').isVisible()
assert find('chatReadingSurface').property('color').lightnessF() < .1
torch = find('caveTorchlight')
before = torch.property('opacity'); QTest.qWait(250)
assert abs(torch.property('opacity') - before) > .001
ctx.theme.reduceMotion = True; QTest.qWait(40)
assert not cave.property('moving')
before = torch.property('opacity'); QTest.qWait(100)
assert torch.property('opacity') == before
for w, h in [(1440,900), (900,600)]:
    win.setWidth(w); win.setHeight(h); QTest.qWait(100)
    capture('dark-chat-' + str(w))
saved = ctx.chat.messages._messages
ctx.chat.messages.reset([])
for w, h in [(1440,900), (900,600)]:
    win.setWidth(w); win.setHeight(h); QTest.qWait(100)
    capture('dark-empty-' + str(w))
ctx.chat.messages.reset(saved)
ctx.theme.reduceMotion = False; QTest.qWait(50)
win.hide(); QTest.qWait(40); assert not cave.property('moving')
win.show(); QTest.qWait(40); assert cave.property('moving')
win.showMinimized(); QTest.qWait(40); assert not cave.property('moving')
win.showNormal(); QTest.qWait(40); assert cave.property('moving')
for page in ['agents', 'documents', 'code', 'research']:
    QMetaObject.invokeMethod(win, 'selectWorkspace', Qt.DirectConnection, Q_ARG('QVariant', page))
    QTest.qWait(40)
    assert not cave.isVisible() and not cave.property('moving')
QMetaObject.invokeMethod(win, 'selectWorkspace', Qt.DirectConnection, Q_ARG('QVariant', 'chats'))
QTest.qWait(40); assert cave.isVisible() and cave.property('moving')
ctx.theme.mode = 'light'; ctx.theme.reduceMotion = True; QTest.qWait(100)
assert scene.isVisible() and not scene.property('moving')
assert not cave.isVisible() and not cave.property('moving')
before = beacons.property('opacity'); QTest.qWait(100)
assert beacons.property('opacity') == before
assert composer.property('text') == 'Keep my draft' and ctx.chat.messages.count == 2
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('MEGASTRUCTURE_OK')
'''


@pytest.mark.parametrize('scale', ['1', '1.5'])
def test_megastructure_chat(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'),
               QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
               QML_DISABLE_DISK_CACHE='1', QT_SCALE_FACTOR=scale)
    env.pop('PROTEGE_CONFIG_DIR', None)
    result = subprocess.run([sys.executable, '-c', PROBE, str(REPO)], env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'MEGASTRUCTURE_OK' in result.stdout
