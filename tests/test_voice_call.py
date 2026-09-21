"""A live call (D3): the microphone open until the person ends the call, and no longer.

The microphone, Whisper and the speakers are fakes, except in the last test,
where Kokoro's voice is played into a call and real Whisper makes it out. What
is tested is where speech is found to start and stop, when what is heard is
sent, when the microphone is shut, and what ends a call.
"""

from __future__ import annotations

import json
import threading
import time
import types

import numpy as np
import pytest

from akira.core.permissions import AuditLog, Policy
from akira.core.voice import VoiceError
from akira.core.voice import call as calls
from akira.core.voice.call import (ENDED, FRAME, LISTENING, MUTED, THINKING, Call, Endpointer,
                                   LiveMicrophone)
from akira.core.voice.listen import SAMPLE_RATE


def tone(seconds, loudness=0.2):
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (loudness * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def quiet(seconds):
    rng = np.random.default_rng(int(seconds * 1000))
    return (rng.standard_normal(int(seconds * SAMPLE_RATE)) * 0.001).astype(np.float32)


def feed_in_blocks(endpointer, audio, size=1000):
    events = []
    for start in range(0, audio.size, size):
        events += endpointer.feed(audio[start:start + size])
    return events


# -- where speech starts and stops ---------------------------------------------------------------


def test_a_quiet_room_is_not_speech():
    assert feed_in_blocks(Endpointer(), quiet(3)) == []


def test_something_said_is_found_whole_with_a_little_either_side():
    events = feed_in_blocks(Endpointer(), np.concatenate([quiet(1), tone(1.2), quiet(1.5)]))
    assert [kind for kind, _ in events] == ["began", "ended"]
    audio = events[1][1]
    # The speech, a little from before it began, and a little of the quiet after.
    assert 1.2 <= audio.size / SAMPLE_RATE <= 1.2 + 0.3 + 0.25


def test_a_cough_is_not_worth_hearing():
    events = feed_in_blocks(Endpointer(), np.concatenate([quiet(1), tone(0.25), quiet(1.5)]))
    assert events in ([], [("began", None), ("ended", None)])
    assert all(audio is None for _, audio in events)


def test_a_click_does_not_begin_anything():
    assert feed_in_blocks(Endpointer(), np.concatenate([quiet(1), tone(0.09), quiet(1)])) == []


def test_a_pause_for_breath_does_not_end_it():
    said = np.concatenate([quiet(1), tone(0.8), quiet(0.4), tone(0.8), quiet(1.5)])
    events = feed_in_blocks(Endpointer(), said)
    assert [kind for kind, _ in events] == ["began", "ended"]
    assert events[1][1].size / SAMPLE_RATE >= 2.0


def test_talking_without_end_is_sent_at_the_limit():
    events = feed_in_blocks(Endpointer(), np.concatenate([quiet(0.5), tone(35)]))
    ended = [audio for kind, audio in events if kind == "ended"]
    assert len(ended) == 1
    assert ended[0].size <= calls.MAX_UTTERANCE_SECONDS * SAMPLE_RATE + FRAME


def test_a_steady_hum_is_the_room_not_speech():
    hum = (0.02 * np.sin(2 * np.pi * 60 * np.arange(4 * SAMPLE_RATE) / SAMPLE_RATE))
    assert feed_in_blocks(Endpointer(), hum.astype(np.float32)) == []


# -- the microphone, left open -------------------------------------------------------------------


class FakeInput:
    def __init__(self, samplerate, callback, blocksize=0, **options):
        self.samplerate, self.callback, self.blocksize = samplerate, callback, blocksize
        self.started = self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def hear(self, samples):
        self.callback(np.asarray(samples, np.float32).reshape(-1, 1), len(samples), None, None)


class FakeDevices:
    def __init__(self, sixteen_k=True):
        self.sixteen_k, self.streams = sixteen_k, []

    def check_input_settings(self, **settings):
        if not self.sixteen_k:
            raise ValueError("Invalid sample rate")

    def query_devices(self, device=None, kind=None):
        return {"default_samplerate": 48_000.0}

    def InputStream(self, samplerate, callback, **options):  # noqa: N802 - sounddevice's name
        stream = FakeInput(samplerate, callback, **options)
        self.streams.append(stream)
        return stream


def test_the_live_microphone_hands_over_what_it_hears_as_it_hears_it():
    devices = FakeDevices()
    mic = LiveMicrophone(sounddevice=devices)
    mic.start()
    [stream] = devices.streams
    assert stream.started and stream.blocksize == FRAME
    stream.hear(tone(0.03))
    assert mic.read(0.1).size == FRAME and mic.level > 0
    assert mic.read(0.01) is None


def test_the_live_microphone_brings_another_rate_to_whispers():
    devices = FakeDevices(sixteen_k=False)
    mic = LiveMicrophone(sounddevice=devices)
    mic.start()
    [stream] = devices.streams
    assert stream.samplerate == 48_000 and stream.blocksize == 3 * FRAME
    stream.hear(np.zeros(3 * FRAME, np.float32))  # 30 ms at 48 kHz
    assert mic.read(0.1).size == FRAME


def test_shutting_the_live_microphone_throws_away_what_was_not_read():
    devices = FakeDevices()
    mic = LiveMicrophone(sounddevice=devices)
    mic.start()
    devices.streams[0].hear(tone(0.03))
    mic.stop()
    assert devices.streams[0].closed and not mic.open and mic.read(0.01) is None


def test_a_backlog_nobody_reads_keeps_only_the_newest():
    devices = FakeDevices()
    mic = LiveMicrophone(sounddevice=devices)
    mic.start()
    for n in range(calls.BACKLOG_BLOCKS + 5):
        devices.streams[0].hear(np.full(FRAME, n / 1000, np.float32))
    first = mic.read(0.01)
    assert first[0] == pytest.approx(5 / 1000)


# -- the call ------------------------------------------------------------------------------------


class ScriptedMicrophone:
    """Hands over what the test puts in, a frame at a time, as a microphone would."""

    def __init__(self):
        self.blocks: list = []
        self.open = False
        self.opened = self.closed = 0
        self.level = 0.0
        self.lock = threading.Lock()

    def say(self, audio):
        with self.lock:
            self.blocks += [audio[i:i + FRAME] for i in range(0, audio.size, FRAME)]

    def start(self):
        self.open = True
        self.opened += 1

    def stop(self):
        self.open = False
        self.closed += 1
        with self.lock:
            self.blocks.clear()

    def read(self, timeout=0.1):
        with self.lock:
            if self.open and self.blocks:
                return self.blocks.pop(0)
        time.sleep(min(timeout, 0.005))
        return None


class FakeSpeaker:
    def __init__(self):
        self.speaking = False
        self.stops = 0
        self.synthesizer = types.SimpleNamespace(ready="")

    def stop(self, wait=1.0):
        self.stops += 1
        self.speaking = False


class FakeTranscriber:
    ready = ""

    def __init__(self, text="What is on my calendar tomorrow?"):
        self.text, self.given = text, []

    def transcribe(self, audio):
        self.given.append(audio)
        return self.text


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    return predicate()


class Recorder:
    def __init__(self):
        self.heard, self.states, self.ended, self.interrupted = [], [], [], 0

    def interrupt(self):
        self.interrupted += 1


def a_call(tmp_path, *grants, text="What is on my calendar tomorrow?", **options):
    policy = Policy()
    for capability in grants or ("audio.record", "audio.play"):
        policy.grant(capability)
    mic, speaker, transcriber, seen = ScriptedMicrophone(), FakeSpeaker(), FakeTranscriber(text), Recorder()
    audit = AuditLog(tmp_path / "audit.jsonl")
    call = Call(lambda: policy, transcriber, speaker, microphone=mic, audit=audit,
                on_heard=seen.heard.append, on_state=seen.states.append,
                on_interrupt=seen.interrupt, on_ended=seen.ended.append, **options)
    return call, policy, mic, speaker, transcriber, seen, audit


def logged(audit):
    return [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]


def test_a_call_needs_listen_and_speak(tmp_path):
    for grants in (("audio.record",), ("audio.play",)):
        call, _, mic, *_, audit = a_call(tmp_path, *grants)
        with pytest.raises(VoiceError, match="A call needs to"):
            call.start()
        assert mic.opened == 0 and not call.active
    assert all(entry["allowed"] is False for entry in logged(audit))


def test_what_is_said_is_heard_and_sent_once(tmp_path):
    call, _, mic, _, transcriber, seen, _ = a_call(tmp_path)
    call.start()
    try:
        assert wait_for(lambda: call.state == LISTENING)
        mic.say(np.concatenate([quiet(0.5), tone(1.0), quiet(1.2)]))
        assert wait_for(lambda: seen.heard)
        assert seen.heard == ["What is on my calendar tomorrow?"]
        assert call.state == THINKING and "hearing" in seen.states
    finally:
        call.end()


def test_while_waiting_for_the_reply_nothing_more_is_heard(tmp_path):
    call, _, mic, _, transcriber, seen, _ = a_call(tmp_path)
    call.start()
    try:
        mic.say(np.concatenate([quiet(0.5), tone(1.0), quiet(1.2)]))
        assert wait_for(lambda: seen.heard)
        mic.say(np.concatenate([tone(1.0), quiet(1.2)]))
        assert wait_for(lambda: not mic.blocks)
        time.sleep(0.1)
        assert len(transcriber.given) == 1
        call.answered()
        assert wait_for(lambda: call.state == LISTENING)
        time.sleep(calls.ECHO_TAIL_SECONDS + 0.1)
        mic.say(np.concatenate([quiet(0.5), tone(1.0), quiet(1.2)]))
        assert wait_for(lambda: len(seen.heard) == 2)
    finally:
        call.end()


def test_nothing_heard_while_akira_speaks_on_the_speakers(tmp_path):
    call, _, mic, speaker, transcriber, seen, _ = a_call(tmp_path)
    call.start()
    try:
        speaker.speaking = True
        mic.say(np.concatenate([quiet(0.3), tone(1.0), quiet(1.2)]))
        assert wait_for(lambda: not mic.blocks)
        time.sleep(0.1)
        assert transcriber.given == [] and speaker.stops == 0 and seen.interrupted == 0
    finally:
        call.end()


def test_with_headphones_talking_over_akira_stops_it(tmp_path):
    call, _, mic, speaker, transcriber, seen, _ = a_call(tmp_path, interrupt_by_voice=True)
    call.start()
    try:
        mic.say(quiet(0.5))
        assert wait_for(lambda: not mic.blocks)
        speaker.speaking = True
        mic.say(np.concatenate([tone(1.0), quiet(1.2)]))
        assert wait_for(lambda: seen.heard)
        assert speaker.stops >= 1 and seen.interrupted == 1
    finally:
        call.end()


def test_muting_shuts_the_microphone_and_unmuting_opens_it(tmp_path):
    call, _, mic, *_ = a_call(tmp_path)
    call.start()
    try:
        call.mute()
        assert not mic.open and call.muted
        assert wait_for(lambda: call.state == MUTED)
        call.unmute()
        assert mic.open and not call.muted
        assert wait_for(lambda: call.state == LISTENING)
    finally:
        call.end()


@pytest.mark.parametrize("withdrawn, why", [("audio.record", "Listening was withdrawn"),
                                            ("audio.play", "Speaking was withdrawn")])
def test_withdrawing_either_permission_ends_the_call(tmp_path, withdrawn, why):
    call, policy, mic, _, _, seen, _ = a_call(tmp_path)
    call.start()
    policy.revoke(withdrawn)
    assert wait_for(lambda: seen.ended)
    assert why in seen.ended[0] and not mic.open and call.state == ENDED and not call.active


def test_ending_shuts_everything_and_logs_no_words(tmp_path):
    call, _, mic, speaker, _, seen, audit = a_call(tmp_path)
    call.start()
    mic.say(np.concatenate([quiet(0.5), tone(1.0), quiet(1.2)]))
    assert wait_for(lambda: seen.heard)
    call.end()
    assert not mic.open and speaker.stops >= 1 and seen.ended == [""]
    assert seen.states[-1] == ENDED and not call.active
    started, ended = logged(audit)
    assert started["action"] == ended["action"] == "call"
    assert ended["detail"]["said"] == 1 and "seconds" in ended["detail"]
    assert "calendar" not in audit.path.read_text(encoding="utf-8")
    call.end()  # a second end changes nothing
    assert seen.ended == [""]


# -- for real ------------------------------------------------------------------------------------


def test_a_call_hears_kokoro_through_whisper(tmp_path):
    from akira.core import voice
    from akira.core.voice.listen import Transcriber, resample
    from akira.core.voice.speak import Synthesizer

    if voice.unavailable():
        pytest.skip(voice.unavailable())
    samples, rate = Synthesizer().synthesize("Add milk to the shopping list.", "bf_emma")
    transcriber = Transcriber()
    call, _, mic, _, _, seen, _ = a_call(tmp_path)
    call._transcriber = transcriber
    try:
        call.start()
        mic.say(np.concatenate([quiet(0.5), resample(samples, rate), quiet(1.2)]))
        assert wait_for(lambda: seen.heard, timeout=60)
        words = seen.heard[0].lower()
        assert all(word in words for word in ("milk", "shopping", "list")), seen.heard
    finally:
        call.end()
        transcriber.close()
