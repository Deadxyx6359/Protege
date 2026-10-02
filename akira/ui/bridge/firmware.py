"""Settings' Firmware page — the `Firmware` bridge.

Which of ST's tools are on this computer (STM32CubeProgrammer's command line,
STM32CubeMX, and pyserial for serial ports), and, when the person asks, which
boards and serial ports are plugged in. Looking for boards runs ST's programmer,
so it happens off the UI thread, and only with "Read connected boards" allowed,
like any other reading of a board. Nothing is ever written to a board from here.
"""

from __future__ import annotations

import importlib.util
import threading
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from akira.core.firmware import boards, cubemx
from akira.core.permissions import AuditLog, Policy

#: Who the activity log records as looking for boards.
ACTOR = "person"
#: The capability looking for boards needs.
CAPABILITY = "device.read"


class FirmwareBridge(QObject):
    """What firmware work has on this computer, and what is plugged into it."""

    toolsChanged = Signal()
    scanChanged = Signal()

    #: Private: carries a finished look from the worker thread to this one.
    _done = Signal(object)

    def __init__(self, *, policy: Callable[[], Policy], audit: AuditLog,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._policy = policy
        self._audit = audit
        self._programmer = ""
        self._cubemx = ""
        self._serial = False
        self._scanning = False
        self._scanned = False
        self._boards: list[dict] = []
        self._ports: list[dict] = []
        self._error = ""
        self._done.connect(self._on_done)
        self.refresh()

    # -- the tools ------------------------------------------------------------------

    @Property(str, notify=toolsChanged)
    def programmer(self) -> str:
        """STM32_Programmer_CLI's path, or "" when it is not installed."""
        return self._programmer

    @Property(str, notify=toolsChanged)
    def cubemx(self) -> str:
        """STM32CubeMX's folder, or ""."""
        return self._cubemx

    @Property(bool, notify=toolsChanged)
    def serial(self) -> bool:
        """Whether serial ports can be read (pyserial is installed)."""
        return self._serial

    @Slot()
    def refresh(self) -> None:
        """Look again for the tools: one may have been installed since."""
        found = boards.programmer()
        self._programmer = str(found) if found else ""
        folder = cubemx.installed()
        self._cubemx = str(folder) if folder else ""
        self._serial = importlib.util.find_spec("serial") is not None
        self.toolsChanged.emit()

    # -- what is plugged in -------------------------------------------------------------

    @Property(bool, notify=scanChanged)
    def scanning(self) -> bool:
        return self._scanning

    @Property(bool, notify=scanChanged)
    def scanned(self) -> bool:
        """Whether boards have been looked for since Akira started."""
        return self._scanned

    @Property("QVariantList", notify=scanChanged)
    def boards(self) -> list:
        """The ST-LINK probes found: `serial`, `board`, `firmware`."""
        return self._boards

    @Property("QVariantList", notify=scanChanged)
    def ports(self) -> list:
        """The serial ports found: `name`, `description`."""
        return self._ports

    @Property(str, notify=scanChanged)
    def error(self) -> str:
        """What went wrong in the last look, or ""."""
        return self._error

    @Slot(result=str)
    def scan(self) -> str:
        """Look for boards and serial ports. "" once started, or why not."""
        if self._scanning:
            return "Already looking."
        decision = self._policy().allows(CAPABILITY)
        self._audit.tool_call(ACTOR, "list_boards", {}, allowed=bool(decision),
                              capability=CAPABILITY,
                              error="" if decision else decision.reason)
        if not decision:
            return "Allow reading connected boards first."
        self._scanning = True
        self._error = ""
        self.scanChanged.emit()
        threading.Thread(target=self._work, args=(bool(self._programmer), self._serial),
                         name="firmware-scan", daemon=True).start()
        return ""

    def _work(self, programmer: bool, serial: bool) -> None:
        """Worker thread. Emits a signal; touches no Qt property."""
        found: list[dict] = []
        listed: list[dict] = []
        errors: list[str] = []
        if programmer:
            try:
                found = [{"serial": p.serial, "board": p.board, "firmware": p.firmware}
                         for p in boards.probes()]
            except boards.BoardError as exc:
                errors.append(str(exc))
            except Exception as exc:  # noqa: BLE001 - a failed look must still report back
                errors.append(f"{type(exc).__name__}: {exc}")
        if serial:
            try:
                listed = [{"name": p.name, "description": p.description} for p in boards.ports()]
            except boards.BoardError as exc:
                errors.append(str(exc))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
        self._done.emit((found, listed, " ".join(errors)))

    def _on_done(self, result) -> None:
        self._boards, self._ports, self._error = result
        self._scanning = False
        self._scanned = True
        self.scanChanged.emit()
