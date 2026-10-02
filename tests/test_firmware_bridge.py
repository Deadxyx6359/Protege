"""The `Firmware` bridge behind Settings' Firmware page: ST's tools found or not, and
boards looked for off the UI thread, only with reading boards allowed, and recorded.

The real programmer is never run here: `boards.probes` and `boards.ports` are fakes.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from akira.core.firmware import boards  # noqa: E402
from akira.core.permissions import AuditLog, Policy  # noqa: E402
from akira.ui.bridge import firmware as firmware_bridge  # noqa: E402
from akira.ui.bridge.firmware import FirmwareBridge  # noqa: E402


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return predicate()


@pytest.fixture
def plugged_in(monkeypatch):
    """A Nucleo's ST-LINK and its virtual COM port, as the programmer would list them."""
    looked = []

    def probes():
        looked.append("probes")
        return [boards.Probe("0670FF3638", "NUCLEO-F411RE", "V2J45M31")]

    monkeypatch.setattr(firmware_bridge.boards, "probes", probes)
    monkeypatch.setattr(firmware_bridge.boards, "ports",
                        lambda: [boards.Port("COM6", "STMicroelectronics STLink Virtual COM Port")])
    monkeypatch.setattr(firmware_bridge.boards, "programmer",
                        lambda: Path("C:/ST/STM32_Programmer_CLI.exe"))
    return looked


def test_the_tools_are_reported_as_found_or_not(app, tmp_path, monkeypatch):
    monkeypatch.setattr(firmware_bridge.boards, "programmer", lambda: None)
    monkeypatch.setattr(firmware_bridge.cubemx, "installed", lambda: tmp_path / "STM32CubeMX")
    bridge = FirmwareBridge(policy=Policy, audit=AuditLog(tmp_path / "audit.jsonl"))
    assert bridge.programmer == ""
    assert bridge.cubemx == str(tmp_path / "STM32CubeMX")


def test_looking_for_boards_needs_reading_them_allowed(app, tmp_path, plugged_in):
    audit = AuditLog(tmp_path / "audit.jsonl")
    bridge = FirmwareBridge(policy=Policy, audit=audit)
    assert bridge.scan() == "Allow reading connected boards first."
    assert not bridge.scanning and not bridge.scanned and plugged_in == []
    refused = audit.read()[-1]
    assert refused.action == "list_boards" and not refused.allowed


def test_boards_and_ports_are_listed_off_the_ui_thread(app, tmp_path, plugged_in):
    live = Policy()
    live.grant("device.read")
    audit = AuditLog(tmp_path / "audit.jsonl")
    bridge = FirmwareBridge(policy=lambda: live, audit=audit)
    assert bridge.scan() == ""
    assert bridge.scanning
    assert bridge.scan() == "Already looking."
    assert pump_until(app, lambda: not bridge.scanning), "the look never came back"
    assert bridge.scanned and bridge.error == ""
    assert bridge.boards == [{"serial": "0670FF3638", "board": "NUCLEO-F411RE",
                              "firmware": "V2J45M31"}]
    assert bridge.ports == [{"name": "COM6",
                             "description": "STMicroelectronics STLink Virtual COM Port"}]
    assert audit.read()[-1].allowed


def test_a_failed_look_says_why_and_keeps_what_was_found(app, tmp_path, plugged_in, monkeypatch):
    def broken():
        raise boards.BoardError("No ST-LINK is connected.")

    monkeypatch.setattr(firmware_bridge.boards, "probes", broken)
    live = Policy()
    live.grant("device.read")
    bridge = FirmwareBridge(policy=lambda: live, audit=AuditLog(tmp_path / "audit.jsonl"))
    assert bridge.scan() == ""
    assert pump_until(app, lambda: not bridge.scanning)
    assert bridge.error == "No ST-LINK is connected."
    assert bridge.boards == [] and [p["name"] for p in bridge.ports] == ["COM6"]
