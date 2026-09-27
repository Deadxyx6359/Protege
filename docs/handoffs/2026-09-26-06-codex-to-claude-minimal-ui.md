# Minimal UI — Codex to Claude, 2026-09-26

New user direction: "make the ui more minimal, it shouldnt have descriptions
or notes." Treat this as the visual baseline for subsequent work.

- Shared Sheet no longer renders subtitles; header height is 56.
- FormRow renders the title and controls without the description paragraph.
  Properties remain compatible with existing callers.
- Removed chat greeting subtitles, composer footnotes, call instructions and
  the voice-sheet introduction. Call widget is now 370 x 280.
- Removed explanatory copy from Pictures, Documents, Settings, Schedule,
  Memory, Watching, Agents, Research/investigations and draft review.
- Empty states use short labels. Removed repeated image prompt/seed metadata
  and save reminders from the image panel; editing and saving remain available.
- Retained user content, errors, active state, permission scopes and exact
  destinations/action text required to approve writes, publication or deletion.

Existing document, picture, voice, memory, draft, settings, general-view,
accessibility, text-format, navigation, Code and Research UI tests pass.
Dark/light compact screenshots inspected; call controls still fit. Local
captures: artifacts/scenes/ui-audit/minimal-sep26/.

No backend behavior changed. Claude's concurrent weather/location work was
left intact. New screens should lead with controls and short labels, without
standing help paragraphs or explanatory footers.
