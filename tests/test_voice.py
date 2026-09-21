"""Voice (D1, D2): heard by Whisper, spoken by Kokoro, on this computer alone.

The microphone and speakers are fakes: no test records the room or makes a
sound. Whisper and Kokoro are fakes too, except in the last test, which runs
them for real on the files under models/ when they are there, and only in
memory: Kokoro says a sentence and Whisper is asked what it heard.
"""

from __future__ import annotations

import json
import threading
import time
import types

import numpy as np
import pytest

from akira.core import voice
from akira.core.permissions import AuditLog, Policy
from akira.core.voice import VoiceError, listen, speak
from akira.core.voice.listen import SAMPLE_RATE, Listener, Microphone, Transcriber
from akira.core.voice.speak import STOPPED, Speaker, Synthesizer
from akira.core.voice.store import VoiceSettings, VoiceStore


def tone(seconds, loudness=0.2, rate=SAMPLE_RATE):
    t = np.arange(int(seconds * rate)) / rate
    return (loudness * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def granted(*capabilities):
    policy = Policy()
    for capability in capabilities:
        policy.grant(capability)
    return policy


# -- what is heard -------------------------------------------------------------------------------


def test_silence_and_a_quiet_room_are_not_speech():
    assert listen.speech_seconds(np.zeros(SAMPLE_RATE * 2, dtype=np.float32)) == 0.0
    hum = (np.random.default_rng(1).standard_normal(SAMPLE_RATE * 2) * 0.002).astype(np.float32)
    assert listen.speech_seconds(hum) < listen.MIN_SPEECH_SECONDS


def test_speech_in_a_quiet_room_is_measured():
    clip = np.concatenate([np.zeros(SAMPLE_RATE, np.float32), tone(1.0),
                           np.zeros(SAMPLE_RATE, np.float32)])
    assert 0.9 <= listen.speech_seconds(clip) <= 1.1


def test_talking_from_the_first_moment_to_the_last_is_still_speech():
    assert listen.speech_seconds(tone(1.5)) > 1.0


def test_a_recording_is_brought_to_whispers_rate():
    out = listen.resample(tone(1.0, rate=48_000), 48_000)
    assert out.dtype == np.float32 and abs(out.size - SAMPLE_RATE) <= 1


@pytest.mark.parametrize("said, kept", [
    (" Remind me to call the dentist.", "Remind me to call the dentist."),
    ("[BLANK_AUDIO]", ""),
    (" (music) Set a timer (upbeat music)", "Set a timer"),
    (" Thanks for watching!", ""),
    (" you", ""),
    (" Thank you.", "Thank you."),  # a person says this to an assistant
])
def test_what_whisper_invents_or_notes_is_dropped(said, kept):
    assert listen.clean(said) == kept


def test_silence_never_reaches_whisper(tmp_path):
    # The model is not there, so reaching Whisper would raise.
    transcriber = Transcriber(tmp_path / "missing.bin")
    assert transcriber.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32)) == ""
    with pytest.raises(VoiceError, match="not in place"):
        transcriber.transcribe(tone(1.0))


# -- the microphone ------------------------------------------------------------------------------


class FakeInput:
    def __init__(self, devices, samplerate, callback, **options):
        self.devices, self.samplerate, self.callback = devices, samplerate, callback
        self.started = self.closed = False
        devices.streams.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def abort(self):
        self.started = False

    def close(self):
        self.closed = True

    def hear(self, samples):
        self.callback(np.asarray(samples, np.float32).reshape(-1, 1), len(samples), None, None)


class FakeDevices:
    """sounddevice, as far as Akira uses it."""

    def __init__(self, sixteen_k=True, native=48_000):
        self.sixteen_k, self.native = sixteen_k, native
        self.streams: list = []
        self.played: list = []

    def check_input_settings(self, **settings):
        if not self.sixteen_k:
            raise ValueError("Invalid sample rate")

    def query_devices(self, device=None, kind=None):
        return {"default_samplerate": float(self.native)}

    def InputStream(self, samplerate, callback, **options):  # noqa: N802 - sounddevice's name
        return FakeInput(self, samplerate, callback, **options)

    def OutputStream(self, samplerate, **options):  # noqa: N802
        return FakeOutput(self, samplerate)


def test_the_microphone_hands_over_what_it_heard_and_keeps_nothing():
    devices = FakeDevices()
    mic = Microphone(sounddevice=devices)
    mic.start()
    [stream] = devices.streams
    assert stream.started and stream.samplerate == SAMPLE_RATE and mic.open
    stream.hear(tone(0.5))
    stream.hear(tone(0.5))
    assert mic.level > 0
    heard = mic.stop()
    assert heard.size == SAMPLE_RATE and stream.closed and not mic.open
    assert mic.stop().size == 0 and mic.level == 0.0


def test_the_microphone_stops_keeping_at_its_limit():
    devices = FakeDevices()
    mic = Microphone(max_seconds=1, sounddevice=devices)
    mic.start()
    devices.streams[0].hear(tone(0.8))
    assert not mic.full
    devices.streams[0].hear(tone(0.8))
    assert mic.full
    assert mic.stop().size == SAMPLE_RATE


def test_a_microphone_that_will_not_do_16_khz_is_recorded_at_its_own_rate():
    devices = FakeDevices(sixteen_k=False, native=48_000)
    mic = Microphone(sounddevice=devices)
    mic.start()
    assert devices.streams[0].samplerate == 48_000
    devices.streams[0].hear(tone(1.0, rate=48_000))
    assert abs(mic.stop().size - SAMPLE_RATE) <= 1


def test_a_microphone_that_will_not_open_says_so():
    class Broken(FakeDevices):
        def InputStream(self, samplerate, callback, **options):  # noqa: N802
            raise OSError("no device")

    with pytest.raises(VoiceError, match="microphone could not be opened: no device"):
        Microphone(sounddevice=Broken()).start()


def test_a_microphone_that_opens_but_will_not_start_is_closed_again():
    class Stuck(FakeInput):
        def start(self):
            raise OSError("device busy")

    class Devices(FakeDevices):
        def InputStream(self, samplerate, callback, **options):  # noqa: N802
            return Stuck(self, samplerate, callback)

    devices = Devices()
    mic = Microphone(sounddevice=devices)
    with pytest.raises(VoiceError, match="device busy"):
        mic.start()
    assert devices.streams[0].closed and not mic.open


def test_a_microphone_that_complains_on_stopping_is_still_closed():
    class Grumpy(FakeInput):
        def stop(self):
            raise OSError("underflow")

    class Devices(FakeDevices):
        def InputStream(self, samplerate, callback, **options):  # noqa: N802
            return Grumpy(self, samplerate, callback)

    devices = Devices()
    mic = Microphone(sounddevice=devices)
    mic.start()
    devices.streams[0].hear(tone(0.5))
    assert mic.stop().size == SAMPLE_RATE // 2
    assert devices.streams[0].closed and not mic.open


# -- a press of the button -----------------------------------------------------------------------


class FakeTranscriber:
    def __init__(self, text="Set a timer for ten minutes."):
        self.text, self.given = text, []
        self.ready = ""

    def transcribe(self, audio):
        self.given.append(audio)
        return self.text

    def load(self):
        pass

    def close(self):
        pass


def listener(tmp_path, policy, text="Set a timer for ten minutes."):
    devices = FakeDevices()
    audit = AuditLog(tmp_path / "audit.jsonl")
    heard = Listener(lambda: policy, audit, FakeTranscriber(text), Microphone(sounddevice=devices))
    return heard, devices, audit


def logged(audit):
    return [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]


def test_the_microphone_does_not_open_without_listen(tmp_path):
    heard, devices, audit = listener(tmp_path, Policy())
    with pytest.raises(VoiceError, match="Not permitted: Listen has not been allowed"):
        heard.start()
    assert devices.streams == [] and not heard.listening
    [entry] = logged(audit)
    assert entry["action"] == "listen" and entry["allowed"] is False


def test_what_was_said_comes_back_and_only_its_length_is_logged(tmp_path):
    heard, devices, audit = listener(tmp_path, granted("audio.record"))
    heard.start()
    devices.streams[0].hear(tone(1.0))
    result = heard.stop()
    assert result.text == "Set a timer for ten minutes." and result.seconds == pytest.approx(1.0)
    assert not heard.listening and devices.streams[0].closed
    [entry] = logged(audit)
    assert entry["allowed"] is True and entry["detail"] == {"seconds": 1.0}
    assert "timer" not in audit.path.read_text(encoding="utf-8")


def test_withdrawing_listen_while_the_microphone_is_open_throws_it_away(tmp_path):
    policy = granted("audio.record")
    heard, devices, audit = listener(tmp_path, policy)
    heard.start()
    devices.streams[0].hear(tone(1.0))
    policy.revoke("audio.record")
    with pytest.raises(VoiceError, match="withdrawn"):
        heard.stop()
    assert heard.transcriber.given == [] and devices.streams[0].closed
    assert logged(audit)[-1]["allowed"] is False


def test_cancelling_throws_away_what_was_heard(tmp_path):
    heard, devices, audit = listener(tmp_path, granted("audio.record"))
    heard.start()
    devices.streams[0].hear(tone(1.0))
    heard.cancel()
    assert heard.transcriber.given == [] and not heard.listening
    assert "thrown away" in logged(audit)[-1]["error"]


def test_nothing_about_voice_is_written_to_disk_but_the_log(tmp_path):
    heard, devices, _ = listener(tmp_path, granted("audio.record"))
    heard.start()
    devices.streams[0].hear(tone(1.0))
    heard.stop()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["audit.jsonl"]


# -- what is said --------------------------------------------------------------------------------


@pytest.mark.parametrize("written, heard", [
    ("**Bold** and *italic* and `code`.", "Bold and italic and code."),
    ("See [the forecast](https://example.com/weather) now.", "See the forecast now."),
    ("Go to https://example.com/a?b=c today.", "Go to a link today."),
    ("## Plans\n- one\n- two", "Plans. one. two."),
    ("Run this:\n```python\nimport os\nos.remove('x')\n```\nDone.",
     "Run this: The code is on screen. Done."),
    ("| a | b |\n|---|---|\n| 1 | 2 |", "a, b. 1, 2."),
    ("snake_case_names stay whole", "snake_case_names stay whole."),
    ("an _aside_ and __more__", "an aside and more."),
])
def test_what_is_written_for_the_eye_is_not_read_out(written, heard):
    assert speak.speakable(written) == heard


def test_text_is_spoken_a_sentence_at_a_time_and_long_ones_are_split():
    assert speak.pieces("One. Two? Three! Four") == ["One.", "Two?", "Three!", "Four"]
    long = ", ".join(["a phrase of some length"] * 30) + "."
    parts = speak.pieces(long)
    assert len(parts) > 1 and all(len(part) <= speak.MAX_PIECE for part in parts)
    assert " ".join(parts).split() == long.split()


def test_six_voices_and_the_default_is_the_first():
    assert len(speak.VOICES) == 6 and speak.DEFAULT_VOICE == "af_heart"
    assert len({v.id for v in speak.VOICES}) == 6
    assert speak.BY_ID["bf_emma"].language == "en-gb"
    assert speak.BY_ID["af_heart"].language == "en-us"


def test_every_voice_offered_is_in_the_voices_file():
    if not voice.KOKORO_VOICES.is_file():
        pytest.skip("the Kokoro voices file is not here")
    with np.load(voice.KOKORO_VOICES) as held:
        assert {v.id for v in speak.VOICES} <= set(held.files)


def test_kokoro_is_run_on_the_processor_alone(monkeypatch, tmp_path):
    made = {}

    class Options:
        pass

    def session(path, sess_options, providers):
        made.update(path=path, providers=providers, threads=sess_options.intra_op_num_threads)
        return "session"

    class Kokoro:
        @staticmethod
        def from_session(session, voices):
            made["voices"] = voices
            return types.SimpleNamespace(create=lambda text, **kw: (np.zeros(10, np.float32), 24000))

    runtime = types.SimpleNamespace(SessionOptions=Options, InferenceSession=session)
    monkeypatch.setattr(speak, "load_engines",
                        lambda: types.SimpleNamespace(onnxruntime=runtime, Kokoro=Kokoro))
    model, voices = tmp_path / "k.onnx", tmp_path / "v.bin"
    model.write_bytes(b"x")
    voices.write_bytes(b"x")
    samples, rate = Synthesizer(model, voices).synthesize("Hi.", "af_bella", speed=5)
    assert made["providers"] == ["CPUExecutionProvider"] and made["threads"] == speak.THREADS
    assert rate == 24000 and samples.dtype == np.float32


class FakeOutput:
    def __init__(self, devices, samplerate):
        self.devices, self.samplerate = devices, samplerate
        self.ended = ""

    def start(self):
        pass

    def write(self, block):
        self.devices.played.append(block.copy())
        time.sleep(0.005)

    def stop(self):
        self.ended = "stop"

    def abort(self):
        self.ended = "abort"

    def close(self):
        self.devices.streams.append(self)


class FakeSynthesizer:
    ready = ""

    def __init__(self, seconds=0.3, gate=None):
        self.seconds, self.gate, self.said = seconds, gate, []

    def synthesize(self, text, voice="af_heart", speed=1.0):
        if self.gate is not None:
            self.gate.wait(5)
        self.said.append(text)
        return np.full(int(24000 * self.seconds), 0.1, np.float32), 24000


def speaking(policy, synthesizer=None):
    devices = FakeDevices()
    synthesizer = synthesizer if synthesizer is not None else FakeSynthesizer()
    return Speaker(lambda: policy, synthesizer, devices), devices, synthesizer


def finish(speaker):
    done = threading.Event()
    reasons = []

    def ended(why):
        reasons.append(why)
        done.set()

    return ended, done, reasons


def test_nothing_is_said_without_speak(tmp_path):
    speaker, devices, synthesizer = speaking(Policy())
    with pytest.raises(VoiceError, match="Speak has not been allowed"):
        speaker.say("Hello.")
    assert synthesizer.said == [] and devices.played == []


def test_everything_is_said_in_order_and_the_speakers_drain(tmp_path):
    speaker, devices, synthesizer = speaking(granted("audio.play"))
    ended, done, reasons = finish(speaker)
    assert speaker.say("One. Two. Three.", on_done=ended)
    assert done.wait(5) and reasons == [""]
    assert synthesizer.said == ["One.", "Two.", "Three."]
    [stream] = devices.streams
    assert stream.ended == "stop"
    played = sum(block.size for block in devices.played)
    assert played == 3 * int(24000 * (0.3 + speak.PAUSE_SECONDS))


def test_stopping_is_at_once_and_what_was_left_is_not_played():
    speaker, devices, _ = speaking(granted("audio.play"), FakeSynthesizer(seconds=2.0))
    ended, done, reasons = finish(speaker)
    speaker.say("A long sentence. Another one.", on_done=ended)
    deadline = time.monotonic() + 5
    while not devices.played and time.monotonic() < deadline:
        time.sleep(0.01)
    started = time.monotonic()
    speaker.stop()
    assert done.wait(2) and reasons == [STOPPED]
    assert time.monotonic() - started < 0.5
    assert devices.streams[0].ended == "abort"
    assert sum(b.size for b in devices.played) < 24000 * 2


def test_withdrawing_speak_stops_at_the_next_sentence():
    policy = granted("audio.play")
    gate = threading.Event()
    speaker, devices, synthesizer = speaking(policy, FakeSynthesizer(seconds=0.1, gate=gate))
    ended, done, reasons = finish(speaker)
    speaker.say("One. Two. Three.", on_done=ended)
    policy.revoke("audio.play")
    gate.set()
    assert done.wait(5)
    assert reasons[0].startswith("Not permitted") and len(synthesizer.said) <= 1


def test_an_unknown_voice_or_nothing_to_say_says_nothing():
    speaker, devices, synthesizer = speaking(granted("audio.play"))
    with pytest.raises(VoiceError, match="no voice called"):
        speaker.say("Hello.", voice="someone_else")
    assert speaker.say("```\ncode only\n```") is True  # the code is said to be on screen
    speaker.stop()
    assert speaker.say("   ") is False


# -- the settings --------------------------------------------------------------------------------


def test_the_choice_is_kept_and_read_aloud_starts_off(tmp_path):
    store = VoiceStore(tmp_path / "voice.json")
    assert store.load() == VoiceSettings("af_heart", 1.0, False)
    store.save(VoiceSettings("bm_george", 1.2, True))
    assert store.load() == VoiceSettings("bm_george", 1.2, True)


@pytest.mark.parametrize("raw", ['{"voice": "nobody", "speed": 99, "read_aloud": "yes"}',
                                 "not json", '["a list"]'])
def test_a_damaged_choice_falls_back_to_what_is_safe(tmp_path, raw):
    path = tmp_path / "voice.json"
    path.write_text(raw, encoding="utf-8")
    settings = VoiceStore(path).load()
    assert settings.voice == "af_heart" and settings.read_aloud is False
    assert speak.SLOWEST <= settings.speed <= speak.FASTEST


# -- the one door --------------------------------------------------------------------------------


def test_voice_is_walked_by_the_offline_check():
    import verify_offline as vo

    assert "akira/core/voice/engines.py" in vo.ENTRY_POINTS
    source = (vo.REPO_ROOT / "akira/core/voice/engines.py").read_text(encoding="utf-8")
    # The low-level binding alone: pywhispercpp's own model class downloads.
    assert "import _pywhispercpp" in source and "pywhispercpp.model" not in source
    # onnxruntime's own reporting, through Windows rather than a socket, is off.
    assert "onnxruntime.disable_telemetry_events()" in source


def test_the_packages_own_downloader_is_found_on_disk_and_unreachable():
    import verify_offline as vo

    result = vo.ScanResult()
    vo.scan_installed_inventory(result)
    if not any(root.joinpath("pywhispercpp").is_dir() for root in vo._site_packages()):
        pytest.skip("pywhispercpp is not installed")
    assert any("pywhispercpp" in str(note.path) and "requests" in note.detail
               for note in result.notes)


# -- for real ------------------------------------------------------------------------------------


def test_kokoro_says_it_and_whisper_hears_it():
    if voice.unavailable():
        pytest.skip(voice.unavailable())
    synthesizer, transcriber = Synthesizer(), Transcriber()
    try:
        samples, rate = synthesizer.synthesize("Remind me to water the plants on Sunday.",
                                               "af_heart")
        heard = transcriber.transcribe(listen.resample(samples, rate))
    finally:
        transcriber.close()
    words = heard.lower()
    assert all(word in words for word in ("remind", "water", "plants", "sunday")), heard
