"""Akira's own programs end when Akira does, and the person's do not.

Each case runs in a Python of its own: tying is for the whole process, and the
test runner's `subprocess` is left as it is.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows job objects")

REPO = Path(__file__).resolve().parent.parent
SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]

_SYNCHRONIZE = 0x00100000
_QUERY = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
_TERMINATE = 0x0001


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def ended_within(pid: int, seconds: float) -> bool:
    k = _kernel32()
    handle = k.OpenProcess(_SYNCHRONIZE | _QUERY, False, pid)
    if not handle:
        return True  # gone already
    try:
        return k.WaitForSingleObject(handle, int(seconds * 1000)) == 0
    finally:
        k.CloseHandle(handle)


def end(pid: int) -> None:
    k = _kernel32()
    handle = k.OpenProcess(_TERMINATE, False, pid)
    if handle:
        k.TerminateProcess(handle, 1)
        k.CloseHandle(handle)


def run(script: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", script, str(REPO)], capture_output=True,
                          text=True, timeout=timeout)


PREAMBLE = f'''
import os, subprocess, sys
sys.path.insert(0, sys.argv[1])
from akira.core import processes
SLEEPER = {SLEEPER!r}
# Given nothing of this process's to hold: a sleeper holding its output open
# would keep the test waiting for it rather than for this process.
QUIET = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
'''


def test_programs_akira_started_end_when_it_does_however_it_ends():
    # Ended abruptly, as a crash or Task Manager would: nothing gets to tidy up.
    result = run(PREAMBLE + '''
assert processes.tie_children()
child = subprocess.Popen(SLEEPER, **QUIET)
mine = subprocess.Popen(SLEEPER, creationflags=processes.DETACHED_PROCESS, **QUIET)
print(child.pid, mine.pid, flush=True)
os._exit(0)
''')
    assert result.returncode == 0, result.stderr
    tied, theirs = (int(n) for n in result.stdout.split())
    try:
        assert ended_within(tied, 10), "a program Akira started outlived it"
        # Started detached, as VS Code is for the person, it is theirs and goes on.
        assert not ended_within(theirs, 0.5)
    finally:
        end(tied)
        end(theirs)


def test_a_program_started_by_one_of_akiras_ends_with_it_too():
    result = run(PREAMBLE + '''
processes.tie_children()
inner = ("import subprocess, sys, time; print(subprocess.Popen(%r, stdin=subprocess.DEVNULL, "
         "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid, flush=True); time.sleep(120)")
outer = subprocess.Popen([sys.executable, "-c", inner % (SLEEPER,)], stdout=subprocess.PIPE,
                         stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
print(outer.stdout.readline().strip(), flush=True)
os._exit(0)
''')
    assert result.returncode == 0, result.stderr
    grandchild = int(result.stdout.split()[0])
    try:
        assert ended_within(grandchild, 10)
    finally:
        end(grandchild)


def test_quitting_ends_what_is_still_running_at_once():
    result = run(PREAMBLE + '''
import time
processes.tie_children()
child = subprocess.Popen(SLEEPER, **QUIET)
started = time.monotonic()
processes.end_children()
child.wait(10)
print(round(time.monotonic() - started, 2))
''')
    assert result.returncode == 0, result.stderr
    assert float(result.stdout) < 5


def test_without_tying_nothing_changes():
    result = run(PREAMBLE + '''
child = subprocess.Popen(SLEEPER, **QUIET)
print(child.pid, flush=True)
os._exit(0)
''')
    pid = int(result.stdout)
    try:
        assert not ended_within(pid, 0.5)
    finally:
        end(pid)


def test_a_stuck_close_cannot_keep_akira_alive():
    started = time.monotonic()
    result = run(PREAMBLE + '''
import threading, time
processes.exit_within(0.5, 7)
# A thread nobody can stop, which Python would otherwise wait on for ever.
threading.Thread(target=time.sleep, args=(600,)).start()
''', timeout=30)
    assert result.returncode == 7
    assert time.monotonic() - started < 20


def test_leaving_keeps_the_exit_code_and_what_was_printed():
    result = run(PREAMBLE + '''
print("saved", end="")
processes.leave(3)
print("never")
''')
    assert result.returncode == 3
    assert result.stdout == "saved"


def test_the_job_limits_have_windows_layout():
    from akira.core import processes

    assert ctypes.sizeof(processes._ExtendedLimits) == (144 if ctypes.sizeof(ctypes.c_void_p) == 8
                                                        else 112)
