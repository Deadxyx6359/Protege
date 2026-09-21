"""The `Voice` bridge (D1, D2, D3): push to talk, reading aloud, calls, and the chosen voice.

What listens, what speaks, the call and the chat are fakes; `test_voice.py` and
`test_voice_call.py` test the real ones. What is tested here is what the
interface is told, what reaches the chat, and when.
"""

from __future__ import annotations

import threading
import time
import types

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication, QObject, Signal  # noqa: E402

from akira.core.permissions import Policy  # noqa: E402
from akira.core.voice import VoiceError  # noqa: E402
from akira.core.voice.listen import Heard  # noqa: E402
from akira.core.voice.speak import STOPPED  # noqa: E402
from akira.core.voice.store import VoiceSettings, VoiceStore  # noqa: E402
from akira.ui.bridge.voice import SAMPLE, VoiceBridge  # noqa: E402


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return predicate()


class FakeListener:
    def __init__(self, policy, text="Open my calendar."):
        self.policy, self.text = policy, text
        self.microphone = types.SimpleNamespace(level=0.0, full=False)
        self.transcriber = types.SimpleNamespace(load=lambda: None, close=lambda: None,
                                                 ready="")
        self.open = False
        self.started = self.cancelled = self.stopped = 0

    def ready(self):
        decision = self.policy.allows("audio.record")
        return "" if decision else f"Not permitted: {decision.reason}."

    def allowed(self):
        return bool(self.policy.allows("audio.record"))

    def start(self):
        self.open = True
        self.started += 1

    def cancel(self):
        self.open = False
        self.cancelled += 1

    def stop(self):
        self.open = False
        self.stopped += 1
        if isinstance(self.text, Exception):
            raise self.text
        return Heard(self.text, 1.0)


class FakeReading:
    def __init__(self):
        self.pieces, self.finished, self.stopped = [], False, False

    def add(self, pieces):
        self.pieces += pieces

    def finish(self):
        self.finished = True

    def stop(self, wait=1.0):
        self.stopped = True


class FakeSpeaker:
    def __init__(self, policy):
        self.policy = policy
        self.said, self.stops, self.done, self.readings = [], 0, [], []
        self.synthesizer = types.SimpleNamespace(ready="", load=lambda: None)

    def begin(self, voice, speed, on_done=None):
        if self.ready():
            raise VoiceError(self.ready())
        self.done.append(on_done)
        self.readings.append(FakeReading())
        return self.readings[-1]

    def ready(self):
        decision = self.policy.allows("audio.play")
        return "" if decision else f"Not permitted: {decision.reason}."

    def say(self, text, voice, speed, on_done=None):
        if not text.strip():
            return False
        self.said.append((text, voice, speed))
        self.done.append(on_done)
        return True

    def stop(self):
        self.stops += 1

    def finish(self, why=""):
        # As the speaking thread would, from another thread.
        threading.Thread(target=self.done[-1], args=(why,)).start()


class FakeChat(QObject):
    """The chat, as the voice bridge uses it."""

    replyGrew = Signal(str)
    replyEnded = Signal(str)
    busyChanged = Signal()

    def __init__(self, answers_at_once=False):
        super().__init__()
        self.busy, self.sent, self.stops = False, [], 0
        self.answers_at_once = answers_at_once

    def send(self, text):
        self.sent.append(text)
        self.busy = not self.answers_at_once

    def stop(self):
        self.stops += 1

    def reply(self, *growing, whole=None):
        for text in growing:
            self.replyGrew.emit(text)
        self.replyEnded.emit(growing[-1] if whole is None else whole)
        self.busy = False
        self.busyChanged.emit()


class FakeCall:
    """A call, driven by the test as its own thread would drive the bridge."""

    made: list = []

    def __init__(self, **options):
        self.options = options
        self.started = self.ended = False
        self.end_waited = None
        self.muted = False
        self.answers = 0
        self.level = 0.25
        self.interrupt_by_voice = options["interrupt_by_voice"]
        self.refuse_unmute = ""
        FakeCall.made.append(self)

    def start(self):
        self.started = True

    def mute(self):
        self.muted = True

    def unmute(self):
        if self.refuse_unmute:
            raise VoiceError(self.refuse_unmute)
        self.muted = False

    def answered(self):
        self.answers += 1

    def end(self, why="", wait=True):
        self.ended, self.end_waited = True, wait

    def hear(self, text):
        self.options["on_heard"](text)

    def state(self, state):
        self.options["on_state"](state)

    def interrupted(self):
        self.options["on_interrupt"]()

    def finished(self, why=""):
        self.options["on_ended"](why)


def bridge(tmp_path, *capabilities, text="Open my calendar.", check=lambda: ""):
    policy = Policy()
    for capability in capabilities:
        policy.grant(capability)
    listener, speaker = FakeListener(policy, text), FakeSpeaker(policy)
    voice = VoiceBridge(lambda: policy, store=VoiceStore(tmp_path / "voice.json"),
                        listener=listener, speaker=speaker, check=check, make_call=FakeCall)
    return voice, policy, listener, speaker


def in_a_call(tmp_path, **chat):
    voice, policy, listener, speaker = bridge(tmp_path, "audio.record", "audio.play")
    talk = FakeChat(**chat)
    voice.follow(talk)
    assert voice.startCall(), voice.note
    return voice, policy, speaker, talk, FakeCall.made[-1]


# -- listening -------------------------------------------------------------------------------------


def test_without_the_files_nothing_opens_and_the_reason_is_shown(app, tmp_path):
    voice, _, listener, _ = bridge(tmp_path, "audio.record", "audio.play",
                                   check=lambda: "The voice files are not in place: x.")
    assert not voice.available and "not in place" in voice.unavailableReason
    assert not voice.startListening() and listener.started == 0
    assert not voice.speak("Hi.") and "not in place" in voice.note


def test_without_listen_the_microphone_stays_shut(app, tmp_path):
    voice, _, listener, _ = bridge(tmp_path)
    assert not voice.canListen and "Listen has not been allowed" in voice.listenBlocked
    assert not voice.startListening()
    assert listener.started == 0 and not voice.listening
    assert "Listen has not been allowed" in voice.note


def test_a_press_hears_what_was_said(app, tmp_path):
    voice, _, listener, _ = bridge(tmp_path, "audio.record")
    heard = []
    voice.heard.connect(heard.append)
    assert voice.startListening() and voice.listening
    voice.stopListening()
    assert not voice.listening and voice.transcribing
    assert pump_until(app, lambda: heard)
    assert heard == ["Open my calendar."] and not voice.transcribing and voice.note == ""
    voice.close()


def test_hearing_nothing_says_so_and_sends_nothing(app, tmp_path):
    voice, _, _, _ = bridge(tmp_path, "audio.record", text="")
    heard = []
    voice.heard.connect(heard.append)
    voice.startListening()
    voice.stopListening()
    assert pump_until(app, lambda: not voice.transcribing)
    assert heard == [] and voice.note == "Nothing was heard."


def test_a_failure_to_make_it_out_is_shown(app, tmp_path):
    voice, _, _, _ = bridge(tmp_path, "audio.record",
                            text=VoiceError("Whisper could not make out what was said."))
    voice.startListening()
    voice.stopListening()
    assert pump_until(app, lambda: not voice.transcribing)
    assert "could not make out" in voice.note


def test_withdrawing_listen_closes_the_microphone_at_once(app, tmp_path):
    voice, policy, listener, _ = bridge(tmp_path, "audio.record")
    heard = []
    voice.heard.connect(heard.append)
    voice.startListening()
    policy.revoke("audio.record")
    assert pump_until(app, lambda: not voice.listening, timeout=1.0)
    assert listener.cancelled == 1 and listener.stopped == 0 and heard == []
    assert "withdrawn" in voice.note


def test_a_withdrawal_through_the_permissions_screen_is_acted_on_too(app, tmp_path):
    voice, policy, listener, _ = bridge(tmp_path, "audio.record")
    voice.startListening()
    policy.revoke("audio.record")
    voice.refresh()
    assert not voice.listening and listener.cancelled == 1


def test_reaching_the_limit_stops_and_keeps_what_was_heard(app, tmp_path):
    voice, _, listener, _ = bridge(tmp_path, "audio.record")
    heard = []
    voice.heard.connect(heard.append)
    voice.startListening()
    listener.microphone.full = True
    assert pump_until(app, lambda: heard)
    assert listener.stopped == 1 and listener.cancelled == 0


def test_the_level_is_shown_while_the_microphone_is_open(app, tmp_path):
    voice, _, listener, _ = bridge(tmp_path, "audio.record")
    voice.startListening()
    listener.microphone.level = 0.6
    assert pump_until(app, lambda: voice.level == pytest.approx(0.6), timeout=1.0)
    voice.cancelListening()
    assert voice.level == 0.0 and not voice.listening


def test_talking_over_akira_stops_it(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path, "audio.record", "audio.play")
    assert voice.speak("A long answer.") and voice.speaking
    voice.startListening()
    assert not voice.speaking and speaker.stops == 1


def test_a_second_press_waits_for_the_first_to_be_made_out(app, tmp_path):
    voice, _, listener, _ = bridge(tmp_path, "audio.record")
    voice.startListening()
    voice.stopListening()
    # No events have run, so the first is still being made out.
    assert not voice.startListening() and voice.note == "Still making out what was said."
    assert listener.started == 1
    pump_until(app, lambda: not voice.transcribing)
    assert voice.startListening()
    voice.cancelListening()


# -- speaking ----------------------------------------------------------------------------------------


def test_nothing_is_said_without_speak(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path)
    assert not voice.canSpeak and not voice.speak("Hello.")
    assert speaker.said == [] and "Speak has not been allowed" in voice.note


def test_speaking_ends_when_the_speaker_says_so(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path, "audio.play")
    assert voice.speak("Hello.")
    assert speaker.said == [("Hello.", "af_heart", 1.0)]
    speaker.finish("")
    assert pump_until(app, lambda: not voice.speaking)
    assert voice.note == ""


def test_a_problem_while_speaking_is_shown_but_stopping_is_not(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path, "audio.play")
    voice.speak("Hello.")
    speaker.finish("The speakers could not be used: gone")
    assert pump_until(app, lambda: not voice.speaking)
    assert "speakers could not be used" in voice.note
    voice.clearNote()
    voice.speak("Again.")
    speaker.finish(STOPPED)
    assert pump_until(app, lambda: not voice.speaking)
    assert voice.note == ""


def test_what_a_stopped_one_reports_does_not_end_the_next(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path, "audio.play")
    voice.speak("First.")
    first = speaker.done[-1]
    voice.speak("Second.")
    threading.Thread(target=first, args=(STOPPED,)).start()
    pump_until(app, lambda: False, timeout=0.2)
    assert voice.speaking


def test_replies_are_read_only_when_asked_for(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path, "audio.play")
    talk = FakeChat()
    voice.follow(talk)
    talk.reply("An answer. And more.")
    assert speaker.readings == []
    voice.setReadAloud(True)
    talk.reply("An answer. And more.")
    [reading] = speaker.readings
    assert reading.pieces == ["An answer.", "And more."] and reading.finished


def test_a_reply_is_read_as_it_streams_in(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path, "audio.play")
    talk = FakeChat()
    voice.follow(talk)
    voice.setReadAloud(True)
    talk.replyGrew.emit("The weather")
    [reading] = speaker.readings
    assert reading.pieces == [] and voice.speaking
    talk.replyGrew.emit("The weather is fine. Tomorrow")
    assert reading.pieces == ["The weather is fine."]
    talk.replyGrew.emit("The weather is fine. Tomorrow it rains. And")
    assert reading.pieces == ["The weather is fine.", "Tomorrow it rains."]
    talk.reply(whole="The weather is fine. Tomorrow it rains. And then snow.")
    assert reading.pieces[-1] == "And then snow." and reading.finished


def test_a_stopped_or_failed_reply_is_read_no_further(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path, "audio.play")
    talk = FakeChat()
    voice.follow(talk)
    voice.setReadAloud(True)
    talk.replyGrew.emit("One. Two")
    talk.reply(whole="")
    [reading] = speaker.readings
    assert reading.stopped and not reading.finished


def test_a_reply_that_cannot_be_read_says_why_once(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path)
    talk = FakeChat()
    voice.follow(talk)
    voice.setReadAloud(True)
    talk.replyGrew.emit("One. Two")
    assert "Speak has not been allowed" in voice.note
    voice.clearNote()
    talk.replyGrew.emit("One. Two. Three")
    assert voice.note == "" and speaker.readings == []


def test_a_voice_can_be_heard_before_it_is_chosen(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path, "audio.play")
    assert voice.previewVoice("bm_george")
    assert speaker.said == [(SAMPLE, "bm_george", 1.0)] and voice.voice == "af_heart"


# -- the choices ------------------------------------------------------------------------------------


def test_the_choices_are_kept(app, tmp_path):
    voice, _, _, _ = bridge(tmp_path, "audio.play")
    assert [v["id"] for v in voice.voices][0] == "af_heart" and len(voice.voices) == 6
    changed = []
    voice.settingsChanged.connect(lambda: changed.append(1))
    voice.setVoice("bf_emma")
    voice.setVoice("nobody")
    voice.setSpeed(1.3)
    voice.setReadAloud(True)
    assert (voice.voice, voice.speed, voice.readAloud) == ("bf_emma", 1.3, True)
    assert len(changed) == 3
    assert VoiceStore(tmp_path / "voice.json").load() == VoiceSettings("bf_emma", 1.3, True)


def test_turning_read_aloud_off_stops_the_reading(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path, "audio.play")
    talk = FakeChat()
    voice.follow(talk)
    voice.setReadAloud(True)
    talk.replyGrew.emit("A long answer. With more")
    assert voice.speaking
    voice.setReadAloud(False)
    assert not voice.speaking and speaker.stops == 1


def test_the_shell_offers_voice_and_hands_it_replies_and_grant_changes(app, tmp_path,
                                                                        monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path))
    from akira.ui import shell

    ctx = shell.build_context(persist=False)
    try:
        assert ctx.as_context()["Voice"] is ctx.voice
        ctx.voice.setReadAloud(True)
        # Nothing may be played here, so the reply reaching it shows as why not.
        ctx.chat.replyGrew.emit("The answer. More")
        assert ctx.voice.note and not ctx.voice.speaking
        # It follows the chat, so what stops a call is the grants, not the chat.
        assert "no conversation" not in ctx.voice.callBlocked
        assert ctx.voice.callBlocked
        refreshed = []
        ctx.voice.stateChanged.connect(lambda: refreshed.append(1))
        ctx.permissions.grantsChanged.emit()
        assert refreshed
    finally:
        ctx.voice.close()


def test_closing_shuts_the_microphone_and_stops_speaking(app, tmp_path):
    voice, _, listener, speaker = bridge(tmp_path, "audio.record", "audio.play")
    voice.startListening()
    voice.close()
    assert listener.cancelled == 1 and speaker.stops >= 1
    assert not voice.startListening() and not voice.speak("Hi.")


# -- a call -----------------------------------------------------------------------------------------


def test_a_call_needs_a_chat_and_both_grants(app, tmp_path):
    voice, _, _, _ = bridge(tmp_path, "audio.record", "audio.play")
    assert "no conversation" in voice.callBlocked and not voice.startCall()
    voice, _, _, _ = bridge(tmp_path, "audio.record")
    voice.follow(FakeChat())
    assert "A call needs to speak" in voice.callBlocked
    made = len(FakeCall.made)
    assert not voice.startCall() and len(FakeCall.made) == made and not voice.inCall


def test_what_a_call_hears_is_sent_and_the_reply_read_as_it_comes(app, tmp_path):
    voice, _, speaker, talk, call = in_a_call(tmp_path)
    assert call.started and voice.inCall and voice.callState == "listening"
    call.hear("What is the weather tomorrow?")
    assert talk.sent == ["What is the weather tomorrow?"]
    talk.reply("Sunny. Then", whole="Sunny. Then rain.")
    [reading] = speaker.readings
    assert reading.pieces == ["Sunny.", "Then rain."] and reading.finished
    assert call.answers == 1


def test_a_call_reads_replies_whatever_read_aloud_says(app, tmp_path):
    voice, _, speaker, talk, call = in_a_call(tmp_path)
    assert not voice.readAloud
    call.hear("Hello.")
    talk.reply("Hi there.")
    assert speaker.readings


def test_the_newest_thing_said_wins_over_a_reply_under_way(app, tmp_path):
    voice, _, _, talk, call = in_a_call(tmp_path)
    call.hear("First question.")
    call.hear("Actually, something else.")
    assert talk.sent == ["First question."] and talk.stops == 1
    talk.reply(whole="")
    assert talk.sent == ["First question.", "Actually, something else."]


def test_a_chat_that_answers_at_once_leaves_the_call_listening(app, tmp_path):
    voice, _, _, talk, call = in_a_call(tmp_path, answers_at_once=True)
    call.hear("Hello?")
    assert call.answers == 1


def test_talking_over_akira_stops_it_and_the_reply(app, tmp_path):
    voice, _, speaker, talk, call = in_a_call(tmp_path)
    call.hear("Tell me a long story.")
    talk.replyGrew.emit("Once upon a time. There")
    assert voice.speaking
    call.interrupted()
    assert not voice.speaking and speaker.stops >= 1 and talk.stops == 1


def test_the_state_of_the_call_is_shown(app, tmp_path):
    voice, _, _, _, call = in_a_call(tmp_path)
    changed = []
    voice.callChanged.connect(lambda: changed.append(voice.callState))
    call.state("hearing")
    call.state("thinking")
    assert changed == ["hearing", "thinking"]


def test_muting_closes_the_microphone_and_says_so(app, tmp_path):
    voice, _, _, _, call = in_a_call(tmp_path)
    voice.setMuted(True)
    assert call.muted and voice.muted
    call.refuse_unmute = "Not permitted: Listen has not been allowed."
    voice.setMuted(False)
    assert voice.muted and "Listen" in voice.note
    call.refuse_unmute = ""
    voice.setMuted(False)
    assert not voice.muted


def test_the_meter_follows_the_call(app, tmp_path):
    voice, _, _, _, call = in_a_call(tmp_path)
    assert pump_until(app, lambda: voice.level == pytest.approx(0.25), timeout=1.0)
    voice.setMuted(True)
    assert pump_until(app, lambda: voice.level == 0.0, timeout=1.0)


def test_push_to_talk_waits_for_the_call_to_end(app, tmp_path):
    voice, _, _, _, call = in_a_call(tmp_path)
    assert not voice.startListening() and "call is listening" in voice.note


def test_ending_the_call_closes_it_without_waiting(app, tmp_path):
    voice, _, speaker, talk, call = in_a_call(tmp_path)
    call.hear("Hello.")
    talk.replyGrew.emit("Hi. How")
    voice.endCall()
    assert call.ended and call.end_waited is False
    assert not voice.inCall and voice.callState == "" and not voice.speaking


def test_a_call_that_ends_itself_says_why(app, tmp_path):
    voice, _, _, _, call = in_a_call(tmp_path)
    call.finished("Listening was withdrawn, so the call ended.")
    assert not voice.inCall and "withdrawn" in voice.note


def test_what_an_old_call_says_does_not_touch_the_next(app, tmp_path):
    voice, _, _, talk, first = in_a_call(tmp_path)
    voice.endCall()
    assert voice.startCall()
    second = FakeCall.made[-1]
    first.hear("From the old call.")
    first.finished("")
    assert talk.sent == [] and voice.inCall
    second.hear("From the new one.")
    assert talk.sent == ["From the new one."]


def test_the_headphones_choice_reaches_the_call(app, tmp_path):
    voice, _, _, _, call = in_a_call(tmp_path)
    assert call.interrupt_by_voice is False
    voice.setInterruptByVoice(True)
    assert call.interrupt_by_voice is True and voice.interruptByVoice
    voice.endCall()
    voice.startCall()
    assert FakeCall.made[-1].interrupt_by_voice is True


def test_closing_akira_ends_the_call(app, tmp_path):
    voice, _, _, _, call = in_a_call(tmp_path)
    voice.close()
    assert call.ended and call.end_waited is True
