"""Pictures UI with the real bridge and a local, controllable fake renderer."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = r'''
import os, sys, time, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Q_ARG, Qt, QBuffer, QIODevice, QUrl
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont, QImage, QColor
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from akira.core.making import images
from akira.core.making.images import Picture, ImageError
from akira.ui.bridge.images import ImagesBridge
from akira.ui.engine import configure_application, build_engine, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
for name in ['SegUIVar.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
for family in ['Segoe UI Variable Display', 'Segoe UI Variable Text', 'Segoe UI Variable Small']:
    QFont.insertSubstitution(family, 'Segoe UI Variable')
fixture = QImage(64, 64, QImage.Format_RGB32); fixture.fill(QColor('#318366'))
buf = QBuffer(); buf.open(QIODevice.WriteOnly); assert fixture.save(buf, 'PNG'); png = bytes(buf.data())
gate = threading.Event()
class Maker:
    prepared = False
    calls = []
    fail = False
    def make(self, prompt, **kw):
        self.calls.append((prompt, kw)); gate.wait(5)
        if self.fail: raise ImageError('Fixture renderer unavailable.')
        self.prepared = True
        return Picture(png, prompt, kw['width'], kw['height'], kw['steps'], 42, .1)
maker = Maker(); images.unavailable = lambda: ''
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
ctx.images.close(); ctx.images = ImagesBridge(maker)
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.setProperty('currentNav', 'documents'); QTest.qWait(60)
sheet = win.findChild(QObject, 'picturesSheet')
def invoke(obj, method, *args):
    assert QMetaObject.invokeMethod(obj, method, Qt.DirectConnection, *[Q_ARG('QVariant', a) for a in args])
    QTest.qWait(40)
def walk(item):
    yield item
    for child in item.childItems(): yield from walk(child)
def find(name):
    return next(i for i in walk(win.contentItem()) if i.objectName() == name)
def press(item):
    assert item.property('enabled')
    win.requestActivate(); invoke(item, 'forceActiveFocus'); QTest.keyClick(win, Qt.Key_Space); QTest.qWait(50)
def finish():
    gate.set(); deadline = time.monotonic() + 5
    while ctx.images.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    QTest.qWait(40); assert not ctx.images.busy
def capture(label):
    if os.environ.get('AKIRA_REVIEW_DIR'):
        folder = Path(os.environ['AKIRA_REVIEW_DIR']) / os.environ.get('QT_SCALE_FACTOR', '1')
        folder.mkdir(parents=True, exist_ok=True); QTest.qWait(70)
        assert win.grabWindow().save(str(folder / (label + '.png')))
capture('documents')
press(find('openPictures'))
assert sheet.property('opened') and not maker.calls
assert not find('pictureMake').property('enabled')
prompt = find('picturePrompt'); prompt.setProperty('text', 'A glass temple at the bottom of the ocean.')
find('pictureShape').picked.emit('landscape'); QTest.qWait(30)
ctx.chat._busy = True; ctx.chat.busyChanged.emit()
assert not find('pictureMake').property('enabled')
ctx.chat._busy = False; ctx.chat.busyChanged.emit()
for mode in ['dark', 'light']:
    ctx.theme.mode = mode; invoke(sheet, 'scrollToTop'); capture(mode + '-picture-form')
press(find('pictureMake'))
assert ctx.images.busy == 'preparing' and not find('pictureMake').property('enabled')
assert prompt.property('readOnly')
invoke(sheet, 'close'); assert ctx.images.busy
finish(); invoke(sheet, 'open')
assert ctx.images.details['width'] == 768 and ctx.images.details['height'] == 512
# Inline PNG decoding is asynchronous even after the renderer has finished.
preview_status = QQmlExpression(engine.rootContext(), find('generatedPicture'), 'Number(status)')
deadline = time.monotonic() + 5
while preview_status.evaluate()[0] == 2 and time.monotonic() < deadline:
    QTest.qWait(20)
assert preview_status.evaluate()[0] == 1
assert len(maker.calls) == 1 and not sheet.property('saved')
for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    invoke(find('pictureMake'), 'forceActiveFocus')
    invoke(find('pictureSave'), 'forceActiveFocus'); capture(mode + '-picture-result')
# Exercise the save-dialog acceptance handler with a chosen temp destination.
target = Path(sys.argv[2]) / 'chosen.png'
assert not target.exists()
invoke(sheet, 'saveTo', QUrl.fromLocalFile(str(target)).toString())
assert target.read_bytes() == png and sheet.property('saved')
invoke(sheet, 'saveTo', QUrl.fromLocalFile(str(target.with_suffix('.jpg'))).toString())
assert '.png' in sheet.property('notice') and not target.with_suffix('.jpg').exists()
# A failed attempt must keep the previous preview available for saving.
maker.fail = True; press(find('pictureMake')); finish()
assert ctx.images.picture and 'unavailable' in ctx.images.note
prompt.setProperty('text', 'x' * 1001); QTest.qWait(30)
assert not find('pictureMake').property('enabled')
invoke(sheet, 'close')
# Pictures accompany the actual approval; words and both decisions stay visible.
from akira.core.tools import Asking
answers = []
question = Asking('Save the image to chosen.png. ' + 'Action details. ' * 350,
                  png, ((.1, .2, .3, .15),), kind='image/png')
worker = threading.Thread(target=lambda: answers.append(ctx.confirm.ask(question)), daemon=True)
worker.start(); deadline = time.monotonic() + 5
while not find('confirmRefuse').property('visible') and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
QTest.qWait(80)
picture = find('confirmationPicture')
assert picture.property('visible') and str(picture.property('source')).find('data:image/png') >= 0
assert win.activeFocusItem() == find('confirmRefuse')
for name in ['confirmAllow', 'confirmRefuse', 'confirmSummaryScroll']:
    item = find(name); at = item.mapToScene(item.boundingRect().topLeft())
    assert at.y() >= 0 and at.y() + item.height() <= win.height(), (name, at.y(), item.height())
mark = find('confirmationMark')
assert abs(mark.width() - mark.parentItem().width() * .3) < 1
capture('picture-confirmation')
press(find('confirmRefuse')); worker.join(2)
assert answers == [False] and not picture.property('source').toString()
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('PICTURES_UI_OK')
'''


@pytest.mark.parametrize('scale', ['1', '1.5'])
def test_make_preview_and_explicit_save(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / 'config'), QT_QPA_PLATFORM='offscreen',
               QT_QUICK_BACKEND='software', QML_DISABLE_DISK_CACHE='1', QT_SCALE_FACTOR=scale)
    env.pop('PROTEGE_CONFIG_DIR', None)
    result = subprocess.run([sys.executable, '-c', PROBE, str(REPO), str(tmp_path)],
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PICTURES_UI_OK' in result.stdout
