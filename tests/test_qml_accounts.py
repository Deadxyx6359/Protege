"""Provider navigation and secret-field lifecycle in the real Accounts sheet."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("PySide6.QtQml")
REPO = Path(__file__).resolve().parent.parent

PROBE = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Qt, QPoint, QPointF
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
for name in ['SegUIVar.ttf', 'segoeui.ttf', 'seguisym.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []
engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.requestActivate(); QTest.qWait(70)
sheet = win.findChild(QObject, 'accountsSheet')
def invoke(name):
    QMetaObject.invokeMethod(sheet, name, Qt.DirectConnection); QTest.qWait(60)
def run(js):
    expression = QQmlExpression(QQmlEngine.contextForObject(sheet), sheet, js)
    result = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    QTest.qWait(40)
    return result
def click(item, fraction):
    point = item.mapToScene(QPointF(item.width() * fraction, item.height()/2))
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
    QTest.qWait(60)
def enum_value(item, name):
    expression = QQmlExpression(QQmlEngine.contextForObject(item), item, 'Number(' + name + ')')
    value, _ = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    return value
invoke('open')
tabs = win.findChild(QObject, 'accountSections')
click(tabs, .5)
assert sheet.property('section') == 'canvas' and sheet.property('opened')
assert win.findChild(QObject, 'canvasConnection').property('visible')
assert not win.findChild(QObject, 'googleConnection').property('visible')
# Arrow keys use the actual segmented-control focus, and do not dismiss the sheet.
QTest.keyClick(win, Qt.Key_Right); QTest.qWait(50)
assert sheet.property('section') == 'banks' and sheet.property('opened')
assert win.findChild(QObject, 'bankConnection').property('visible')
# Callback from another provider stays labelled and visible in the active tab.
ctx.accounts.canvasFinished.emit(False, '<b>Canvas refused the token</b>')
QTest.qWait(50)
feedback = win.findChild(QObject, 'accountFeedback')
assert str(feedback.property('text')) == 'Canvas · <b>Canvas refused the token</b>'
assert feedback.property('visible') and enum_value(feedback, 'textFormat') == 0
assert sheet.property('section') == 'banks'
# Real password inputs mask text. Closing erases both drafts, with no connection.
sheet.setProperty('canvasToken', 'fixture-secret-canvas')
sheet.setProperty('bankToken', 'fixture-secret-bank')
for name in ['canvasToken', 'bankToken']:
    field = win.findChild(QObject, name)
    inputs = [child for child in field.findChildren(QObject) if child.metaObject().indexOfProperty('echoMode') >= 0]
    assert len(inputs) == 1 and enum_value(inputs[0], 'echoMode') == 2
invoke('close')
assert sheet.property('canvasToken') == '' and sheet.property('bankToken') == ''
assert not ctx.accounts.busy and not ctx.accounts.bankConnecting and not ctx.accounts.canvasConnecting
invoke('open')
sheet.setProperty('notice', '')
# Inspect theme/size variants, saved locally only when requested by the harness.
out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
for mode in ['dark', 'light']:
    ctx.theme.mode = mode
    for width, height in [(900, 600), (1440, 900)]:
        win.setWidth(width); win.setHeight(height)
        for section in ['google', 'canvas', 'banks']:
            sheet.setProperty('section', section); QTest.qWait(80)
            assert sheet.property('opened')
            assert tabs.mapToScene(QPointF(0, 0)).y() >= 0
            assert win.grabWindow().save(str(out / f'{mode}-{width}-{section}.png'))
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close()
print('ACCOUNTS_UI_OK')
'''


@pytest.mark.parametrize("scale", ["1", "1.5"])
def test_accounts_navigation_and_token_lifecycle(tmp_path, scale):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1", QT_SCALE_FACTOR=scale)
    env.pop("PROTEGE_CONFIG_DIR", None)
    output = Path(os.environ.get("AKIRA_ACCOUNT_SHOTS", str(tmp_path / "shots"))) / scale
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO), str(output)],
                            env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ACCOUNTS_UI_OK" in result.stdout
