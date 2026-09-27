"""The menu on a chat in the sidebar, driven through the real window by mouse and keys."""
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
from PySide6.QtCore import QObject, QMetaObject, QPointF, Q_ARG, Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from akira.core.conversation import Conversation
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
for name in ['SegUIVar.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
assert not ctx.projects.create('Garden', '')
garden = ctx.projects.currentId
def saved(title, project='', age=0):
    chat = Conversation(title=title, project=project)
    chat.add('user', title + '?'); chat.add('assistant', 'ok')
    ctx.chat._store.save(chat)
    when = time.time() - age
    os.utime(ctx.chat._store.directory / (chat.id + '.json'), (when, when))
    return chat.id
beans = saved('Beans', garden, 10)
recipes = saved('Recipes', '', 200)
old = saved('Old notes', '', 300)
ctx.chat._refresh_recents()
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(1100); win.setHeight(700); win.requestActivate(); QTest.qWait(80)
def invoke(obj, method, *args):
    QMetaObject.invokeMethod(obj, method, Qt.DirectConnection, *[Q_ARG('QVariant', a) for a in args])
    QTest.qWait(40)
def walk(it, name):
    # Repeated rows and a popup's contents are in the visual tree, not the object tree.
    for child in it.childItems():
        if child.objectName() == name and child.isVisible():
            return child
        found = walk(child, name)
        if found is not None:
            return found
    return None
def item(name):
    found = walk(win.contentItem(), name) or win.findChild(QQuickItem, name)
    assert found is not None, name
    return found
def point(it):
    return it.mapToScene(QPointF(it.width() / 2, it.height() / 2)).toPoint()
def click(it, button=Qt.LeftButton):
    QTest.mouseClick(win, button, Qt.NoModifier, point(it)); QTest.qWait(60)
def recents():
    # Nothing done in the menu opens the chat under it.
    assert ctx.chat.conversationId == beans, 'a press on the menu reached the chat underneath'
    return [(r['title'], r['pinned'], r['project']) for r in ctx.chat.recents]
menu = win.findChild(QObject, 'chatMenu')
assert menu is not None

invoke(win, 'openRecent', beans)
assert ctx.chat.conversationId == beans and ctx.projects.currentId == garden
composer = item('composerInput') if win.findChild(QQuickItem, 'composerInput') else None

# A right-click opens the menu; pinning puts the chat at the top.
click(item('recent_' + recipes), Qt.RightButton)
assert menu.property('opened'), 'right-click did not open the menu'
click(item('chatMenuPin'))
assert not menu.property('opened')
assert recents()[0] == ('Recipes', True, '')

# Rename in place: Enter saves, and the list keeps its order.
click(item('recent_' + recipes), Qt.RightButton)
click(item('chatMenuRename'))
name = item('chatMenuName')
assert name.property('activeFocus')
QTest.keyClick(win, Qt.Key_A, Qt.ControlModifier)
[QTest.keyClick(win, ch) for ch in 'Soup ideas']; QTest.keyClick(win, Qt.Key_Return); QTest.qWait(60)
assert recents()[0] == ('Soup ideas', True, ''), recents()
# An empty name is refused, and says why.
click(item('recent_' + recipes), Qt.RightButton)
click(item('chatMenuRename'))
QTest.keyClick(win, Qt.Key_A, Qt.ControlModifier); QTest.keyClick(win, Qt.Key_Delete)
QTest.keyClick(win, Qt.Key_Return); QTest.qWait(60)
assert menu.property('opened') and item('chatMenuReason').property('text') == 'Give the chat a name.'
QTest.keyClick(win, Qt.Key_Escape); QTest.qWait(60)
assert not menu.property('opened')

# From the keyboard: the Menu key on a focused chat; delete asks first, Keep is focused.
row = item('recent_' + old)
row.forceActiveFocus(); QTest.keyClick(win, Qt.Key_Menu); QTest.qWait(60)
assert menu.property('opened'), 'the Menu key did not open the menu'
click(item('chatMenuDelete'))
assert item('chatMenuCancel').property('activeFocus')
assert old in [r['id'] for r in ctx.chat.recents]
click(item('chatMenuConfirm'))
assert old not in [r['id'] for r in ctx.chat.recents]
row = item('recent_' + recipes)
row.forceActiveFocus(); QTest.keyClick(win, Qt.Key_F10, Qt.ShiftModifier); QTest.qWait(60)
assert menu.property('opened'), 'Shift+F10 did not open the menu'
QTest.keyClick(win, Qt.Key_Escape); QTest.qWait(60)

# Moving the open chat takes the window with it, keeping the chat open.
click(item('recent_' + beans), Qt.RightButton)
click(item('chatMenuMove'))
click(item('chatMove_personal'))
assert ctx.projects.currentId == '', ctx.projects.currentId
assert ctx.chat.conversationId == beans
assert ctx.chat._store.load(beans).project == ''
# And back.
click(item('recent_' + beans), Qt.RightButton)
click(item('chatMenuMove'))
click(item('chatMove_' + garden))
assert ctx.projects.currentId == garden and ctx.chat.conversationId == beans

if os.environ.get('AKIRA_REVIEW_DIR'):
    target = Path(os.environ['AKIRA_REVIEW_DIR']); target.mkdir(parents=True, exist_ok=True)
    for mode in ['dark', 'light']:
        ctx.theme.mode = mode
        click(item('recent_' + recipes), Qt.RightButton)
        win.grabWindow().save(str(target / (mode + '-chat-menu.png')))
        click(item('chatMenuDelete'))
        win.grabWindow().save(str(target / (mode + '-chat-delete.png')))
        QTest.keyClick(win, Qt.Key_Escape); QTest.qWait(60)

# Settings → Chats: a bulk delete says how many, asks, and spares pinned chats.
saved('Ancient', '', 90 * 86400)
saved('Older', '', 40 * 86400)
ctx.chat._refresh_recents(); QTest.qWait(40)
sheet = win.findChild(QObject, 'settingsSheet')
QMetaObject.invokeMethod(sheet, 'open', Qt.DirectConnection); QTest.qWait(80)
win.findChild(QObject, 'settingsSections').selected.emit('chats'); QTest.qWait(60)
assert sheet.property('oldCount') == 2 and sheet.property('allCount') == 3, (sheet.property('oldCount'), sheet.property('allCount'))
click(item('deleteOldChats'))
assert item('keepChats').property('activeFocus')
if os.environ.get('AKIRA_REVIEW_DIR'):
    win.grabWindow().save(str(target / 'settings-chats.png'))
click(item('keepChats'))
assert len(ctx.chat.recents) == 4
click(item('deleteOldChats')); click(item('confirmClearChats'))
assert item('clearedChats').property('text') == 'Deleted 2 chats.'
assert [r['title'] for r in ctx.chat.recents] == ['Soup ideas', 'Beans']
assert sheet.property('allCount') == 1
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('CHAT_MENU_OK')
'''


@pytest.mark.parametrize("scale", ["1", "1.5"])
def test_the_chat_menu_in_the_window(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1", QT_SCALE_FACTOR=scale)
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO)],
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHAT_MENU_OK" in result.stdout
