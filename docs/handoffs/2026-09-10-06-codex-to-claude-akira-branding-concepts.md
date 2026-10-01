# Akira branding concepts — Codex → Claude

The user chose **Akira**, after Akira Nakashima, as the new product name. Four
pixel-art logo concepts are now available in
[the branding brief](../branding/AKIRA.md), with the comparison board and
generation prompts alongside it. No logo has been selected yet.

Read handoff 04, PROJECT.md and QML_BRIDGES.md. The checkout and origin/rebuild
were aligned at `d61ef06` when reviewed. The current frontend priority from your
handoff is the confirmation dialog, followed by persistent critical-review
findings, permissions, traces, scheduling and activity.

While preparing this branding note, your new draft handoff 05 appeared, along
with Agents.runTeam/runAgent, Schedule.addJob and generation serialization in
the working tree. Read that handoff and the updated living bridge reference as
well. This removes the backend entry-point gap described in 04. The UI can now
be built around those APIs once your in-progress changes are validated; the
Research interface has not yet been wired to them. Handoff 05 still contains
TESTS_AT_HANDOFF and its changes were uncommitted when inspected. This note
uses sequence 06 to avoid colliding with your newer handoff.

This session followed the user's request to explore branding after reviewing
your updates. It did not implement the queued UI work or change application
labels/icons. No Python modules, storage paths, config or backend code changed.
Your in-progress edits to core/models.py, core/schedule/actions.py,
core/schedule/scheduler.py and ui/shell.py were left intact.

The concepts are Relay A (switch/contact monogram), Lumen Moth (indigo/aqua
creature), Quiet Beacon (glass lantern), and Orbit Seed (botanical/cosmic mark).
The first has the strongest historical connection; the moth has the strongest
scene personality. These are generated design studies. Once the user chooses,
the final mark needs a deliberate pixel-grid drawing and small-size variants.

Validation: inspected the generated board and refined its background/contrast.
No runtime tests were run for this documentation/image-only pass. The 1311-pass
suite result in handoff 04 is your reported result, not a new test run here.
No commit or push was performed in this concept pass.
