"""A reply can be read and followed, and a sheet stays open while it is used.

Two faults the person found. A reply's words could not be selected and its
links did nothing, so an address had to be retyped by hand. And a sheet closed
itself the moment any control inside it was tapped: the scrim's TapHandler took
a passive grab that a press on a control never took away, so switching a
Settings section both switched it and dismissed the sheet.

Opening a link still asks. The address in a reply is the model's, and the words
of a link need not match where it goes, so `LinkPrompt` shows the whole address
and opens nothing without a yes.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtQml")

from akira.ui.engine import QML_ROOT  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

#: Every element that shows a message, and what it must be.
READABLE = [
    ("Akira/MessageBody.qml", "the reply"),
    ("Akira/ChatView.qml", "what you said"),
]


def _blocks(source: str, opener: str):
    """The text written directly inside each `opener` element."""
    for match in re.finditer(r"\b" + opener + r"\s*\{", source):
        depth, i, start = 1, match.end(), match.end()
        while i < len(source) and depth:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            i += 1
        yield source[start:i]


@pytest.mark.parametrize("name, what", READABLE)
def test_a_message_can_be_selected_and_never_edited(name, what):
    source = (QML_ROOT / name).read_text(encoding="utf-8")
    shown = [block for block in _blocks(source, "TextEdit")]
    assert shown, f"{what} is not a TextEdit, so it cannot be selected"
    for block in shown:
        assert "readOnly: true" in block, f"{what} is editable"
        assert "selectByMouse: true" in block, f"{what} cannot be selected"
        assert "textFormat:" in block, f"{what} does not say how it is shown"


def test_a_link_in_a_reply_is_handed_on_rather_than_opened():
    body = (QML_ROOT / "Akira/MessageBody.qml").read_text(encoding="utf-8")
    assert "signal linkActivated(string url)" in body
    assert "Qt.openUrlExternally" not in body, "a reply must not open an address itself"

    everywhere = [path for path in sorted(QML_ROOT.rglob("*.qml"))
                  if "MessageBody {" in path.read_text(encoding="utf-8")]
    assert everywhere, "no view shows a reply"
    for path in everywhere:
        for block in _blocks(path.read_text(encoding="utf-8"), "MessageBody"):
            assert "Links.ask" in block, (
                f"{path.relative_to(QML_ROOT).as_posix()} shows a reply whose links go nowhere")


def test_only_the_prompt_opens_an_address():
    opens = [path.relative_to(QML_ROOT).as_posix() for path in sorted(QML_ROOT.rglob("*.qml"))
             if "Qt.openUrlExternally" in path.read_text(encoding="utf-8")]
    assert opens == ["Akira/LinkPrompt.qml"], opens


PROBE = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QMetaObject, Qt, QPoint, QPointF
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context

app = QGuiApplication([]); configure_application(app)
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []
engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(900); win.setHeight(600); win.requestActivate(); QTest.qWait(50)

def run(js):
    # The window's own context, so the Akira module's singletons resolve.
    expression = QQmlExpression(QQmlEngine.contextForObject(win), win, js)
    expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    QTest.qWait(40)

def click(item, x, y):
    at = item.mapToScene(QPointF(x, y))
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(int(at.x()), int(at.y())))
    QTest.qWait(60)

# -- a sheet is not dismissed by the controls inside it ----------------------
sheet = win.findChild(QObject, 'settingsSheet')
QMetaObject.invokeMethod(sheet, 'open', Qt.DirectConnection); QTest.qWait(80)
assert sheet.property('opened')
tabs = win.findChild(QObject, 'settingsSections')
click(tabs, tabs.width() * 0.5, tabs.height() / 2)
assert sheet.property('section') == 'appearance', sheet.property('section')
assert sheet.property('opened'), 'a tap on a control in the sheet dismissed it'
modes = win.findChild(QObject, 'appearanceModes')
click(modes, modes.width() * 0.5, modes.height() / 2)
assert sheet.property('opened'), 'changing a setting dismissed the sheet'

# -- and a press that misses it still means "close" --------------------------
QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(20, 20)); QTest.qWait(80)
assert not sheet.property('opened'), 'a press outside the sheet no longer closes it'

# -- a link is shown whole and opened only if it is a web address ------------
prompt = win.findChild(QObject, 'linkPrompt')
assert not prompt.property('visible')
run('Links.ask("https://example.com/a?b=c")')
assert prompt.property('address') == 'https://example.com/a?b=c', prompt.property('address')
assert prompt.property('openable') and prompt.property('visible')
assert win.findChild(QObject, 'linkOpen').property('visible')
assert prompt.property('address') in str(win.findChild(QObject, 'linkAddress').property('text'))

win.findChild(QObject, 'linkRefuse').clicked.emit(); QTest.qWait(40)
assert prompt.property('address') == '' and not prompt.property('visible')

for refused in ['javascript:alert(1)', 'file:///C:/Windows/System32/cmd.exe',
                'https://example.com/ and more']:
    run('Links.ask("%s")' % refused)
    assert prompt.property('address') == refused, prompt.property('address')
    assert not prompt.property('openable'), refused
    assert not win.findChild(QObject, 'linkOpen').property('visible'), refused
    QMetaObject.invokeMethod(prompt, 'dismiss', Qt.DirectConnection); QTest.qWait(30)

run('Links.ask("   ")')
assert not prompt.property('visible'), 'an empty address asked about nothing'

assert not warnings, '\n'.join(warnings)
ctx.close(); win.close()
print('LINKS_AND_SHEETS_OK')
'''


def test_sheets_stay_open_and_links_ask_first(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"), QT_QPA_PLATFORM="offscreen",
               QT_QUICK_BACKEND="software", QML_DISABLE_DISK_CACHE="1")
    env.pop("PROTEGE_CONFIG_DIR", None)
    env.pop("QT_SCALE_FACTOR", None)
    run = subprocess.run([sys.executable, "-c", PROBE, str(REPO)], env=env,
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "LINKS_AND_SHEETS_OK" in run.stdout
