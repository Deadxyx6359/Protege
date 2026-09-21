"""Speech in (D1): push to talk, heard by Whisper on this computer.

The microphone opens when the person asks and closes when they stop, or after
`MAX_SECONDS`. What it heard is kept in memory, turned into words by Whisper
small.en, and dropped. Nothing is written to disk and nothing leaves the
computer.

`audio.record` is checked when the microphone opens, and again before what it
heard is turned into words: withdrawing it while the microphone is open throws
the recording away unheard. Each recording is logged with its length, never its
words.

Whisper, given silence or a cough, invents things ("Thanks for watching!",
"you"). So a clip with too little speech in it is not given to Whisper at all,
and the stock phrases it invents on near-silence are dropped when they are all
it heard, along with its notes about sounds, like "[BLANK_AUDIO]" or "(music)".
"""

from __future__ import annotations

import contextlib
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from akira.core.permissions import AuditLog, Policy
from akira.core.permissions.audit import Event
from akira.core.voice import WHISPER_MODEL, VoiceError, load_engines, missing

#: What Whisper was trained on.
SAMPLE_RATE = 16_000

#: The longest a single press of the button records.
MAX_SECONDS = 120

#: Less speech than this is not worth a transcription, and is where Whisper
#: invents things.
MIN_SPEECH_SECONDS = 0.3

#: The quietest a frame can be and still count as speech, however quiet the room.
SPEECH_FLOOR = 0.006

#: A frame counts as speech when it is this many times louder than the room.
ABOVE_ROOM = 3.0

#: No room is louder than this; a clip quieter nowhere is speech throughout.
ROOM_CEILING = 0.01

#: Threads for Whisper. Four of the eight were fastest on this CPU; more fight
#: with the interface and the model.
THREADS = 4

#: Whisper's notes on sounds: [BLANK_AUDIO], (music), *coughs*.
_NOTES = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")

#: What Whisper says on near-silence, learned from subtitled video. Dropped only
#: when it is the whole of what was heard.
_INVENTED = frozenset({
    "you", "thanks for watching", "thank you for watching",
    "thanks for watching and see you next time", "please subscribe", "like and subscribe",
    "subtitles by the amara org community",
})


@dataclass(frozen=True, slots=True)
class Heard:
    """What one press of the button heard."""

    text: str
    seconds: float


# -- the sound -----------------------------------------------------------------------------------


def speech_seconds(audio: np.ndarray, rate: int = SAMPLE_RATE) -> float:
    """How much of \a audio is louder than the room it was recorded in, in seconds."""
    frame = rate * 30 // 1000
    whole = (audio.size // frame) * frame
    if whole == 0:
        return 0.0
    loudness = np.sqrt(np.mean(np.square(audio[:whole].reshape(-1, frame)), axis=1))
    # The room is the quietest tenth of the clip, unless that is speech too, as
    # when the person talked from the first moment to the last.
    room = min(float(np.percentile(loudness, 10)), ROOM_CEILING)
    speech = loudness > max(SPEECH_FLOOR, room * ABOVE_ROOM)
    return float(np.count_nonzero(speech)) * frame / rate


def resample(audio: np.ndarray, rate: int, to: int = SAMPLE_RATE) -> np.ndarray:
    """\a audio at \a rate, at \a to instead. Linear, which is plenty for speech."""
    if rate == to or audio.size == 0:
        return audio.astype(np.float32, copy=False)
    count = int(round(audio.size * to / rate))
    positions = np.linspace(0, audio.size - 1, count)
    return np.interp(positions, np.arange(audio.size), audio).astype(np.float32)


def clean(text: str) -> str:
    """What Whisper wrote, without its notes on sounds or what it invents on silence."""
    text = " ".join(_NOTES.sub(" ", text).split())
    plain = re.sub(r"[^a-z ]", "", text.lower()).strip()
    if not plain or plain in _INVENTED:
        return ""
    return text


# -- Whisper -------------------------------------------------------------------------------------


class Transcriber:
    """Whisper small.en, loaded the first time it is needed and kept."""

    def __init__(self, model: Path = WHISPER_MODEL, threads: int = THREADS) -> None:
        self._model = model
        self._threads = threads
        self._context: Any = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> str:
        """Why Whisper cannot run, or ""."""
        return missing(self._model)

    def load(self) -> None:
        """Load the model now rather than on the first transcription."""
        with self._lock:
            self._load()

    def _load(self) -> Any:
        if self._context is None:
            problem = self.ready
            if problem:
                raise VoiceError(problem)
            whisper = load_engines().whisper
            context = whisper.whisper_init_from_file_with_params(
                str(self._model), whisper.whisper_context_default_params())
            if context is None:
                raise VoiceError(f"Whisper could not load {self._model.name}.")
            self._context = context
        return self._context

    def transcribe(self, audio: np.ndarray) -> str:
        """The words in \a audio, mono at 16 kHz, cleaned. "" when there were none."""
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if speech_seconds(audio) < MIN_SPEECH_SECONDS:
            return ""
        with self._lock:
            context = self._load()
            whisper = load_engines().whisper
            params = whisper.whisper_full_default_params(whisper.WHISPER_SAMPLING_GREEDY)
            params.language = "en"
            params.translate = False
            params.n_threads = self._threads
            params.print_progress = params.print_realtime = False
            params.print_timestamps = params.print_special = False
            params.no_context = True
            params.no_timestamps = True
            params.suppress_blank = True
            params.suppress_nst = True
            params.temperature = 0.0
            if whisper.whisper_full(context, params, audio, audio.size) != 0:
                raise VoiceError("Whisper could not make out what was said.")
            pieces = []
            for index in range(whisper.whisper_full_n_segments(context)):
                piece = whisper.whisper_full_get_segment_text(context, index)
                pieces.append(piece.decode("utf-8", "replace") if isinstance(piece, bytes)
                              else str(piece))
        return clean("".join(pieces))

    def close(self) -> None:
        with self._lock:
            if self._context is not None:
                load_engines().whisper.whisper_free(self._context)
                self._context = None


# -- the microphone ------------------------------------------------------------------------------


class Microphone:
    """The default microphone, recorded into memory.

    Opened at 16 kHz where the device allows it, and otherwise at its own rate
    and converted when it closes.
    """

    def __init__(self, max_seconds: float = MAX_SECONDS, device: int | str | None = None,
                 sounddevice: Any = None) -> None:
        self._max_seconds = max_seconds
        self._device = device
        self._sounddevice = sounddevice
        self._stream: Any = None
        self._pieces: list[np.ndarray] = []
        self._kept = 0
        self._limit = 0
        self._rate = SAMPLE_RATE
        self._level = 0.0
        self._lock = threading.Lock()

    @property
    def open(self) -> bool:
        return self._stream is not None

    @property
    def level(self) -> float:
        """How loud the last moment was, 0 to 1, for a meter."""
        return self._level

    @property
    def full(self) -> bool:
        """Whether it has recorded all it may."""
        return self._kept >= self._limit > 0

    def _devices(self) -> Any:
        return self._sounddevice if self._sounddevice is not None else load_engines().sounddevice

    def start(self) -> None:
        if self._stream is not None:
            return
        sd = self._devices()
        try:
            try:
                sd.check_input_settings(device=self._device, channels=1, dtype="float32",
                                        samplerate=SAMPLE_RATE)
                rate = SAMPLE_RATE
            except Exception:
                rate = int(sd.query_devices(self._device, "input")["default_samplerate"])
            with self._lock:
                self._pieces, self._kept, self._level = [], 0, 0.0
                self._rate, self._limit = rate, int(rate * self._max_seconds)
            stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                    device=self._device, callback=self._heard)
        except Exception as exc:
            raise VoiceError(f"The microphone could not be opened: {exc}") from None
        try:
            stream.start()
        except Exception as exc:
            with contextlib.suppress(Exception):
                stream.close()
            raise VoiceError(f"The microphone could not be opened: {exc}") from None
        self._stream = stream

    def _heard(self, indata: np.ndarray, frames: int, when: Any, status: Any) -> None:
        # On the audio thread: copy, since the buffer is reused, and keep no more
        # than the limit.
        mono = indata[:, 0] if indata.ndim > 1 else indata
        with self._lock:
            room = self._limit - self._kept
            if room > 0:
                piece = np.array(mono[:room], dtype=np.float32)
                self._pieces.append(piece)
                self._kept += piece.size
            loudness = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
            self._level = min(1.0, loudness * 8.0)

    def stop(self) -> np.ndarray:
        """Close the microphone and hand over what it heard, at 16 kHz. It keeps nothing."""
        stream, self._stream = self._stream, None
        if stream is not None:
            # Closed whatever stopping it says: a microphone left open is the
            # one outcome that must not happen.
            with contextlib.suppress(Exception):
                stream.stop()
            with contextlib.suppress(Exception):
                stream.close()
        with self._lock:
            pieces, self._pieces, self._kept, self._level = self._pieces, [], 0, 0.0
            rate = self._rate
        audio = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)
        return resample(audio, rate)


# -- a press of the button -----------------------------------------------------------------------


class Listener:
    """Push to talk: open the microphone, then close it and read what it heard."""

    def __init__(self, policy: Callable[[], Policy], audit: AuditLog | None = None,
                 transcriber: Transcriber | None = None,
                 microphone: Microphone | None = None) -> None:
        self._policy = policy
        self._audit = audit
        self._transcriber = transcriber if transcriber is not None else Transcriber()
        self._microphone = microphone if microphone is not None else Microphone()

    @property
    def transcriber(self) -> Transcriber:
        return self._transcriber

    @property
    def microphone(self) -> Microphone:
        return self._microphone

    @property
    def listening(self) -> bool:
        return self._microphone.open

    def ready(self) -> str:
        """Why listening cannot start, or "". Opens nothing to find out."""
        decision = self._policy().allows("audio.record")
        if not decision:
            return f"Not permitted: {decision.reason}."
        return self._transcriber.ready

    def allowed(self) -> bool:
        return bool(self._policy().allows("audio.record"))

    def start(self) -> None:
        problem = self.ready()
        if problem:
            self._log(False, 0.0, problem)
            raise VoiceError(problem)
        self._microphone.start()

    def cancel(self) -> None:
        """Close the microphone and throw away what it heard."""
        if self._microphone.open:
            audio = self._microphone.stop()
            self._log(True, audio.size / SAMPLE_RATE, "thrown away unheard")

    def stop(self) -> Heard:
        """Close the microphone and return the words it heard.

        Slow: Whisper takes a second or two. Call it from a worker.
        """
        if not self._microphone.open:
            return Heard("", 0.0)
        audio = self._microphone.stop()
        seconds = audio.size / SAMPLE_RATE
        if not self.allowed():
            # Withdrawn while the microphone was open: nothing it heard is used.
            self._log(False, seconds, "listening was withdrawn while the microphone was open")
            raise VoiceError("Listening was withdrawn, so what was recorded was thrown away.")
        self._log(True, seconds)
        try:
            return Heard(self._transcriber.transcribe(audio), seconds)
        finally:
            del audio

    def _log(self, allowed: bool, seconds: float, error: str = "") -> None:
        if self._audit is not None:
            self._audit.record(Event(time.time(), "tool", "user", "listen", allowed,
                                     {"seconds": round(seconds, 1)}, error=error))
