"""Real call windows and permission controls, with audio hardware replaced by fakes."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, str(Path(sys.argv[1]) / 'tests'))
from test_voice_bridge import FakeCall, FakeListener, FakeSpeaker
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtTest import QTest
from akira.core.voice.store import VoiceStore
from akira.ui.bridge.voice import VoiceBridge
from akira.ui.engine import configure_application, build_engine, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
for name in ['SegUIVar.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
ctx.permissions.grantsChanged.disconnect(ctx.voice.refresh); ctx.voice.close()
policy = ctx.permissions.policy
speaker = FakeSpeaker(policy)
voice = VoiceBridge(lambda: policy, store=VoiceStore(Path(sys.argv[2]) / 'voice.json'),
    listener=FakeListener(policy), speaker=speaker, check=lambda: '', make_call=FakeCall)
voice.follow(ctx.chat); ctx.voice = voice
ctx.permissions.grantsChanged.connect(voice.refresh)
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.requestActivate(); QTest.qWait(60)
sheet = win.findChild(QObject, 'voiceSheet')
call_window = win.findChild(QObject, 'voiceCallWindow')
assert not voice.inCall and not call_window.isVisible()
def invoke(obj, method, *args):
    assert QMetaObject.invokeMethod(obj, method, Qt.DirectConnection, *[Q_ARG('QVariant', a) for a in args])
    QTest.qWait(50)
def walk(item):
    yield item
    for child in item.childItems(): yield from walk(child)
def find(name, window=win):
    return next(o for o in walk(window.contentItem()) if o.objectName() == name)
def press(item, window=win):
    assert item.property('enabled')
    window.requestActivate(); invoke(item, 'forceActiveFocus')
    QTest.keyClick(window, Qt.Key_Space); QTest.qWait(70)
def capture(label, window=win):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        target = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ.get('QT_SCALE_FACTOR', '1')
        target.mkdir(parents=True, exist_ok=True); QTest.qWait(100)
        assert window.grabWindow().save(str(target / (label + '.png')))
press(find('composerVoice'))
assert sheet.property('opened') and not voice.inCall
assert not find('voiceStartCall').property('enabled')
press(find('voicePermission_audio.record'))
assert not find('voiceStartCall').property('enabled')
press(find('voicePermission_audio.play'))
assert find('voiceStartCall').property('enabled') and not voice.inCall
assert len(voice.voices) == 6
# Selection invokes existing persistence slots, and a sample never starts a call.
choice = find('voiceChoice')
choice.picked.emit(voice.voices[1]['id']); QTest.qWait(40)
assert voice.voice == voice.voices[1]['id']
find('voiceSpeed').picked.emit('1.2'); QTest.qWait(40)
assert voice.speed == 1.2
press(find('voicePreview'))
assert speaker.said and not voice.inCall
voice.stopSpeaking()
for mode in ['dark', 'light']:
    ctx.theme.mode = mode; capture(mode + '-voice-settings')
# The lower call action must be visible when reached by keyboard in a short window.
invoke(find('voiceStartCall'), 'forceActiveFocus')
start = find('voiceStartCall')
assert start.mapToScene(start.boundingRect().center()).y() < win.height() - 50
capture('voice-settings-call-action')
press(find('voiceStartCall'))
assert voice.inCall and call_window.isVisible() and not sheet.property('opened')
assert call_window.transientParent() is None
assert call_window.flags() & Qt.WindowStaysOnTopHint
call = FakeCall.made[-1]
assert call.started
conversation = ctx.chat.conversationId
for page in ['code', 'research', 'chats']:
    invoke(win, 'selectWorkspace', page)
    assert win.property('currentNav') == page
    assert voice.inCall and ctx.chat.conversationId == conversation
assert not win.findChild(QObject, 'activeProjectPicker').property('enabled')
assert not win.findChild(QObject, 'workspaceSidebar').property('newChatEnabled')
for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    capture(mode + '-call-listening', call_window)
    press(find('callMute', call_window), call_window)
    assert voice.muted and 'muted' in find('callStateLabel', call_window).property('text').lower()
    capture(mode + '-call-muted', call_window)
    press(find('callMute', call_window), call_window)
    assert not voice.muted
win.showMinimized(); QTest.qWait(60)
assert voice.inCall and call_window.isVisible()
win.showNormal(); QTest.qWait(30)
# Closing the main window leaves the independent call alive.
win.close(); QTest.qWait(70)
assert not win.isVisible() and voice.inCall and call_window.isVisible()
press(find('callReturn', call_window), call_window)
assert win.isVisible() and voice.inCall
win.close(); QTest.qWait(60)
press(find('callEnd', call_window), call_window)
assert call.ended and not voice.inCall and not call_window.isVisible() and win.isVisible()
# The widget's native close button ends the call too.
invoke(sheet, 'open'); press(find('voiceStartCall'))
call = FakeCall.made[-1]
call_window.close(); QTest.qWait(60)
assert call.ended and not voice.inCall and not call_window.isVisible()
# Revocation ends a hidden-main call and restores the app to display the reason.
invoke(sheet, 'open'); press(find('voiceStartCall'))
win.close(); ctx.permissions.revoke('audio.record')
# Real Call polls permission; the hardware fake reports that same end event.
FakeCall.made[-1].finished('Not permitted: Listen has not been allowed.')
QTest.qWait(80)
assert not voice.inCall and not call_window.isVisible() and win.isVisible(), (voice.inCall, call_window.isVisible(), win.isVisible(), win.property('callWasActive'), voice.note)
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('VOICE_UI_OK')
'''


@pytest.mark.parametrize("scale", ["1", "1.5"])
def test_call_window_lifetime_and_explicit_permissions(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"), QT_QPA_PLATFORM="offscreen",
               QT_QUICK_BACKEND="software", QML_DISABLE_DISK_CACHE="1", QT_SCALE_FACTOR=scale)
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO), str(tmp_path)],
                            env=env, capture_output=True, text=True, timeout=100)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'VOICE_UI_OK' in result.stdout
