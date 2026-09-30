"""The calendar page, driven through the real window by mouse and keys."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

PROBE = r'''
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, QPoint, QPointF, Q_ARG, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from akira.core import planner
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context

app = QGuiApplication([]); configure_application(app)
today = date.today()
# A day beside today in the same month, for dragging to and adding on.
other = today + timedelta(days=1) if (today + timedelta(days=1)).month == today.month else today - timedelta(days=1)
store = planner.shared()
dentist = store.add(planner.draft('Dentist', today.isoformat() + 'T15:00', where='Leeds'))

ctx = build_context(persist=False); ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(1280); win.setHeight(800); win.requestActivate(); QTest.qWait(100)

def walk(it, name):
    for child in it.childItems():
        if child.objectName() == name and child.isVisible():
            return child
        found = walk(child, name)
        if found is not None:
            return found
    return None
def item(name):
    found = walk(win.contentItem(), name)
    assert found is not None, name
    return found
def point(it):
    return it.mapToScene(QPointF(it.width() / 2, it.height() / 2)).toPoint()
def click(it):
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, point(it)); QTest.qWait(80)
def typed(name, text, enter=False):
    click(item(name))
    QTest.keyClick(win, Qt.Key_A, Qt.ControlModifier)
    for ch in text:
        QTest.keyClick(win, ch)
    QTest.qWait(40)
    if enter:
        QTest.keyClick(win, Qt.Key_Return); QTest.qWait(120)
def invoke(obj, method, *args):
    QMetaObject.invokeMethod(obj, method, Qt.DirectConnection, *[Q_ARG('QVariant', a) for a in args])
    QTest.qWait(120)

win.setProperty('currentNav', 'calendar'); QTest.qWait(200)
view = win.findChild(QObject, 'calendarView')
sheet = win.findChild(QObject, 'calendarEventSheet')
assert view.property('visible') and not sheet.property('opened')
item('calendarDay_' + today.isoformat())
# A new setup has not allowed the chat to read it: the page says so, with the way.
assert 'can\'t see this calendar yet' in item('calendarHint').property('text')

# Clicked, an event opens whole; renamed and saved, it is changed.
click(item('calendarChip_%s_%s' % (dentist.id, today.isoformat())))
assert sheet.property('opened') and sheet.property('eventTitle') == 'Dentist'
assert sheet.property('startTime') == '15:00' and sheet.property('where') == 'Leeds'
typed('eventTitleInput', 'Hygienist')
click(item('eventSave'))
assert not sheet.property('opened'), sheet.property('notice')
assert store.get(dentist.id).title == 'Hygienist'

# A line with a day and a time is added at once, and can be undone.
words = '%d %s %d' % (other.day, other.strftime('%B'), other.year)
typed('calendarQuickAdd', 'Lunch with Sam ' + words + ' 12:30', enter=True)
lunch = [e for e in store.events() if e.title == 'Lunch with Sam']
assert len(lunch) == 1 and lunch[0].start == datetime(other.year, other.month, other.day, 12, 30)
assert item('calendarNotice').property('text').startswith('Added: Lunch with Sam')
assert view.property('selectedDay') == other.isoformat()
click(item('calendarUndo'))
assert not [e for e in store.events() if e.title == 'Lunch with Sam']

# A line with no day or time opens the editor with it, for the day chosen.
typed('calendarQuickAdd', 'Holiday', enter=True)
assert sheet.property('opened') and sheet.property('eventTitle') == 'Holiday'
assert sheet.property('allDay') and sheet.property('startDate') == other.isoformat()
click(item('eventSave'))
(holiday,) = [e for e in store.events() if e.title == 'Holiday']
assert holiday.start == other and holiday.all_day

# What cannot be kept is said in the editor, which stays open.
click(item('calendarNew'))
typed('eventTitleInput', 'Party')
typed('eventStartDate', 'soon')
click(item('eventSave'))
assert sheet.property('opened') and 'not a date' in sheet.property('notice')
click(item('eventCancel'))
assert not sheet.property('opened') and not [e for e in store.events() if e.title == 'Party']

# Removing asks once, in place.
click(item('calendarChip_%s_%s' % (holiday.id, other.isoformat())))
click(item('eventRemove'))
assert sheet.property('opened') and sheet.property('confirmingRemove')
assert store.get(holiday.id)
click(item('eventRemove'))
assert not sheet.property('opened') and not [e for e in store.events() if e.id == holiday.id]

# Dragged to another day, an event keeps its time.
chip = item('calendarChip_%s_%s' % (dentist.id, today.isoformat()))
target = item('calendarDay_' + other.isoformat())
start, end = point(chip), point(target)
QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, start); QTest.qWait(30)
for step in range(1, 13):
    QTest.mouseMove(win, QPoint(start.x() + (end.x() - start.x()) * step // 12,
                                start.y() + (end.y() - start.y()) * step // 12)); QTest.qWait(15)
QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, end); QTest.qWait(150)
assert store.get(dentist.id).start == datetime(other.year, other.month, other.day, 15, 0), \
    store.get(dentist.id).start

# The week: a timed event is a block in its day's hours.
invoke(view, 'setMode', 'week')
assert item('calendarWeek').isVisible() and not walk(win.contentItem(), 'calendarMonth')
item('calendarBlock_%s_%s' % (dentist.id, other.isoformat()))
# An agent's change, straight to the store, reaches the page.
store.add(planner.draft('Added by an agent', other.isoformat()))
QTest.qWait(150)
assert walk(win.contentItem(), 'calendarChip_%s_%s' % (store.events()[-1].id if store.events()[-1].title == 'Added by an agent' else [e for e in store.events() if e.title == 'Added by an agent'][0].id, other.isoformat())) is not None

assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('CALENDAR_UI_OK')
'''


def test_the_calendar_page_in_the_window(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1")
    env.pop("PROTEGE_CONFIG_DIR", None)
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO)], env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CALENDAR_UI_OK" in result.stdout
