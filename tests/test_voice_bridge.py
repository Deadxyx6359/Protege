"""The `Voice` bridge (D1, D2): push to talk, reading aloud, and the chosen voice.

What listens and what speaks are fakes; `test_voice.py` tests the real ones.
What is tested here is what the interface is told, and when.
"""

from __future__ import annotations

import threading
import time
import types

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

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
        self.transcriber = types.SimpleNamespace(load=lambda: None, close=lambda: None)
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


class FakeSpeaker:
    def __init__(self, policy):
        self.policy = policy
        self.said, self.stops, self.done = [], 0, []

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


def bridge(tmp_path, *capabilities, text="Open my calendar.", check=lambda: ""):
    policy = Policy()
    for capability in capabilities:
        policy.grant(capability)
    listener, speaker = FakeListener(policy, text), FakeSpeaker(policy)
    voice = VoiceBridge(lambda: policy, store=VoiceStore(tmp_path / "voice.json"),
                        listener=listener, speaker=speaker, check=check)
    return voice, policy, listener, speaker


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


def test_answers_are_read_aloud_only_when_asked_for(app, tmp_path):
    voice, _, _, speaker = bridge(tmp_path, "audio.play")
    voice.readReply("An answer.")
    assert speaker.said == []
    voice.setReadAloud(True)
    voice.readReply("An answer.")
    assert speaker.said == [("An answer.", "af_heart", 1.0)]


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
    voice.setReadAloud(True)
    voice.readReply("A long answer.")
    voice.setReadAloud(False)
    assert not voice.speaking and speaker.stops == 1


def test_the_shell_offers_voice_and_hands_it_answers_and_grant_changes(app, tmp_path,
                                                                        monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path))
    from akira.ui import shell

    ctx = shell.build_context(persist=False)
    try:
        assert ctx.as_context()["Voice"] is ctx.voice
        read = []
        monkeypatch.setattr(ctx.voice, "_say", lambda text, voice: read.append(text) or True)
        ctx.voice.setReadAloud(True)
        ctx.chat.answered.emit("The answer.")
        assert read == ["The answer."]
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
