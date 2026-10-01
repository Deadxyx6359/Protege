"""Akira's own programs end when Akira does.

Akira starts other programs: training in its own Python, the picture maker
(`sd-cli`), the browser it reads pages with and that browser's driver, a
skill's sandbox, a project's tests, the helpers the phone and the screen use.
Each is started through `subprocess`, and once `tie_children` has run each is
put in a Windows job object made to end everything in it when its last handle
closes. Akira holds the only handle, so when Akira's process ends, however it
ends (Quit, a crash, Task Manager), Windows ends the rest. A program one of
them starts joins the same job by itself.

Programs started *for the person* are not tied, and outlive Akira as they
should: VS Code opened on a file (started detached, which is what marks it as
theirs) and a page opened in their own browser (opened by Windows through the
shell, not through `subprocess`).

Quitting also ends the process itself on a deadline (`exit_within`), so a
thread stuck waiting cannot keep an Akira nobody can see alive.
"""

from __future__ import annotations

import ctypes
import functools
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes

#: The `creationflags` bit that marks a program as the person's, not Akira's.
DETACHED_PROCESS = 0x00000008

_KILL_ON_JOB_CLOSE = 0x00002000
_EXTENDED_LIMIT_INFORMATION = 9

_lock = threading.Lock()
_job: int | None = None
_kernel32 = None
_original_init = None


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _windows():
    """kernel32 with the signatures used here. A private instance, so the
    argument types set on it reach nobody else's calls."""
    global _kernel32
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                              wintypes.DWORD]
        k.SetInformationJobObject.restype = wintypes.BOOL
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.TerminateJobObject.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        _kernel32 = k
    return _kernel32


def tie_children() -> bool:
    """From now on, tie every program started through `subprocess` to this process.

    For the application alone: tests and tools leave `subprocess` as it is.
    Once per process; later calls do nothing. Returns whether programs are tied,
    which is never off Windows.
    """
    global _job, _original_init
    if sys.platform != "win32":
        return False
    with _lock:
        if _job is not None:
            return True
        k = _windows()
        job = k.CreateJobObjectW(None, None)
        if not job:
            return False
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(job, _EXTENDED_LIMIT_INFORMATION,
                                         ctypes.byref(limits), ctypes.sizeof(limits)):
            k.CloseHandle(job)
            return False
        _job = job

        original = subprocess.Popen.__init__

        @functools.wraps(original)
        def __init__(self, *args, **kwargs):
            original(self, *args, **kwargs)
            if not int(kwargs.get("creationflags", 0) or 0) & DETACHED_PROCESS:
                adopt(self)

        _original_init = original
        subprocess.Popen.__init__ = __init__
    return True


def adopt(process: subprocess.Popen) -> bool:
    """Tie one program already started. Whether it was: not before `tie_children`,
    nor once it has ended."""
    job, handle = _job, getattr(process, "_handle", None)
    if job is None or handle is None:
        return False
    return bool(_windows().AssignProcessToJobObject(job, int(handle)))


def end_children() -> None:
    """End every tied program still running, now. For quitting, once everything
    has been asked to stop properly: this is what catches whatever did not."""
    job = _job
    if job is not None:
        _windows().TerminateJobObject(job, 1)


def exit_within(seconds: float, code: int = 0) -> threading.Thread:
    """End this process after \a seconds unless it has ended by then.

    Started when quitting begins: closing waits on threads, and one stuck in a
    call that never returns would otherwise keep the process, and the gigabytes
    it holds, alive with no window. Ending it ends what is tied to it too.
    """
    def last_resort() -> None:
        time.sleep(seconds)
        os._exit(code)

    thread = threading.Thread(target=last_resort, name="akira-exit", daemon=True)
    thread.start()
    return thread


def leave(code: int) -> None:
    """End this process now, everything having been saved and closed.

    Python's own teardown is skipped: it would wait on every thread still
    running, and unload native libraries (llama.cpp, Whisper, the card's
    runtime) in an order nobody chose, which is where a closing process hangs
    or crashes. Everything worth keeping was written before this is called.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(code)
