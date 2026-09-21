"""The voice engines, imported in one place so `verify_offline.py` walks them all.

Whisper (through the low-level binding of `pywhispercpp`, never its downloader),
Kokoro (through `kokoro_onnx` and onnxruntime, on the CPU alone) and the
microphone and speakers (through `sounddevice`). The modules that use them import
this one when they first need it, so Akira starts without loading any of it.

onnxruntime's Windows build reports how it is used through Windows' own event
tracing, which hands it to Windows' diagnostics rather than opening a socket,
so no guard in Akira would see it go. It is switched off here, before any
session exists.
"""

from __future__ import annotations

import _pywhispercpp as whisper
import onnxruntime
import sounddevice
from kokoro_onnx import Kokoro

onnxruntime.disable_telemetry_events()

__all__ = ["Kokoro", "onnxruntime", "sounddevice", "whisper"]
