"""One Akira at a time.

Launching Akira while it is already running, with its window closed to the icon
by the clock, brings that one back rather than starting a second, which would
load a second model. Done with a named mutex and a named event in this Windows
session (`Local\\`), nothing on the network: the first Akira holds the mutex and
waits on the event; a second finds the mutex taken, sets the event, and leaves.
Anyone able to set the event can do no more than bring the window forward.

The names carry a digest of the configuration folder, so an Akira run against
another configuration (a test, a tool) is a different Akira.
"""

from __future__ import annotations

import ctypes
import hashlib
import sys
import threading
from ctypes import wintypes
from typing import Callable

from akira.core.config import config_dir

_ALREADY_EXISTS = 183
_INFINITE = 0xFFFFFFFF
_SIGNALLED = 0
_ANY_PROCESS = 0xFFFFFFFF  # ASFW_ANY

_kernel32 = None


def _windows():
    global _kernel32
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                   wintypes.LPCWSTR]
        k.CreateEventW.restype = wintypes.HANDLE
        k.SetEvent.argtypes = [wintypes.HANDLE]
        k.SetEvent.restype = wintypes.BOOL
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        _kernel32 = k
    return _kernel32


def default_name() -> str:
    folder = str(config_dir()).replace("/", "\\").rstrip("\\").lower()
    return "Akira.Desktop." + hashlib.sha256(folder.encode("utf-8")).hexdigest()[:16]


class Instance:
    """This Akira's claim to be the one running."""

    def __init__(self, name: str | None = None) -> None:
        self._name = name or default_name()
        self._mutex = None
        self._event = None
        self._listener: threading.Thread | None = None
        self._stopping = False
        self.first = True
        if sys.platform != "win32":
            return
        k = _windows()
        # A new mutex need not clear the last error, so nothing stale is read as "taken".
        ctypes.set_last_error(0)
        self._mutex = k.CreateMutexW(None, False, "Local\\" + self._name)
        self.first = not (self._mutex and ctypes.get_last_error() == _ALREADY_EXISTS)
        self._event = k.CreateEventW(None, False, False, "Local\\" + self._name + ".show")

    def call_first(self) -> bool:
        """From a second Akira: ask the first to show its window. Whether it was asked."""
        if self.first or not self._event:
            return False
        # The person just launched this one, so it may hand the foreground on;
        # without that the first Akira's window would only flash on the taskbar.
        try:
            ctypes.WinDLL("user32").AllowSetForegroundWindow(wintypes.DWORD(_ANY_PROCESS))
        except (OSError, AttributeError):
            pass
        return bool(_windows().SetEvent(self._event))

    def listen(self, on_called: Callable[[], None]) -> None:
        """Call \a on_called, on a worker thread, each time another Akira asks."""
        if not self.first or not self._event or self._listener is not None:
            return

        def wait() -> None:
            k = _windows()
            while not self._stopping:
                if k.WaitForSingleObject(self._event, _INFINITE) != _SIGNALLED:
                    return
                if not self._stopping:
                    on_called()

        self._listener = threading.Thread(target=wait, name="akira-instance", daemon=True)
        self._listener.start()

    def release(self) -> None:
        """Give up the claim, for quitting: Akira launched again from here on is a new one."""
        if sys.platform != "win32":
            return
        k = _windows()
        self._stopping = True
        if self._listener is not None and self._event:
            k.SetEvent(self._event)  # only this Akira waits on it: wakes its own listener
            self._listener.join(2.0)
        for handle in (self._event, self._mutex):
            if handle:
                k.CloseHandle(handle)
        self._event = self._mutex = None
