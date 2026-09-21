# Calls, and replies read as they stream

Claude → Codex, 2026-09-21. Follows handoff 41 (voice) the same day, which is
still the one to read first. This adds D3's backend and changes one thing in
that handoff: `Chat.answered` is gone.

## What you can build now

**A call** (D3). `Voice.startCall()` starts talking with Akira hands-free:
what the person says is sent to the chat as if typed, and the reply is read
aloud as it is written, until `Voice.endCall()`. The person chose **no wake
word**, so the microphone is open only during a call they started. Members are
in [QML_BRIDGES.md](../QML_BRIDGES.md) under `Voice` → "A call":
`startCall`, `callBlocked`, `endCall`, `inCall`, `callState` (`listening`,
`hearing`, `thinking`, `speaking`, `muted`), `muted` / `setMuted`, `level`, and
`interruptByVoice` / `setInterruptByVoice` (for headphones).

The plan asks for the call to live in **its own small always-on-top window
that survives the main window closing**. The call runs in the bridge, not in
any view, so that window only needs to show `callState` and `level`, and give
mute, stop-speaking and end. Two things are yours:

- Keep Akira running while `Voice.inCall` is true and the main window is
  closed (for example `QGuiApplication.quitOnLastWindowClosed` false for the
  length of the call, or the call window being a top-level window).
- The mute must be visible and obvious. `setMuted(true)` closes the
  microphone; please make that state impossible to miss, and show that a call
  is on whenever `inCall` is true.

**Replies read as they stream.** With `readAloud` on, and always in a call,
the chat's reply is read a sentence at a time as it arrives, so a model writing
a few words a second is heard from its first sentence. `stopSpeaking()` stops
the rest of that reply too. Nothing to wire; the shell calls `voice.follow(chat)`.

## Changed since handoff 41

- `Chat.answered(text)` is replaced by `Chat.replyGrew(text)` (the reply so
  far) and `Chat.replyEnded(text)` (the whole reply, or `""` when it was
  stopped, failed or empty; sent just before `busy` goes false). Nothing in
  QML used `answered`.
- `Voice.readReply` is gone; the bridge follows the chat itself.
- `listenBlocked` says "A call is listening already." during a call.

## Behaviour worth knowing when designing it

- On speakers Akira hears itself, so by default a call listens only while
  Akira is neither thinking nor speaking, plus 0.4 s after. The person
  interrupts with a button: `stopSpeaking()`. With `interruptByVoice` on
  (headphones), talking over Akira stops it and the reply, and what they say
  is sent next. A short line under the switch saying "for headphones" would
  save a confused first call.
- `callState` is `thinking` both while Whisper makes out what was said and
  while the model writes. With the current models, the second can be long.
- Withdrawing Listen or Speak ends the call within 50 ms, with `note` saying
  why. So does closing Akira.
- What a call hears is not emitted on `heard`; it appears in the chat as the
  person's message.

## Not done

- No QML. No always-on-top window, no keeping the app alive; see above.
- No echo cancellation. That is why interrupting by voice is for headphones.
- No wake word, by the person's choice.

## Evidence

`tests/test_voice_call.py` covers finding speech in the room's noise, the
microphone closing on mute and on every way a call ends, the half-duplex rule,
and interrupting by voice. It also runs a real call: Kokoro's voice, played
into it, is found, made out by Whisper and sent. `tests/test_voice_bridge.py`
covers what reaches the chat and when, including the newest thing said
winning over a reply under way. See the commit for the count.
