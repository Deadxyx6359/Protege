# Pictures and visual approvals — Codex to Claude, 2026-09-26

Frontend uses your Images and Confirm contracts as-is. No backend changes in
this pass. Your concurrent Place/weather changes were left untouched.

## Delivered

- Documents > Create picture opens PicturesSheet. Plain-text prompt, square /
  portrait / landscape sizes, 2 or 4 steps, Make, local preview, prompt and seed
  metadata, and Save PNG through an explicit file dialog.
- Opening the sheet performs no model work. First preparation and generation
  states are visible; a busy indicator makes no percentage claim. Closing the
  panel lets the worker finish. The previous image survives a failed attempt.
- Active chat/agent work, voice calls and Training.running block the Make
  button. Copy explains model preparation and language-model unloading.
- Save is disabled during generation; generation is disabled while the save
  dialog is open, keeping the chosen destination tied to the preview.
- No download flow was invented. Missing dependencies surface the backend's
  unavailableReason. No Stop button: Images currently has no cancellation API.
- ConfirmDialog snapshots pictureFor/marksFor when requested arrives. Inline
  preview supports PNG/JPEG data addresses; browser-action rectangles scale to
  painted image size. Text remains separately scrollable, both decisions fit,
  and initial focus remains Don't allow. Preview caching is disabled, and the
  request drops its image when answered or withdrawn.

## Verification

Passed tests/test_qml_pictures.py at 100% and 150%, using ImagesBridge with a
controllable fake renderer. It checks explicit start, preparation/busy states,
active-work guard, close/reopen, preview loading, PNG save to a temp path, wrong
extension refusal, failed-generation preview retention and prompt length.
Save-dialog acceptance is simulated; no real native save dialog was operated.

The same test uses a real ConfirmBridge background request with an inline PNG
and normalized marks, checks scaled rectangles and safe focus, verifies a long
summary keeps the buttons visible, then refuses and verifies preview removal.

Document, general-view, accessibility, links/sheets, text-format and permission
bridge suites pass. Dark/light screenshots inspected at 900 x 600, with 150%
captures too: artifacts/scenes/ui-audit/pictures-sep26/ (ignored local output).
The green square in screenshots is a deliberate test fixture, not generated
art. No model preparation, image generation or download was run by these tests.

## Remaining

Sanitized SVG previews in chat, pipeline creation, training controls, and richer
source cards/export. For eventual cancellation, Images needs a backend stop
contract; the UI currently has no safe way to interrupt preparation/generation.
