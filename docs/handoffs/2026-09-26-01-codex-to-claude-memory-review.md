# Memory review: sources first, one proposal at a time

Codex → Claude, 2026-09-26. Read handoffs 41–45; confirmed the previous UI
checkpoint `a040b5e` is already on `origin/rebuild` under your later commits.
This pass is local and uncommitted.

## Changes

Only `akira/ui/qml/Akira/MemoryView.qml` and a new
`tests/test_qml_memory_review.py` were changed for the implementation.
No bridge, permission, model, scheduler or core contract changed.

- A searchable proposal queue matches note titles, target paths, source
  conversation titles, and displayed project names.
- One proposal expands at a time. Source titles and project provenance appear
  separately, followed by the full selectable, wrapped plain-text preview.
- Save/discard actions sit after the preview with the full vault destination.
  The existing guarded accept, conflict handling, and scoped write-permission
  recovery remain. Selecting Review writes nothing.
- Vault setup collapses once a vault exists, with an explicit Setup button.
  Memory activity and last-run feedback remain visible in the page header.
- Cards use rectangles and the scroll content is layered to avoid Qt software
  clipping faults. Keyboard focus is brought into the scroll viewport.

## Validation

23 passed in 20.07 seconds across memory bridge, new real-window memory review,
QML views, navigation, text formats and accessibility. The new tests cover
source-title search, masked HTML-looking content as literal text, collapsed
save controls, denied writes, an explicit permitted save and discard, at
100%/150% scale. Screenshots were inspected in dark and light, at 900×600 and
1440×900; ignored local output is `artifacts/scenes/ui-audit/memory-sep26/`.
No real account, microphone, voice model or external service was used.

**Whole-tree offline audit is currently failing:**
`akira/training/_trainer.py:96 imports networking module 'transformers' inside
main()`. This is in the in-progress backend training work, not the UI change.
Please resolve before a whole-tree release; I did not relax the checker or
edit that work. Whitespace check passed for the UI file.

## Next frontend priorities

1. Voice/calls: contract is now available. Dedicated call window surviving main
   window minimization/close, obvious mute/listening state, end/interrupt,
   voice selection, and explicit permission/setup controls. No voice UI yet.
2. Scheduled-run details and content-pipeline draft review/publication, always
   showing the publish destination beside its explicit action.
3. Image-generation UI and sanitized drawing previews; confirmation pictures.
4. Findings export, Drive/Canvas source cards, browser hand-over notice.

All pre-existing dirty backend/shared-seam files, including Images, training,
voice, shell wiring and your pending bridge documentation, were left intact.
