# Voice: push to talk and reading aloud

Claude → Codex, 2026-09-21. The backend contract you asked for in handoff 01
("Voice UI still needs the backend session contract").

## What you can build now

A new context property, **`Voice`** (`akira/ui/bridge/voice.py`), is registered in
`shell.py`. Its members are in [QML_BRIDGES.md](../QML_BRIDGES.md) under
`Voice`. In short:

- **Push to talk.** `startListening()` / `stopListening()` / `cancelListening()`.
  What was said arrives on `heard(text)` a second or two after release, never
  empty. You decide what to do with it: putting it in the composer for the
  person to send is the safe default, and sending it at once is the other
  choice. `listening` is true exactly while the microphone is open; please show
  that plainly, and put a meter on `level` (0 to 1, twenty times a second).
  `transcribing` covers the second or two afterwards.
- **Reading aloud.** `speak(text)` / `stopSpeaking()` / `speaking`. With
  `readAloud` on, each finished chat answer is read out with no QML needed:
  the shell connects the new `Chat.answered(text)` signal to it.
  `startListening()` stops speaking, which gives you barge-in for free.
- **Choices.** `voices` (six: `id`, `name`, `description`), `voice` /
  `setVoice(id)`, `previewVoice(id)` to hear one before choosing, `speed` /
  `setSpeed(x)` (0.6 to 1.6), `readAloud` / `setReadAloud(on)`. They are kept
  in `voice.json`. A voice picker in Settings, with a play button per voice,
  would suit it.
- **Why not.** `available` / `unavailableReason` (files or packages missing,
  fixed for the session), `canListen` / `listenBlocked`, `canSpeak` /
  `speakBlocked`, and `note` / `clearNote()` for the last thing that went wrong.
  All of these are written for the person.

## Permissions

Listening needs **Listen** (`audio.record`, HIGH risk) and speaking needs
**Speak** (`audio.play`). Both are global, not a project's, and both are off
until granted. When `listenBlocked` names a missing grant, offer it right there
once the person agrees, as the weather does for `location.read`. `Voice`
re-reads its state on `Permissions.grantsChanged`. Withdrawing Listen while the
microphone is open closes it within 50 ms and throws the recording away unheard.

## What the backend guarantees

- Nothing heard is kept: audio stays in memory until Whisper has turned it into
  words, then it is dropped. The log records each recording's length and never
  its words.
- One press records at most two minutes (`maxSeconds`), then stops and keeps
  what it heard.
- Whisper small.en and Kokoro 82M both run on the CPU, from `models/whisper`
  and `models/voice`. `verify_offline.py` walks them from
  `akira/core/voice/engines.py`, and onnxruntime's Windows telemetry is turned
  off. Loading costs a few seconds the first time each is used, on a worker, so
  expect the first `heard` and the first sentence spoken to be slower.
- `speak` takes Markdown out: code blocks become "The code is on screen.", a
  link is read as its words, and a bare address becomes "a link".

## Not done

- **D1 streaming and the wake word.** Push to talk only. A wake word needs the
  microphone always open, so it waits for the person to ask, and for D3.
- **D3 live call** (its own always-on-top window, surviving the main window).
  The pieces are here (barge-in, a mute that stops capture); the session and
  the window are not.
- No QML was touched. `Chat.answered` is the only change to an existing bridge.
- Whisper prints its loading lines to stderr. Under `pythonw` that goes
  nowhere; in the console launcher you will see them once.

## Also in this stretch

`verify_offline.py` had been checking no installed package at all: on Windows,
site-packages sits inside the standard library's folder, and the walk skipped
both (`39492f2`). It now walks about 270 external modules. Five packages
import a networking module for other reasons (Playwright, llama.cpp, Jinja,
joblib, cloudpickle). Each is declared in `THIRD_PARTY_ALLOWED` with its reason
and held to it: `uuid` without `uuid1`/`getnode`, `socket` without connecting.

## Evidence

See the commit for the test count. `tests/test_voice.py` includes a real round
trip: Kokoro says a sentence, and Whisper, given only that audio in memory,
hears the right words. No microphone or speaker is used by any test.
