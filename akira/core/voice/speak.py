"""Speech out (D2): Kokoro, on this computer's processor, in one of six voices.

Kokoro 82M, quantised to int8, runs through onnxruntime on the CPU alone, which
on this machine speaks a little faster than it talks. The session is made here,
with the CPU named as its only provider, so onnxruntime never reaches for
anything else it was built with.

Text is spoken a sentence at a time: the first is heard while the next is being
made, so a long answer starts at once. What is written for the eye is taken out
first. Markdown's marks are dropped, a link is read as its words, and code is
not read out at all.

Stopping is immediate, within a tenth of a second, which is what lets a person
talk over Akira. Speaking needs `audio.play`, checked before each sentence.
"""

from __future__ import annotations

import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from akira.core.permissions import Policy
from akira.core.voice import KOKORO_MODEL, KOKORO_VOICES, VoiceError, load_engines, missing


@dataclass(frozen=True, slots=True)
class Voice:
    id: str
    name: str
    description: str

    @property
    def language(self) -> str:
        """What Kokoro is told the voice speaks: British voices begin with b."""
        return "en-gb" if self.id.startswith("b") else "en-us"


#: The six. The first is the default: feminine, professional, expressive.
VOICES = (
    Voice("af_heart", "Heart", "Warm and expressive, American"),
    Voice("af_bella", "Bella", "Bright and lively, American"),
    Voice("af_nicole", "Nicole", "Soft and close, American"),
    Voice("bf_emma", "Emma", "Clear and composed, British"),
    Voice("am_michael", "Michael", "Low and steady, American"),
    Voice("bm_george", "George", "Deep and measured, British"),
)
DEFAULT_VOICE = VOICES[0].id
BY_ID = {voice.id: voice for voice in VOICES}

#: How much faster or slower than Kokoro's own pace a person may set it.
SLOWEST, FASTEST = 0.6, 1.6

#: Threads for onnxruntime. Four was fastest here, at about real time.
THREADS = 4

#: What is heard between one piece of sound and the next check for "stop".
BLOCK_SECONDS = 0.1

#: The longest a piece given to Kokoro at once. A longer sentence is split at a
#: comma or a space, so the first sound comes soon.
MAX_PIECE = 280

#: The quiet between one sentence and the next, since each is made alone.
PAUSE_SECONDS = 0.2

CODE_SAID = "The code is on screen."

#: What `on_done` is told when speaking was stopped before the end.
STOPPED = "stopped"

_FENCE = re.compile(r"```.*?(?:```|\Z)|~~~.*?(?:~~~|\Z)", re.S)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"<?https?://\S+?>?(?=[\s)\],.;:!?]*(?:\s|$))")
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_INLINE_CODE = re.compile(r"`([^`]*)`")
#: `_` marks emphasis only at a word's edge, so snake_case stays whole.
_EMPHASIS = re.compile(r"(\*\*|\*|~~)(?=\S)(.+?)(?<=\S)\1"
                       r"|(?<!\w)(__|_)(?=\S)(.+?)(?<=\S)\3(?!\w)")
_LINE_MARK = re.compile(r"^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d{1,3}[.)]\s+)", re.M)
_RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$", re.M)
_TABLE_EDGE = re.compile(r"^\s*\|?\s*:?-{2,}.*$", re.M)
_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")


def speakable(text: str) -> str:
    """\a text as it should be heard: what is written for the eye taken out."""
    text = _FENCE.sub(f" {CODE_SAID} ", text)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("a link", text)
    text = _TAG.sub(" ", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _RULE.sub(" ", text)
    text = _TABLE_EDGE.sub(" ", text)
    text = _LINE_MARK.sub("", text)
    for _ in range(2):  # **bold with *italic* inside**
        text = _EMPHASIS.sub(lambda found: found.group(2) or found.group(4), text)
    lines = []
    for line in text.splitlines():
        if "|" in line:
            # A table's row, read as its cells.
            line = ", ".join(cell.strip() for cell in line.strip().strip("|").split("|")
                             if cell.strip())
        line = " ".join(line.split())
        if line:
            # A line that ends without a stop, a heading or a list item, is
            # still a pause.
            lines.append(line if line[-1] in ".!?…:;," else line + ".")
    return " ".join(lines)


def pieces(text: str, longest: int = MAX_PIECE) -> list[str]:
    """\a text in the pieces it is spoken in: sentences, split further if long."""
    found = []
    for sentence in _SENTENCE_END.split(text):
        sentence = sentence.strip()
        while len(sentence) > longest:
            cut = sentence.rfind(", ", 0, longest)
            if cut < longest // 3:
                cut = sentence.rfind(" ", 0, longest)
            if cut <= 0:
                cut = longest
            found.append(sentence[:cut + 1].strip())
            sentence = sentence[cut + 1:].strip()
        if sentence:
            found.append(sentence)
    return found


# -- Kokoro --------------------------------------------------------------------------------------


class Synthesizer:
    """Kokoro, loaded the first time it is needed and kept."""

    def __init__(self, model: Path = KOKORO_MODEL, voices: Path = KOKORO_VOICES,
                 threads: int = THREADS) -> None:
        self._model = model
        self._voices = voices
        self._threads = threads
        self._kokoro: Any = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> str:
        """Why Kokoro cannot run, or ""."""
        return missing(self._model, self._voices)

    def load(self) -> None:
        with self._lock:
            self._load()

    def _load(self) -> Any:
        if self._kokoro is None:
            problem = self.ready
            if problem:
                raise VoiceError(problem)
            loaded = load_engines()
            options = loaded.onnxruntime.SessionOptions()
            options.intra_op_num_threads = self._threads
            options.inter_op_num_threads = 1
            session = loaded.onnxruntime.InferenceSession(
                str(self._model), sess_options=options, providers=["CPUExecutionProvider"])
            self._kokoro = loaded.Kokoro.from_session(session, str(self._voices))
        return self._kokoro

    def synthesize(self, text: str, voice: str = DEFAULT_VOICE,
                   speed: float = 1.0) -> tuple[np.ndarray, int]:
        """\a text spoken in \a voice: the samples, and how many there are a second."""
        chosen = BY_ID.get(voice)
        if chosen is None:
            raise VoiceError(f"There is no voice called {voice!r}.")
        speed = min(FASTEST, max(SLOWEST, float(speed)))
        with self._lock:
            samples, rate = self._load().create(text, voice=chosen.id, speed=speed,
                                                lang=chosen.language)
        return np.asarray(samples, dtype=np.float32), int(rate)


# -- the speakers --------------------------------------------------------------------------------


class Speaker:
    """Says things, one at a time, and stops the moment it is asked to."""

    def __init__(self, policy: Callable[[], Policy], synthesizer: Synthesizer | None = None,
                 sounddevice: Any = None) -> None:
        self._policy = policy
        self._synthesizer = synthesizer if synthesizer is not None else Synthesizer()
        self._sounddevice = sounddevice
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def synthesizer(self) -> Synthesizer:
        return self._synthesizer

    @property
    def speaking(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def ready(self) -> str:
        """Why nothing can be said, or "". Loads nothing to find out."""
        decision = self._policy().allows("audio.play")
        if not decision:
            return f"Not permitted: {decision.reason}."
        return self._synthesizer.ready

    def say(self, text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0,
            on_done: Callable[[str], None] | None = None) -> bool:
        """Start saying \a text, stopping whatever was being said.

        Returns at once. \a on_done is called on another thread when it ends,
        with why it stopped short, or "" if it did not. False, and nothing
        said, when there is nothing to say.
        """
        problem = self.ready()
        if problem:
            raise VoiceError(problem)
        if voice not in BY_ID:
            raise VoiceError(f"There is no voice called {voice!r}.")
        said = pieces(speakable(text))
        if not said:
            return False
        with self._lock:
            self.stop()
            stop = self._stop = threading.Event()
            self._thread = threading.Thread(target=self._speak, name="akira-speak", daemon=True,
                                            args=(said, voice, speed, stop, on_done))
            self._thread.start()
        return True

    def stop(self, wait: float = 1.0) -> None:
        """Stop speaking, within a tenth of a second."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(wait)

    def _devices(self) -> Any:
        return self._sounddevice if self._sounddevice is not None else load_engines().sounddevice

    def _speak(self, said: list[str], voice: str, speed: float, stop: threading.Event,
               on_done: Callable[[str], None] | None) -> None:
        made: queue.Queue = queue.Queue(maxsize=2)
        maker = threading.Thread(target=self._make, name="akira-speak-make", daemon=True,
                                 args=(said, voice, speed, stop, made))
        maker.start()
        problem = ""
        stream = None
        try:
            while not stop.is_set():
                try:
                    piece = made.get(timeout=BLOCK_SECONDS)
                except queue.Empty:
                    continue
                if piece is None:
                    break
                if isinstance(piece, str):
                    problem = piece
                    break
                samples, rate = piece
                if stream is None:
                    stream = self._devices().OutputStream(samplerate=rate, channels=1,
                                                          dtype="float32")
                    stream.start()
                block = max(1, int(rate * BLOCK_SECONDS))
                for start in range(0, samples.size, block):
                    if stop.is_set():
                        break
                    stream.write(samples[start:start + block].reshape(-1, 1))
        except Exception as exc:
            problem = f"The speakers could not be used: {exc}"
        finally:
            stopped = stop.is_set()
            stop.set()
            if stream is not None:
                try:
                    stream.abort() if stopped else stream.stop()
                finally:
                    stream.close()
            maker.join(1.0)
        if on_done is not None:
            on_done(problem or (STOPPED if stopped else ""))

    def _make(self, said: list[str], voice: str, speed: float, stop: threading.Event,
              made: queue.Queue) -> None:
        def hand_over(item: Any) -> bool:
            while not stop.is_set():
                try:
                    made.put(item, timeout=BLOCK_SECONDS)
                    return True
                except queue.Full:
                    continue
            return False

        for piece in said:
            if stop.is_set():
                return
            decision = self._policy().allows("audio.play")
            if not decision:
                hand_over(f"Not permitted: {decision.reason}.")
                return
            try:
                sound = self._synthesizer.synthesize(piece, voice, speed)
            except VoiceError as exc:
                hand_over(str(exc))
                return
            except Exception as exc:
                hand_over(f"Kokoro could not say that: {exc}")
                return
            samples, rate = sound
            pause = np.zeros(int(rate * PAUSE_SECONDS), dtype=np.float32)
            if not hand_over((np.concatenate([samples, pause]), rate)):
                return
        hand_over(None)
