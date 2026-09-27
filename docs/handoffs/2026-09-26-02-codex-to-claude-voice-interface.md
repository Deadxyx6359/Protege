# Voice interface — Codex to Claude, 2026-09-26

Frontend implementation uses the existing Voice bridge. No backend changes.

## Delivered

- Composer Voice action and Settings > General > Voice & calls open VoiceSheet.
- Explicit microphone and playback grants/revocation; opening the sheet never
  starts recording. Six existing voices, sample playback, persisted speed,
  read-aloud and headphone interruption settings.
- CallWindow is a small independent always-on-top window with Akira branding,
  elapsed time, actual microphone level, clear muted/listening state, Open chat,
  mute/unmute, interrupt and end. Interrupt stops speech and chat generation.
- `transientParent: null` keeps the call window independent of main-window
  minimization. Closing the main window hides it during a call; ending the call
  restores it. Closing the call window ends the call. Backend termination also
  restores a hidden main window so errors are visible.
- Project/history/new-chat controls cannot change the conversation during a
  call, including Research's new-inquiry action. An external project change
  ends the call before resetting the conversation.
- Shared Sheet now scrolls keyboard-focused controls into view, including the
  Start call button at 900 x 600. No automatic permission grants.

Files: Main.qml, Composer.qml, SettingsSheet.qml, Sheet.qml, ResearchView.qml,
qmldir; new VoiceSheet.qml, CallWindow.qml and tests/test_qml_voice.py.

## Validation and limits

Voice UI + bridge + call tests: 62 passed. UI settings, accessibility,
navigation, views, text formats, memory review and voice: 22 passed. Subsequent
Research guards additionally checked by the voice regression test. Dark/light
screenshots inspected at 100% and captures also produced at 150%; local ignored
captures: artifacts/scenes/ui-audit/voice-sep26/.

Audio hardware is replaced with fakes in UI tests. Permission revocation is
driven through the backend termination callback; real Call's policy polling is
covered by backend tests. No real microphone, model download, transcription or
speaker playback was started. Real Windows desktop minimize/close behavior and
an end-to-end call with installed audio models still need an interactive check.

The current whole-tree `python verify_offline.py` passes after your latest
backend commit 2491bd6. This supersedes the earlier training-import audit failure
recorded in the memory handoff. I did not modify the checker or training code.

## Next UI work

1. Scheduled-run details and content-pipeline draft review, with publication
   destination beside the explicit Publish action.
2. Images setup/generation/save and sanitized Drawing previews, plus browser
   confirmation pictures.
3. Findings export, richer Drive/Canvas source cards and browser hand-over.
4. Training setup and adapter selection using handoff 47: explicit conversation
   selection, training blocks model replies, and globally reachable Stop.

Push-to-talk/dictation is not exposed in this pass; hands-free calls are.
