"""A live call (D3): talking with Akira without pressing anything, until the person ends it.

The microphone is open only while a call the person started is running. Muting
closes it: capture stops, rather than what it hears being ignored. Ending the
call, closing Akira, or withdrawing Listen or Speak closes it too. There is no
wake word, so the microphone is never open when the person has not started
something.

While the call runs, `Endpointer` finds where the person starts and stops
talking. Each thing said is made out by Whisper and handed to the owner, which
sends it to the chat; the owner reads the reply aloud as it streams in and
says when it is over (`answered`).

**Hearing itself.** On speakers, the microphone hears Akira's own voice. So by
default nothing is listened to while Akira is thinking or speaking, and for a
moment after, and the person interrupts with a button. With headphones, the
person can turn on `interrupt_by_voice`: speaking over Akira then stops it,
stops the reply, and what they say next is the next thing sent.

What is heard stays in memory until it is words and is then dropped. The log
records that a call began and ended, how long it ran and how many things were
said, never what.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any, Callable

import numpy as np

from akira.core.permissions import AuditLog, Policy
from akira.core.permissions.audit import Event
from akira.core.voice import VoiceError, load_engines
from akira.core.voice.listen import (ABOVE_ROOM, ROOM_CEILING, SAMPLE_RATE, SPEECH_FLOOR,
                                     Transcriber, close_input, input_rate, open_input, resample)
from akira.core.voice.speak import Speaker

#: 30 ms at 16 kHz: what loudness is judged over.
FRAME = SAMPLE_RATE * 30 // 1000

#: Speech has begun when this many of the last `START_WINDOW` frames are loud.
START_FRAMES, START_WINDOW = 6, 10

#: Speech has ended after this much quiet: 0.8 s.
END_FRAMES = 27

#: Kept from before speech began, so its first sound is not cut: 0.3 s.
PRE_ROLL_FRAMES = 10

#: Kept of the quiet at the end: 0.2 s.
TAIL_FRAMES = 7

#: Less loud speech than this in one utterance is a cough or a door: 0.3 s.
MIN_SPEECH_FRAMES = 10

#: The longest one thing said may be before it is sent as it stands.
MAX_UTTERANCE_SECONDS = 30

#: How far back the room's own loudness is judged from: 3 s.
ROOM_FRAMES = 100

#: After Akira stops speaking, the room is still ringing with it for this long.
ECHO_TAIL_SECONDS = 0.4

#: How much the microphone may hold while nothing reads it: 10 s.
BACKLOG_BLOCKS = 334

LISTENING, HEARING, THINKING, SPEAKING, MUTED, ENDED = (
    "listening", "hearing", "thinking", "speaking", "muted", "ended")


# -- where speech starts and stops ---------------------------------------------------------------


class Endpointer:
    """Finds where someone starts and stops talking, in audio given a block at a time.

    The room is the quietest fifth of the last three seconds; speech is what is
    several times louder than it. `feed` returns `("began", None)` when speech
    starts and `("ended", audio)` when it stops, with `None` in place of audio
    when there was too little speech in it to be worth hearing.
    """

    def __init__(self) -> None:
        self._room: deque = deque(maxlen=ROOM_FRAMES)
        self._carry = np.zeros(0, dtype=np.float32)
        self.reset()

    def reset(self) -> None:
        """Forget anything under way; the room is remembered."""
        self._carry = np.zeros(0, dtype=np.float32)
        self._before: deque = deque(maxlen=PRE_ROLL_FRAMES)
        self._recent: deque = deque(maxlen=START_WINDOW)
        self._frames: list[np.ndarray] = []
        self._talking = False
        self._quiet = 0
        self._loud = 0
        self._bar = SPEECH_FLOOR

    @property
    def talking(self) -> bool:
        return self._talking

    def _threshold(self) -> float:
        if not self._room:
            return SPEECH_FLOOR
        room = min(float(np.percentile(self._room, 20)), ROOM_CEILING)
        return max(SPEECH_FLOOR, room * ABOVE_ROOM)

    def feed(self, block: np.ndarray) -> list[tuple[str, np.ndarray | None]]:
        events: list[tuple[str, np.ndarray | None]] = []
        data = np.concatenate([self._carry, np.asarray(block, dtype=np.float32).ravel()])
        whole = data.size // FRAME
        self._carry = data[whole * FRAME:]
        for index in range(whole):
            frame = data[index * FRAME:(index + 1) * FRAME]
            loudness = float(np.sqrt(np.mean(np.square(frame))))
            self._room.append(loudness)
            if not self._talking:
                bar = self._threshold()
                self._before.append(frame)
                self._recent.append(loudness > bar)
                if sum(self._recent) >= START_FRAMES:
                    # The bar is held while they talk, so their own voice does
                    # not raise it.
                    self._talking, self._bar = True, bar
                    self._frames = list(self._before)
                    self._loud, self._quiet = sum(self._recent), 0
                    events.append(("began", None))
                continue
            self._frames.append(frame)
            if loudness > self._bar:
                self._loud += 1
                self._quiet = 0
            else:
                self._quiet += 1
            if (self._quiet >= END_FRAMES
                    or len(self._frames) * FRAME >= MAX_UTTERANCE_SECONDS * SAMPLE_RATE):
                events.append(("ended", self._finish()))
        return events

    def _finish(self) -> np.ndarray | None:
        keep = len(self._frames) - max(0, self._quiet - TAIL_FRAMES)
        audio = np.concatenate(self._frames[:keep]) if self._loud >= MIN_SPEECH_FRAMES else None
        self._talking, self._frames, self._quiet, self._loud = False, [], 0, 0
        self._before.clear()
        self._recent.clear()
        return audio


# -- the microphone, left open -------------------------------------------------------------------


class LiveMicrophone:
    """The microphone, open for a call, handing over what it hears as it hears it."""

    def __init__(self, device: int | str | None = None, sounddevice: Any = None) -> None:
        self._device = device
        self._sounddevice = sounddevice
        self._stream: Any = None
        self._rate = SAMPLE_RATE
        self._heard: queue.Queue = queue.Queue(maxsize=BACKLOG_BLOCKS)
        self._level = 0.0

    @property
    def open(self) -> bool:
        return self._stream is not None

    @property
    def level(self) -> float:
        return self._level

    def start(self) -> None:
        if self._stream is not None:
            return
        sd = self._sounddevice if self._sounddevice is not None else load_engines().sounddevice
        self._rate = input_rate(sd, self._device)
        self._drain()
        self._stream = open_input(sd, self._device, self._rate, self._hear,
                                  blocksize=self._rate * 30 // 1000)

    def _hear(self, indata: np.ndarray, frames: int, when: Any, status: Any) -> None:
        mono = np.array(indata[:, 0] if indata.ndim > 1 else indata, dtype=np.float32)
        loudness = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
        self._level = min(1.0, loudness * 8.0)
        block = resample(mono, self._rate)
        try:
            self._heard.put_nowait(block)
        except queue.Full:
            # Nobody has read it for ten seconds: the oldest goes.
            try:
                self._heard.get_nowait()
                self._heard.put_nowait(block)
            except (queue.Empty, queue.Full):
                pass

    def read(self, timeout: float = 0.1) -> np.ndarray | None:
        """What was heard next, at 16 kHz, or None if nothing was in \a timeout."""
        try:
            return self._heard.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        """Close the microphone and throw away anything not yet read."""
        stream, self._stream = self._stream, None
        close_input(stream)
        self._drain()
        self._level = 0.0

    def _drain(self) -> None:
        while True:
            try:
                self._heard.get_nowait()
            except queue.Empty:
                return


# -- the call ------------------------------------------------------------------------------------


def permitted(policy: Policy) -> str:
    """Why \a policy does not allow a call, or "". A call needs both Listen and Speak."""
    for capability, name in (("audio.record", "listen"), ("audio.play", "speak")):
        decision = policy.allows(capability)
        if not decision:
            return f"Not permitted: {decision.reason}. A call needs to {name}."
    return ""


class Call:
    """One call, from `start` to `end`. Its callbacks run on the call's own thread."""

    def __init__(self, policy: Callable[[], Policy], transcriber: Transcriber, speaker: Speaker, *,
                 on_heard: Callable[[str], None],
                 on_state: Callable[[str], None] = lambda state: None,
                 on_interrupt: Callable[[], None] = lambda: None,
                 on_ended: Callable[[str], None] = lambda why: None,
                 microphone: LiveMicrophone | None = None,
                 audit: AuditLog | None = None,
                 interrupt_by_voice: bool = False,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._policy = policy
        self._transcriber = transcriber
        self._speaker = speaker
        self._microphone = microphone if microphone is not None else LiveMicrophone()
        self._audit = audit
        self._on_heard = on_heard
        self._on_state = on_state
        self._on_interrupt = on_interrupt
        self._on_ended = on_ended
        self.interrupt_by_voice = interrupt_by_voice
        self._clock = clock
        self._ending = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = ""
        self._muted = False
        self._awaiting = False
        self._hearing = False
        self._making_out = False
        self._began = 0.0
        self._said = 0
        self._why = ""
        self._closed = False
        self._lock = threading.Lock()

    # -- what it is doing -------------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def active(self) -> bool:
        return self._thread is not None and not self._ending.is_set()

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def level(self) -> float:
        return self._microphone.level

    def ready(self) -> str:
        """Why a call cannot start, or "". A call needs both Listen and Speak."""
        return (permitted(self._policy()) or self._transcriber.ready
                or self._speaker.synthesizer.ready)

    # -- the person's controls --------------------------------------------------------------------

    def start(self) -> None:
        problem = self.ready()
        if problem:
            self._log("call", False, error=problem)
            raise VoiceError(problem)
        self._microphone.start()
        self._began = self._clock()
        self._log("call", True)
        self._thread = threading.Thread(target=self._run, name="akira-call", daemon=True)
        self._thread.start()

    def mute(self) -> None:
        """Close the microphone. Nothing is captured until `unmute`."""
        with self._lock:
            self._muted = True
            self._microphone.stop()
        self._refresh()

    def unmute(self) -> None:
        with self._lock:
            if not self.active or not self._muted:
                return
            problem = self.ready()
            if problem:
                raise VoiceError(problem)
            self._microphone.start()
            self._muted = False
        self._refresh()

    def answered(self) -> None:
        """The reply to what was last heard is over: all of it given to the speaker, or none."""
        self._awaiting = False
        self._refresh()

    def end(self, why: str = "", wait: bool = True) -> None:
        """End the call: the microphone closes at once, and Akira stops speaking.

        Without \a wait, returns without waiting for the call's thread, which
        may be making out something said; `on_ended` follows from that thread.
        """
        thread = self._thread
        if thread is None or self._ending.is_set():
            return
        self._why = why
        self._ending.set()
        with self._lock:
            self._microphone.stop()
        self._speaker.stop()
        if thread is not threading.current_thread():
            if not wait and thread.is_alive():
                return
            thread.join(5.0)
        self._close()

    # -- the call's own thread -------------------------------------------------------------------

    def _busy(self) -> bool:
        return self._awaiting or self._speaker.speaking

    def _run(self) -> None:
        heard = Endpointer()
        quiet_until = 0.0
        was_busy = False
        try:
            while not self._ending.is_set():
                problem = self._withdrawn()
                if problem:
                    self._why = problem
                    return
                if self._muted:
                    self._refresh()
                    self._ending.wait(0.05)
                    continue
                block = self._microphone.read(0.05)
                busy = self._busy()
                if was_busy and not busy and not self.interrupt_by_voice:
                    # On speakers the room is still ringing with Akira's voice.
                    # With headphones there is no echo, and what the person
                    # began saying over it must not be cut.
                    quiet_until = self._clock() + ECHO_TAIL_SECONDS
                    heard.reset()
                was_busy = busy
                self._refresh()
                if block is None or self._muted:
                    continue
                if (busy and not self.interrupt_by_voice) or self._clock() < quiet_until:
                    heard.reset()
                    continue
                for kind, audio in heard.feed(block):
                    if kind == "began":
                        self._hearing = True
                        if self._busy():
                            self._interrupt()
                    else:
                        self._hearing = False
                        if audio is not None:
                            self._make_out(audio)
                    self._refresh()
        except Exception as exc:  # noqa: BLE001 - a call must not end in silence
            self._why = f"The call stopped: {exc}"
        finally:
            self._ending.set()
            with self._lock:
                self._microphone.stop()
            self._close()

    def _interrupt(self) -> None:
        self._speaker.stop()
        self._awaiting = False
        self._on_interrupt()

    def _make_out(self, audio: np.ndarray) -> None:
        self._making_out = True
        self._refresh()
        try:
            text = self._transcriber.transcribe(audio)
        except VoiceError:
            text = ""
        finally:
            self._making_out = False
        if text and not self._withdrawn() and not self._ending.is_set():
            self._said += 1
            self._awaiting = True
            self._refresh()
            self._on_heard(text)

    def _withdrawn(self) -> str:
        for capability, what in (("audio.record", "Listening"), ("audio.play", "Speaking")):
            if not self._policy().allows(capability):
                return f"{what} was withdrawn, so the call ended."
        return ""

    def _refresh(self) -> None:
        if self._ending.is_set():
            return  # `_close` says it has ended, once
        if self._muted:
            state = MUTED
        elif self._hearing:
            state = HEARING
        elif self._making_out:
            state = THINKING
        elif self._speaker.speaking:
            state = SPEAKING
        elif self._awaiting:
            state = THINKING
        else:
            state = LISTENING
        if state != self._state:
            self._state = state
            self._on_state(state)

    def _close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._state = ENDED
        self._log("call", True, seconds=round(self._clock() - self._began, 1), said=self._said,
                  error=self._why)
        self._on_state(ENDED)
        self._on_ended(self._why)

    def _log(self, action: str, allowed: bool, error: str = "", **detail: Any) -> None:
        if self._audit is not None:
            self._audit.record(Event(time.time(), "tool", "user", action, allowed, detail,
                                     error=error))
