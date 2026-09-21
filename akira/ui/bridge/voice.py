"""Speech in and out for the interface — the `Voice` bridge (D1, D2).

Push to talk: `startListening()` opens the microphone and `stopListening()`
closes it; what was said arrives on `heard(text)` a second or two later, for the
interface to put where it wants it. Nothing that was heard is kept, and nothing
is sent anywhere.

Starting to listen stops Akira speaking, so a person can talk over it. While the
microphone is open it is checked twenty times a second: withdrawing `audio.record`
closes it at once and throws away what it heard, and so does reaching
`maxSeconds`, except that then what was heard is kept.

`speak(text)` reads text aloud in the chosen voice and `stopSpeaking()` stops
it. With `readAloud` on, each finished answer in the chat is read out. Speaking
needs `audio.play`.

Whisper and Kokoro load the first time they are used, on a worker, and stay
loaded. Every slow thing happens off this thread, and its result crosses back on
a queued signal.
"""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from akira.core.permissions import AuditLog, Policy
from akira.core.voice import VoiceError, unavailable
from akira.core.voice.listen import MAX_SECONDS, Listener
from akira.core.voice.speak import BY_ID, STOPPED, VOICES, Speaker
from akira.core.voice.store import VoiceSettings, VoiceStore, checked

#: How often the open microphone is looked at: its level, its limit, its permission.
TICK_MS = 50

#: What a voice says when a person tries it.
SAMPLE = "Hello, I'm Akira. This is how I sound when I read something to you."


class VoiceBridge(QObject):
    """Listening, speaking, and the voice a person chose."""

    stateChanged = Signal()
    levelChanged = Signal()
    settingsChanged = Signal()

    #: What one press of the button heard; "" is never sent.
    heard = Signal(str)

    #: Private: from a worker to this thread.
    _transcribed = Signal(str, str)
    _spoke = Signal(int, str)

    def __init__(self, policy: Callable[[], Policy], audit: AuditLog | None = None, *,
                 store: VoiceStore | None = None, listener: Listener | None = None,
                 speaker: Speaker | None = None, check: Callable[[], str] = unavailable,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store if store is not None else VoiceStore()
        self._settings = self._store.load()
        self._listener = listener if listener is not None else Listener(policy, audit)
        self._speaker = speaker if speaker is not None else Speaker(policy)
        self._unavailable = check()
        self._listening = False
        self._transcribing = False
        self._speaking = False
        self._level = 0.0
        self._note = ""
        self._said = 0
        self._workers: list[threading.Thread] = []
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._transcribed.connect(self._on_transcribed)
        self._spoke.connect(self._on_spoke)

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
        return self.available and not self._listener.ready()

    @Property(str, notify=stateChanged)
    def listenBlocked(self) -> str:
        """Why the microphone cannot be opened now, or ""."""
        return self._unavailable or self._listener.ready()

    @Property(bool, notify=stateChanged)
    def canSpeak(self) -> bool:
        return self.available and not self._speaker.ready()

    @Property(str, notify=stateChanged)
    def speakBlocked(self) -> str:
        return self._unavailable or self._speaker.ready()

    @Property(bool, notify=stateChanged)
    def listening(self) -> bool:
        """The microphone is open. The interface shows it whenever this is true."""
        return self._listening

    @Property(bool, notify=stateChanged)
    def transcribing(self) -> bool:
        return self._transcribing

    @Property(bool, notify=stateChanged)
    def speaking(self) -> bool:
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
        self._timer.stop()
        self._listening = False
        self._set_level(0.0)

    def _tick(self) -> None:
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

    @Slot(str)
    def readReply(self, text: str) -> None:
        """An answer finished in the chat: read it out if the person asked for that."""
        if self._settings.read_aloud and not self._listening:
            self._say(text, self._settings.voice)

    @Slot()
    def stopSpeaking(self) -> None:
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
        if not on:
            self.stopSpeaking()
        self._change(read_aloud=on)

    def _change(self, **changes) -> None:
        now = self._settings
        wanted = checked(changes.get("voice", now.voice), changes.get("speed", now.speed),
                         changes.get("read_aloud", now.read_aloud))
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
        """Permissions changed: read again what can be done, and act on a withdrawal."""
        if self._listening and not self._listener.allowed():
            self._tick()
        if self._speaking and self._speaker.ready():
            self.stopSpeaking()
        self.stateChanged.emit()

    @Slot()
    def clearNote(self) -> None:
        self._set_note("")

    def close(self) -> None:
        """Close the microphone, stop speaking, and let the models go."""
        self._closed = True
        self._timer.stop()
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
