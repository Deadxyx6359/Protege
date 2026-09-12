"""Seeing the screen (C4): a capture, and the words on it.

**What it takes.** `screen.capture`, granted by the person and checked before
every capture by the tools that call this (see `core/tools/builtin/screen.py`).
A screenshot shows whatever is open: a message, a password being typed, a bank
balance. So every capture is in the activity log, and an agent's appears in its
trace as it happens.

**Kept in memory.** A capture is held as PNG bytes in this process. It is
written to disk only when a tool with `files.write` there saves it, after the
person says yes. The words on it are read by Windows' own text recognition,
which runs on this computer: nothing is installed for it and nothing is sent.

**For agents, words.** The local models read text, not pictures, so an agent
looking at the screen is given the text recognised on it.

Standard library and the Windows API only: GDI for the capture, zlib for the
PNG, and PowerShell's bridge to `Windows.Media.Ocr` for the words.
"""

from __future__ import annotations

import ctypes
import os
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

OCR_TIMEOUT_S = 30.0


class ScreenError(RuntimeError):
    """A capture or a reading that failed, with a reason for the person."""


@dataclass(frozen=True)
class Shot:
    png: bytes
    width: int
    height: int
    at: float


# -- capture ---------------------------------------------------------------------------------

_SRCCOPY, _CAPTUREBLT = 0x00CC0020, 0x40000000
_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN, _SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 76, 77, 78, 79


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def _gdi():
    """user32 and gdi32 with their handle types declared.

    Declared, not assumed: ctypes returns int by default, which cuts a 64-bit
    handle in half, and the capture then fails in ways that look like anything
    but that.
    """
    if sys.platform != "win32":
        raise ScreenError("Screenshots are only taken on Windows.")
    handle = ctypes.c_void_p
    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    user32.GetDC.restype, user32.GetDC.argtypes = handle, [handle]
    user32.ReleaseDC.argtypes = [handle, handle]
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    gdi32.CreateCompatibleDC.restype, gdi32.CreateCompatibleDC.argtypes = handle, [handle]
    gdi32.CreateCompatibleBitmap.restype = handle
    gdi32.CreateCompatibleBitmap.argtypes = [handle, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype, gdi32.SelectObject.argtypes = handle, [handle, handle]
    gdi32.BitBlt.argtypes = [handle, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             handle, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.GetDIBits.argtypes = [handle, handle, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, wintypes.UINT]
    gdi32.DeleteObject.argtypes = [handle]
    gdi32.DeleteDC.argtypes = [handle]
    return user32, gdi32


def png(width: int, height: int, bgra: bytes) -> bytes:
    """A PNG of \a width by \a height from top-down BGRA pixels, as GDI gives them."""
    rgb = bytearray(width * height * 3)
    view = memoryview(bgra)
    rgb[0::3], rgb[1::3], rgb[2::3] = view[2::4], view[1::4], view[0::4]
    stride = width * 3
    scan = b"".join(b"\x00" + bytes(rgb[row * stride:(row + 1) * stride]) for row in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(scan, 6)) + chunk(b"IEND", b""))


def grab() -> Shot:
    """The whole screen, every monitor, as it is now.

    No permission check here: this is what the tools call after the registry
    has checked `screen.capture`. Nothing else should call it.
    """
    user32, gdi32 = _gdi()
    x, y, width, height = (user32.GetSystemMetrics(i) for i in (
        _SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN, _SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN))
    if width <= 0 or height <= 0:
        raise ScreenError("There is no screen to capture.")
    screen = user32.GetDC(None)
    if not screen:
        raise ScreenError("The screen could not be read.")
    memory = bitmap = previous = None
    try:
        memory = gdi32.CreateCompatibleDC(screen)
        bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
        if not memory or not bitmap:
            raise ScreenError("There was not enough memory to capture the screen.")
        previous = gdi32.SelectObject(memory, bitmap)
        if not gdi32.BitBlt(memory, 0, 0, width, height, screen, x, y, _SRCCOPY | _CAPTUREBLT):
            raise ScreenError("The screen could not be copied. It may be locked.")
        header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, -height, 1, 32, 0,
                                   0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        if gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0) != height:
            raise ScreenError("The screen could not be copied.")
    finally:
        if previous:
            gdi32.SelectObject(memory, previous)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory:
            gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)
    return Shot(png(width, height, pixels.raw), width, height, time.time())


# -- words -----------------------------------------------------------------------------------

#: PowerShell's bridge to Windows' OCR. The picture's path arrives in an
#: environment variable, never inside the script, so nothing can be quoted into it.
_OCR = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($operation, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $null = $task.Wait(-1)
    $task.Result
}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:AKIRA_OCR_IMAGE)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) { throw 'Windows has no text recognition language installed.' }
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    foreach ($line in $result.Lines) { [Console]::WriteLine($line.Text) }
} finally { $stream.Dispose() }
"""

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def read_text(picture: bytes) -> str:
    """The words Windows recognises in \a picture, a PNG, one line of text per line.

    The picture goes to a private temporary folder for the moment it takes, and
    is deleted whatever happens.
    """
    if sys.platform != "win32":
        raise ScreenError("Reading text from a picture needs Windows.")
    folder = tempfile.mkdtemp(prefix="akira-ocr-")
    path = Path(folder) / "screen.png"
    try:
        path.write_bytes(picture)
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _OCR],
            env={**os.environ, "AKIRA_OCR_IMAGE": str(path)}, capture_output=True,
            stdin=subprocess.DEVNULL, timeout=OCR_TIMEOUT_S, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise ScreenError("Reading the text took too long.") from None
    except OSError as exc:
        raise ScreenError(f"Windows' text recognition could not be started: {exc}") from None
    finally:
        path.unlink(missing_ok=True)
        os.rmdir(folder)
    if done.returncode != 0:
        lines = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ScreenError(f"The text could not be read: {lines[-1] if lines else 'no reason given'}")
    return done.stdout.decode("utf-8", "replace").replace("\r\n", "\n").strip()
