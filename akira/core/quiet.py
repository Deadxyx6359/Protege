"""Keeping out of the way of what the person is doing.

While Akira's window is closed it keeps running, for reminders, watches and
scheduled jobs, but not at the cost of a game or anything else the person has
in front of them. Two things here:

- `background_priority`: Windows' background mode for this process. Its
  processor time, disk access and memory all come after every other program's,
  and on a processor with efficiency cores it is kept on those (EcoQoS).
- `CardWatch.busy`: whether something else has the graphics card, so that a job
  needing a model waits rather than loading one beside a game. Two signs, both
  read from this computer and sent nowhere: Windows' own "busy" state, which is
  a full-screen program in front (a game, a film, a presentation; the state
  Windows holds notifications back for), and, with an NVIDIA card, how much of
  its memory something else is using, from the driver's own library (NVML).
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from typing import Any, Callable

# -- background mode ------------------------------------------------------------------------

_BACKGROUND_BEGIN = 0x00100000
_BACKGROUND_END = 0x00200000
_POWER_THROTTLING = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
_THROTTLE_EXECUTION_SPEED = 0x1

_kernel32 = None
_in_background = False


class _Throttling(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG),
                ("StateMask", wintypes.ULONG)]


def _windows():
    global _kernel32
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.SetPriorityClass.restype = wintypes.BOOL
        k.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                            wintypes.DWORD]
        k.SetProcessInformation.restype = wintypes.BOOL
        _kernel32 = k
    return _kernel32


def background_priority(on: bool) -> bool:
    """Put this process behind every other program, or back level with them.

    Returns whether anything changed. Off Windows, nothing does.
    """
    global _in_background
    if sys.platform != "win32" or on == _in_background:
        return False
    k = _windows()
    me = k.GetCurrentProcess()
    changed = bool(k.SetPriorityClass(me, _BACKGROUND_BEGIN if on else _BACKGROUND_END))
    if changed:
        _in_background = on
    # Efficiency, on top: asked for while in the background, and left to Windows
    # to decide again afterwards. Windows 10 before 1709 has no such setting.
    state = _Throttling(1, _THROTTLE_EXECUTION_SPEED if on else 0,
                        _THROTTLE_EXECUTION_SPEED if on else 0)
    k.SetProcessInformation(me, _POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state))
    return changed


def in_background() -> bool:
    return _in_background


# -- the graphics card ----------------------------------------------------------------------

#: What Windows' notification state says about the screen, for the states that
#: mean something has it to itself.
_FULL_SCREEN = {
    2: "a full-screen program is open",
    3: "a game is running full screen",
    4: "a presentation is being shown",
}

#: Memory on the card in use by others, above which something else has it.
#: Idle, with nothing loaded, this card shows 150 MB; a game takes gigabytes.
OTHERS_BYTES = 1024**3

#: Load on the card, in percent, above which something else is using it. Read
#: only when the driver can say: an NVIDIA card asleep cannot.
OTHERS_PERCENT = 25

#: How long an answer is trusted. Asking the driver wakes a sleeping card, so a
#: job waiting for it is not allowed to ask every half minute.
RECHECK_S = 300.0


def full_screen() -> str:
    """Why a full-screen program has the screen, or ""."""
    if sys.platform != "win32":
        return ""
    state = ctypes.c_int(0)
    try:
        if ctypes.WinDLL("shell32").SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return ""
    except (OSError, AttributeError):
        return ""
    return _FULL_SCREEN.get(state.value, "")


class _Use(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Memory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong),
                ("used", ctypes.c_ulonglong)]


class Nvidia:
    """The first NVIDIA card, through the driver's NVML. `None` everywhere when
    there is no such card or driver."""

    def __init__(self, library: Any = None) -> None:
        self._library = library
        self._device: Any = None
        self._tried = False

    def _open(self) -> bool:
        if self._tried:
            return self._device is not None
        self._tried = True
        try:
            lib = self._library if self._library is not None else ctypes.WinDLL("nvml.dll")
            if lib.nvmlInit_v2() != 0:
                return False
            device = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(device)) != 0:
                return False
        except (OSError, AttributeError):
            return False
        self._library, self._device = lib, device
        return True

    def used_bytes(self) -> int | None:
        if not self._open():
            return None
        memory = _Memory()
        if self._library.nvmlDeviceGetMemoryInfo(self._device, ctypes.byref(memory)) != 0:
            return None
        return int(memory.used)

    def load_percent(self) -> int | None:
        if not self._open():
            return None
        use = _Use()
        if self._library.nvmlDeviceGetUtilizationRates(self._device, ctypes.byref(use)) != 0:
            return None
        return int(use.gpu)


class CardWatch:
    """Whether something other than Akira is using the screen or the graphics card.

    Ask only while Akira has nothing of its own on the card, as while its window
    is closed: Akira's own model would count as someone else's.
    """

    def __init__(self, *, screen: Callable[[], str] = full_screen, card: Nvidia | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._screen = screen
        self._card = card if card is not None else Nvidia()
        self._clock = clock
        self._lock = threading.Lock()
        self._answer = ""
        self._asked = -RECHECK_S

    def busy(self) -> str:
        """Why the card should be left alone, in a few words, or ""."""
        # The screen first: Windows answers at once and wakes nothing.
        reason = self._screen()
        if reason:
            return reason
        with self._lock:
            now = self._clock()
            if now - self._asked >= RECHECK_S:
                self._answer, self._asked = self._ask_card(), now
            return self._answer

    def forget(self) -> None:
        """Ask the card afresh next time, as when Akira has just let go of it."""
        with self._lock:
            self._asked = -RECHECK_S

    def _ask_card(self) -> str:
        used = self._card.used_bytes()
        if used is not None and used >= OTHERS_BYTES:
            return f"another program is using {used / 1024**3:.1f} GB of the graphics card"
        load = self._card.load_percent()
        if load is not None and load >= OTHERS_PERCENT:
            return f"another program is using the graphics card ({load}%)"
        return ""
