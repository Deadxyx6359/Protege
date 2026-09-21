"""Voice (Phase D): speech in and out, on this computer alone.

Whisper hears (`listen`) and Kokoro speaks (`speak`), both from files under
`models/`, with nothing fetched and nothing sent. What the microphone hears is
kept in memory until it is turned into words, and then dropped: no recording is
ever written to disk.

Listening needs `audio.record`, checked when the microphone opens and again
before what it heard is turned into words, so withdrawing it stops a recording
that is under way. Speaking needs `audio.play`.
"""

from __future__ import annotations

from pathlib import Path

from akira.core.config import MODELS_DIR

#: Whisper small.en, as ggml, from ggerganov/whisper.cpp.
WHISPER_MODEL = MODELS_DIR / "whisper" / "ggml-small.en.bin"

#: Kokoro 82M, quantised to int8, and its voices, from thewh1teagle/kokoro-onnx.
KOKORO_MODEL = MODELS_DIR / "voice" / "kokoro-v1.0.int8.onnx"
KOKORO_VOICES = MODELS_DIR / "voice" / "voices-v1.0.bin"


class VoiceError(Exception):
    """Why listening or speaking cannot happen, said so a person can act on it."""


def missing(*paths: Path) -> str:
    """What is not there of \a paths, as a sentence, or "" when all of it is."""
    gone = [path for path in paths if not path.is_file()]
    if not gone:
        return ""
    names = ", ".join(str(path.relative_to(MODELS_DIR.parent)) if MODELS_DIR.parent in path.parents
                      else str(path) for path in gone)
    return f"The voice files are not in place: {names}."


#: What voice runs on, as each is imported.
PACKAGES = ("_pywhispercpp", "onnxruntime", "sounddevice", "kokoro_onnx")


def unavailable() -> str:
    """Why voice cannot work on this computer at all, or "". Imports nothing."""
    import importlib.util

    absent = [name for name in PACKAGES if importlib.util.find_spec(name) is None]
    if absent:
        return (f"The voice packages are not installed ({', '.join(absent)}). "
                "They are listed in requirements.txt.")
    return missing(WHISPER_MODEL, KOKORO_MODEL, KOKORO_VOICES)


def load_engines():
    """The engines module, imported the first time voice is used.

    Kept out of Akira's start: onnxruntime and Whisper take a moment to load, and
    most sessions never speak.
    """
    try:
        from akira.core.voice import engines as loaded
    except ImportError as exc:
        raise VoiceError(f"The voice packages are not installed ({exc.name or exc}). "
                         "They are listed in requirements.txt.") from None
    return loaded
