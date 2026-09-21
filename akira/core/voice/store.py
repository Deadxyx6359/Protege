"""The voice a person chose, how fast it speaks, and whether answers are read aloud.

`voice.json` in the configuration folder. Nothing about what was said or heard
is kept here or anywhere else.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from akira.core import files
from akira.core.config import config_dir
from akira.core.voice.speak import BY_ID, DEFAULT_VOICE, FASTEST, SLOWEST


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    voice: str = DEFAULT_VOICE
    speed: float = 1.0
    read_aloud: bool = False
    """Off until the person turns it on: Akira does not start talking unasked."""


def checked(voice: str, speed: float, read_aloud: bool) -> VoiceSettings:
    """Settings that can be used: an unknown voice is the default, the speed in range."""
    try:
        pace = min(FASTEST, max(SLOWEST, round(float(speed), 2)))
    except (TypeError, ValueError):
        pace = 1.0
    return VoiceSettings(voice if voice in BY_ID else DEFAULT_VOICE, pace, bool(read_aloud))


class VoiceStore:
    """`voice.json` in the configuration folder."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_dir() / "voice.json"

    def load(self) -> VoiceSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return checked(str(raw.get("voice") or ""), raw.get("speed", 1.0),
                           raw.get("read_aloud") is True)
        except (OSError, ValueError, AttributeError, TypeError):
            return VoiceSettings()

    def save(self, settings: VoiceSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"voice": settings.voice, "speed": settings.speed,
                           "read_aloud": settings.read_aloud}, stream)
            files.replace(temporary, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
