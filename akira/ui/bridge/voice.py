"""Speech in and out for the interface — the `Voice` bridge (D1, D2, D3).

Push to talk: `startListening()` opens the microphone and `stopListening()`
closes it; what was said arrives on `heard(text)` a second or two later, for the
interface to put where it wants it. Nothing that was heard is kept.

Starting to listen stops Akira speaking, so a person can talk over it. While the
microphone is open it is checked twenty times a second: withdrawing `audio.record`
closes it at once and throws away what it heard, and so does reaching
`maxSeconds`, except that then what was heard is kept.

`speak(text)` reads text aloud in the chosen voice and `stopSpeaking()` stops
it. With `readAloud` on, the chat's replies are read out as they stream in, a
sentence at a time, so a slow model is heard from its first sentence rather
than its last. Speaking needs `audio.play`.

A call (`startCall()`) is talking with Akira without pressing anything: what
the person says is sent to the chat and the reply is read aloud, until they end
it. The microphone is open only during a call, and `setMuted(true)` closes it.
See `akira.core.voice.call`.

Whisper and Kokoro load the first time they are used, on a worker, and stay
loaded. Every slow thing happens off this thread, and its result crosses back on
a queued signal.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from akira.core.permissions import AuditLog, Policy
from akira.core.voice import VoiceError, unavailable
from akira.core.voice.call import LISTENING, Call, permitted
from akira.core.voice.listen import MAX_SECONDS, Listener
from akira.core.voice.speak import BY_ID, STOPPED, VOICES, Reading, Speaker, Unfolding
from akira.core.voice.store import VoiceSettings, VoiceStore, checked

#: How often the open microphone is looked at: its level, its limit, its permission.
TICK_MS = 50

#: What a voice says when a person tries it.
SAMPLE = "Hello, I'm Akira. This is how I sound when I read something to you."


class VoiceBridge(QObject):
    """Listening, speaking, calls, and the voice a person chose."""

    stateChanged = Signal()
    levelChanged = Signal()
    settingsChanged = Signal()
    callChanged = Signal()

    #: What one press of the button heard; "" is never sent. Not sent in a call,
    #: where what is heard goes to the chat.
    heard = Signal(str)

    #: Private: from a worker, or a call's thread, to this one. Each carries
    #: which reading or call it is about, so a late one is recognised.
    _transcribed = Signal(str, str)
    _spoke = Signal(int, str)
    _callHeard = Signal(int, str)
    _callState = Signal(int, str)
    _callInterrupted = Signal(int)
    _callEnded = Signal(int, str)

    def __init__(self, policy: Callable[[], Policy], audit: AuditLog | None = None, *,
                 store: VoiceStore | None = None, listener: Listener | None = None,
                 speaker: Speaker | None = None, check: Callable[[], str] = unavailable,
                 make_call: Callable[..., Any] | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._policy = policy
        self._store = store if store is not None else VoiceStore()
        self._settings = self._store.load()
        self._listener = listener if listener is not None else Listener(policy, audit)
        self._speaker = speaker if speaker is not None else Speaker(policy)
        self._make_call = make_call if make_call is not None else (
            lambda **options: Call(policy, self._listener.transcriber, self._speaker,
                                   audit=audit, **options))
        self._unavailable = check()
        self._listening = False
        self._transcribing = False
        self._speaking = False
        self._level = 0.0
        self._note = ""
        self._said = 0
        self._workers: list[threading.Thread] = []
        self._closed = False
        # The chat whose replies are read, and to which a call sends what it hears.
        self._chat: Any = None
        self._reading: Reading | None = None
        self._unfolding: Unfolding | None = None
        self._reply_passed = False
        # The call, if one is running.
        self._call: Any = None
        self._calls = 0
        self._call_state = ""
        self._pending = ""
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._transcribed.connect(self._on_transcribed)
        self._spoke.connect(self._on_spoke)
        self._callHeard.connect(self._on_call_heard)
        self._callState.connect(self._on_call_state)
        self._callInterrupted.connect(self._on_call_interrupted)
        self._callEnded.connect(self._on_call_ended)

    def follow(self, chat: Any) -> None:
        """Read \a chat's replies aloud, and send it what a call hears.

        \a chat is the `ChatBridge`: its `replyGrew`, `replyEnded` and
        `busyChanged` signals, and its `send`, `stop` and `busy`.
        """
        self._chat = chat
        chat.replyGrew.connect(self._on_reply_grew)
        chat.replyEnded.connect(self._on_reply_ended)
        chat.busyChanged.connect(self._on_chat_busy)

    # -- what the interface reads ------------------------------------------------------------

    @Property(bool, notify=stateChanged)
    def available(self) -> bool:
        """Whether the voice packages and files are on this computer."""
        return not self._unavailable

    @Property(str, notify=stateChanged)
    def unavailableReason(self) -> str:
        return self._unavailable

    @Property(bool, notify=stateChanged)
    def canListen(self) -> bool:
        return not self.listenBlocked

    @Property(str, notify=stateChanged)
    def listenBlocked(self) -> str:
        """Why the microphone cannot be opened now, or ""."""
        if self._call is not None:
            return "A call is listening already."
        return self._unavailable or self._listener.ready()

    @Property(bool, notify=stateChanged)
    def canSpeak(self) -> bool:
        return self.available and not self._speaker.ready()

    @Property(str, notify=stateChanged)
    def speakBlocked(self) -> str:
        return self._unavailable or self._speaker.ready()

    @Property(bool, notify=stateChanged)
    def listening(self) -> bool:
        """The microphone is open for push to talk. Show it whenever this is true."""
        return self._listening

    @Property(bool, notify=stateChanged)
    def transcribing(self) -> bool:
        return self._transcribing

    @Property(bool, notify=stateChanged)
    def speaking(self) -> bool:
        """Something is being read aloud, including a reply still arriving."""
        return self._speaking

    @Property(float, notify=levelChanged)
    def level(self) -> float:
        """How loud the microphone is, 0 to 1, while it is open."""
        return self._level

    @Property(str, notify=stateChanged)
    def note(self) -> str:
        """The last thing that went wrong, said plainly, or ""."""
        return self._note

    @Property(int, constant=True)
    def maxSeconds(self) -> int:
        return MAX_SECONDS

    @Property("QVariantList", constant=True)
    def voices(self) -> list:
        return [{"id": v.id, "name": v.name, "description": v.description} for v in VOICES]

    @Property(str, notify=settingsChanged)
    def voice(self) -> str:
        return self._settings.voice

    @Property(float, notify=settingsChanged)
    def speed(self) -> float:
        return self._settings.speed

    @Property(bool, notify=settingsChanged)
    def readAloud(self) -> bool:
        return self._settings.read_aloud

    @Property(bool, notify=settingsChanged)
    def interruptByVoice(self) -> bool:
        return self._settings.interrupt_by_voice

    # -- a call, as the interface sees it ----------------------------------------------------

    @Property(bool, notify=callChanged)
    def inCall(self) -> bool:
        return self._call is not None

    @Property(bool, notify=callChanged)
    def muted(self) -> bool:
        return self._call is not None and self._call.muted

    @Property(str, notify=callChanged)
    def callState(self) -> str:
        """`listening`, `hearing`, `thinking`, `speaking` or `muted`; "" out of a call."""
        return self._call_state if self._call is not None else ""

    @Property(str, notify=stateChanged)
    def callBlocked(self) -> str:
        """Why a call cannot start now, or ""."""
        if self._call is not None:
            return ""
        if self._chat is None:
            return "There is no conversation for a call to talk to."
        return (self._unavailable or permitted(self._policy())
                or self._listener.transcriber.ready or self._speaker.synthesizer.ready)

    # -- listening ---------------------------------------------------------------------------

    @Slot(result=bool)
    def startListening(self) -> bool:
        """Open the microphone. False, with `note` saying why, when it cannot be."""
        if self._closed or self._listening:
            return self._listening
        if self._transcribing:
            self._set_note("Still making out what was said.")
            return False
        problem = self.listenBlocked
        if problem:
            self._set_note(problem)
            return False
        self.stopSpeaking()
        try:
            self._listener.start()
        except VoiceError as exc:
            self._set_note(str(exc))
            return False
        self._listening = True
        self._note = ""
        self._timer.start()
        self._work(self._listener.transcriber.load)
        self.stateChanged.emit()
        return True

    @Slot()
    def stopListening(self) -> None:
        """Close the microphone and make out what it heard; `heard` follows."""
        if not self._listening:
            return
        self._end_listening()
        self._transcribing = True
        self.stateChanged.emit()
        self._work(self._transcribe)

    @Slot()
    def cancelListening(self) -> None:
        """Close the microphone and throw away what it heard."""
        if not self._listening:
            return
        self._end_listening()
        self._listener.cancel()
        self.stateChanged.emit()

    def _end_listening(self) -> None:
        self._listening = False
        if self._call is None:
            self._timer.stop()
        self._set_level(0.0)

    def _tick(self) -> None:
        if self._call is not None:
            self._set_level(0.0 if self._call.muted else self._call.level)
            return
        microphone = self._listener.microphone
        if not self._listener.allowed():
            self.cancelListening()
            self._set_note("Listening was withdrawn, so what was recorded was thrown away.")
            return
        self._set_level(microphone.level)
        if microphone.full:
            self.stopListening()

    def _transcribe(self) -> None:
        try:
            heard = self._listener.stop()
        except VoiceError as exc:
            self._transcribed.emit("", str(exc))
        except Exception as exc:  # noqa: BLE001 - a crashed worker must not be silent
            self._transcribed.emit("", f"What was said could not be made out: {exc}")
        else:
            self._transcribed.emit(heard.text, "" if heard.text else "Nothing was heard.")

    @Slot(str, str)
    def _on_transcribed(self, text: str, problem: str) -> None:
        self._transcribing = False
        self._note = problem
        self.stateChanged.emit()
        if text and not self._closed:
            self.heard.emit(text)

    # -- speaking ----------------------------------------------------------------------------

    @Slot(str, result=bool)
    def speak(self, text: str) -> bool:
        """Read \a text aloud in the chosen voice, stopping whatever was being said."""
        return self._say(text, self._settings.voice)

    @Slot(str, result=bool)
    def previewVoice(self, voice: str) -> bool:
        """Say a line in \a voice, so a person can hear it before choosing it."""
        return self._say(SAMPLE, voice)

    @Slot()
    def stopSpeaking(self) -> None:
        """Stop reading, and read no more of the reply being read."""
        if self._speaking:
            self._said += 1  # what the stopped one reports is no longer news
            self._speaker.stop()
            self._speaking = False
            self.stateChanged.emit()

    def _say(self, text: str, voice: str) -> bool:
        if self._closed:
            return False
        problem = self.speakBlocked
        if problem:
            self._set_note(problem)
            return False
        self._said += 1
        said = self._said
        try:
            started = self._speaker.say(text, voice, self._settings.speed,
                                        on_done=lambda why: self._spoke.emit(said, why))
        except VoiceError as exc:
            self._set_note(str(exc))
            return False
        self._speaking = started
        self._note = ""
        self.stateChanged.emit()
        return started

    @Slot(int, str)
    def _on_spoke(self, said: int, why: str) -> None:
        if said != self._said:
            return
        self._speaking = False
        if why and why != STOPPED:
            self._note = why
        self.stateChanged.emit()

    # -- the chat's replies, read as they come -----------------------------------------------

    def _reads_replies(self) -> bool:
        return self._call is not None or self._settings.read_aloud

    @Slot(str)
    def _on_reply_grew(self, text: str) -> None:
        if self._closed or self._reply_passed or not self._reads_replies():
            return
        if self._reading is None:
            if self._listening:
                # The person is talking to push to talk; this reply is not read.
                self._reply_passed = True
                return
            problem = self.speakBlocked
            if problem:
                self._reply_passed = True
                self._set_note(problem)
                return
            self._said += 1
            said = self._said
            try:
                self._reading = self._speaker.begin(
                    self._settings.voice, self._settings.speed,
                    on_done=lambda why: self._spoke.emit(said, why))
            except VoiceError as exc:
                self._reply_passed = True
                self._set_note(str(exc))
                return
            self._unfolding = Unfolding()
            self._speaking = True
            self.stateChanged.emit()
        self._reading.add(self._unfolding.grew(text))

    @Slot(str)
    def _on_reply_ended(self, text: str) -> None:
        reading, unfolding = self._reading, self._unfolding
        self._reading, self._unfolding, self._reply_passed = None, None, False
        if reading is not None:
            if text:
                reading.add(unfolding.ended(text))
                reading.finish()
            else:
                # Stopped, failed or empty: nothing more of it is read.
                reading.stop()
        if self._call is not None:
            self._call.answered()

    @Slot()
    def _on_chat_busy(self) -> None:
        if self._chat is not None and not self._chat.busy and self._pending:
            text, self._pending = self._pending, ""
            self._send(text)

    # -- a call ------------------------------------------------------------------------------

    @Slot(result=bool)
    def startCall(self) -> bool:
        """Start talking with Akira hands-free. False, with `note` saying why, if it cannot."""
        if self._closed or self._call is not None:
            return self._call is not None
        if self._listening or self._transcribing:
            self._set_note("Finish talking first.")
            return False
        problem = self.callBlocked
        if problem:
            self._set_note(problem)
            return False
        self.stopSpeaking()
        self._calls += 1
        n = self._calls
        call = self._make_call(
            on_heard=lambda text: self._callHeard.emit(n, text),
            on_state=lambda state: self._callState.emit(n, state),
            on_interrupt=lambda: self._callInterrupted.emit(n),
            on_ended=lambda why: self._callEnded.emit(n, why),
            interrupt_by_voice=self._settings.interrupt_by_voice)
        try:
            call.start()
        except VoiceError as exc:
            self._set_note(str(exc))
            return False
        self._call, self._call_state, self._pending, self._note = call, LISTENING, "", ""
        self._timer.start()
        self._work(self._listener.transcriber.load)
        self._work(self._speaker.synthesizer.load)
        self.callChanged.emit()
        self.stateChanged.emit()
        return True

    @Slot()
    def endCall(self) -> None:
        """End the call: the microphone closes and Akira stops at once."""
        call = self._call
        if call is None:
            return
        self._forget_call()
        call.end(wait=False)
        self.stopSpeaking()

    @Slot(bool)
    def setMuted(self, on: bool) -> None:
        """Mute closes the microphone; capture stops, it is not ignored."""
        call = self._call
        if call is None or call.muted == on:
            return
        try:
            call.mute() if on else call.unmute()
        except VoiceError as exc:
            self._set_note(str(exc))
        if call.muted:
            self._set_level(0.0)
        self.callChanged.emit()

    def _send(self, text: str) -> None:
        chat = self._chat
        if chat is None or self._call is None:
            return
        if chat.busy:
            # The newest thing said wins: the reply under way is stopped, and
            # this is sent when the chat is free.
            self._pending = text
            chat.stop()
            return
        chat.send(text)
        if not chat.busy:
            # Nothing is coming: no model, or it answered at once.
            self._call.answered()

    @Slot(int, str)
    def _on_call_heard(self, n: int, text: str) -> None:
        if n == self._calls and self._call is not None:
            self._send(text)

    @Slot(int, str)
    def _on_call_state(self, n: int, state: str) -> None:
        if n == self._calls and self._call is not None and state != self._call_state:
            self._call_state = state
            self.callChanged.emit()

    @Slot(int)
    def _on_call_interrupted(self, n: int) -> None:
        if n != self._calls or self._call is None:
            return
        self.stopSpeaking()
        if self._chat is not None and self._chat.busy:
            self._chat.stop()

    @Slot(int, str)
    def _on_call_ended(self, n: int, why: str) -> None:
        if n == self._calls and self._call is not None:
            self._forget_call()
            self.stopSpeaking()
        if why:
            self._set_note(why)

    def _forget_call(self) -> None:
        self._call, self._call_state, self._pending = None, "", ""
        if not self._listening:
            self._timer.stop()
        self._set_level(0.0)
        self.callChanged.emit()
        self.stateChanged.emit()

    # -- the choices -------------------------------------------------------------------------

    @Slot(str)
    def setVoice(self, voice: str) -> None:
        if voice in BY_ID:
            self._change(voice=voice)

    @Slot(float)
    def setSpeed(self, speed: float) -> None:
        self._change(speed=speed)

    @Slot(bool)
    def setReadAloud(self, on: bool) -> None:
        if not on and self._call is None:
            self.stopSpeaking()
        self._change(read_aloud=on)

    @Slot(bool)
    def setInterruptByVoice(self, on: bool) -> None:
        """For headphones: talking over Akira stops it. On speakers it would hear itself."""
        self._change(interrupt_by_voice=on)
        if self._call is not None:
            self._call.interrupt_by_voice = self._settings.interrupt_by_voice

    def _change(self, **changes) -> None:
        now = self._settings
        wanted = checked(changes.get("voice", now.voice), changes.get("speed", now.speed),
                         changes.get("read_aloud", now.read_aloud),
                         changes.get("interrupt_by_voice", now.interrupt_by_voice))
        if wanted == now:
            return
        self._settings = wanted
        try:
            self._store.save(wanted)
        except OSError as exc:
            self._set_note(f"The voice settings could not be saved: {exc}")
        self.settingsChanged.emit()

    @property
    def settings(self) -> VoiceSettings:
        return self._settings

    # -- the rest ----------------------------------------------------------------------------

    @Slot()
    def refresh(self) -> None:
        """Permissions changed: read again what can be done, and act on a withdrawal.

        A call notices a withdrawal itself, within a twentieth of a second.
        """
        if self._listening and not self._listener.allowed():
            self._tick()
        if self._speaking and self._speaker.ready():
            self.stopSpeaking()
        self.stateChanged.emit()

    @Slot()
    def clearNote(self) -> None:
        self._set_note("")

    def close(self) -> None:
        """End any call, close the microphone, stop speaking, and let the models go."""
        self._closed = True
        self._timer.stop()
        call, self._call = self._call, None
        if call is not None:
            call.end()
        if self._listening:
            self._listening = False
            self._listener.cancel()
        self._speaker.stop()
        for worker in self._workers:
            worker.join(15.0)
        if not any(worker.is_alive() for worker in self._workers):
            self._listener.transcriber.close()

    def _work(self, job: Callable[[], None]) -> None:
        def run() -> None:
            try:
                job()
            except Exception:  # noqa: BLE001 - loading early; the real use reports it
                pass

        self._workers = [w for w in self._workers if w.is_alive()]
        worker = threading.Thread(target=run, name="akira-voice", daemon=True)
        self._workers.append(worker)
        worker.start()

    def _set_note(self, note: str) -> None:
        if note != self._note:
            self._note = note
            self.stateChanged.emit()

    def _set_level(self, level: float) -> None:
        if abs(level - self._level) > 0.01 or (level == 0.0 and self._level != 0.0):
            self._level = level
            self.levelChanged.emit()
