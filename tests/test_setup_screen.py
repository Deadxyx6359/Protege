"""The first screen: the permissions most people want first, chosen at once."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from akira.core.permissions import AuditLog, Policy
from akira.core.permissions import starter

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


def test_each_choice_grants_what_it_says_and_no_more(tmp_path):
    plan = starter.planned([{"id": "web"}, {"id": "weather"}, {"id": "notices"},
                            {"id": "documents", "folder": str(tmp_path)}])
    policy = Policy()
    starter.apply(policy, plan)
    assert policy.allows("web.search") and policy.allows("net.http", "en.wikipedia.org")
    assert policy.allows("net.http", "api.open-meteo.com")
    assert policy.allows("net.http", "geocoding-api.open-meteo.com")
    assert not policy.allows("net.http", "example.com")
    assert policy.allows("location.read") and policy.allows("notify.send")
    assert policy.allows("files.read", str(tmp_path / "a.txt"))
    assert policy.allows("docs.read", str(tmp_path / "a.docx"))
    assert policy.granted("vault.read") is None and policy.granted("files.write") is None


def test_it_adds_to_what_is_held_and_keeps_its_end_date():
    policy = Policy()
    policy.grant("net.http", ("bbc.co.uk",), expires=4_102_444_800.0)
    starter.apply(policy, starter.planned([{"id": "web"}]))
    grant = policy.granted("net.http")
    assert grant.scopes == ("bbc.co.uk", "en.wikipedia.org") and grant.expires == 4_102_444_800.0


def test_a_folder_choice_needs_its_folder():
    with pytest.raises(ValueError, match="Pick a folder"):
        starter.planned([{"id": "notes"}])
    with pytest.raises(ValueError):
        starter.planned([{"id": "everything"}])


def test_the_bridge_grants_all_or_nothing_and_records_it(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from akira.ui.bridge.permissions import PermissionsBridge
    monkeypatch.setattr(Policy, "path", staticmethod(lambda: tmp_path / "permissions.json"))
    audit = AuditLog(tmp_path / "audit.jsonl")
    bridge = PermissionsBridge(Policy(), audit)
    assert not bridge.setupOffered
    assert "Pick a folder" in bridge.applyStarter([{"id": "web"}, {"id": "notes"}])
    assert bridge.grants == [], "half of it was granted"
    assert bridge.applyStarter([{"id": "web"}, {"id": "notices"}]) == ""
    assert {g["id"] for g in bridge.grants} == {"web.search", "net.http", "notify.send"}
    assert bridge.setupOffered and Policy.load().allows("notify.send")
    notes = [e.detail.get("note") for e in audit.read(limit=50) if e.kind == "grant"]
    assert "chosen on the first screen" in notes


def test_not_now_is_remembered(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from akira.ui.bridge.permissions import PermissionsBridge
    monkeypatch.setattr(Policy, "path", staticmethod(lambda: tmp_path / "permissions.json"))
    bridge = PermissionsBridge(Policy(), AuditLog(tmp_path / "audit.jsonl"))
    bridge.markSetupOffered()
    assert PermissionsBridge(Policy(), AuditLog(tmp_path / "audit.jsonl")).setupOffered


PROBE = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QMetaObject, QObject, QPointF, Q_ARG, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from akira.ui.engine import build_engine, configure_application, load
from akira.ui.shell import build_context
app = QGuiApplication([]); configure_application(app)
ctx = build_context(persist=False); ctx.theme.reduceMotion = True
engine, _ = build_engine(theme=ctx.theme, context=ctx.as_context())
warnings = []; engine.warnings.connect(lambda items: warnings.extend(str(i) for i in items))
win = load(engine, Path(sys.argv[1]) / 'akira/ui/qml/Main.qml')
win.setWidth(1100); win.setHeight(700); QTest.qWait(80)
def walk(it, name):
    for child in it.childItems():
        if child.objectName() == name and child.isVisible():
            return child
        found = walk(child, name)
        if found is not None:
            return found
    return None
def click(name):
    it = walk(win.contentItem(), name); assert it is not None, name
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier,
                     it.mapToScene(QPointF(it.width() / 2, it.height() / 2)).toPoint()); QTest.qWait(60)
sheet = win.findChild(QObject, 'setupSheet')
assert not sheet.property('opened'), 'opened by itself outside the application'
QMetaObject.invokeMethod(win, 'openSetup'); QTest.qWait(80)
assert sheet.property('opened')
click('setupChoice_weather')                 # off
folder = sys.argv[2]
QMetaObject.invokeMethod(sheet, 'set', Q_ARG('QVariant', 'documents'), Q_ARG('QVariant', True),
                         Q_ARG('QVariant', folder)); QTest.qWait(40)
click('setupAllow')
assert not sheet.property('opened') and sheet.property('notice') == ''
policy = ctx.permissions.policy
assert policy.allows('web.search') and policy.allows('notify.send')
assert policy.granted('location.read') is None, 'weather was granted though it was turned off'
assert policy.allows('files.read', folder)
# From Settings, again.
settings = win.findChild(QObject, 'settingsSheet')
QMetaObject.invokeMethod(settings, 'open'); QTest.qWait(80)
click('quickSetup')
assert sheet.property('opened') and not settings.property('opened')
click('setupLater')
assert not sheet.property('opened')
assert not warnings, '\n'.join(warnings)
ctx.close(); win.close(); print('SETUP_UI_OK')
'''


def test_the_setup_screen_in_the_window(tmp_path):
    env = dict(os.environ, AKIRA_CONFIG_DIR=str(tmp_path / "config"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QML_DISABLE_DISK_CACHE="1")
    env.pop("PROTEGE_CONFIG_DIR", None)
    folder = tmp_path / "Documents"
    folder.mkdir()
    result = subprocess.run([sys.executable, "-c", PROBE, str(REPO), str(folder)],
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SETUP_UI_OK" in result.stdout
