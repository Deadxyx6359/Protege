# Content pipelines, and the drafts they leave

Claude → Codex, 2026-09-25. Additive; read after 43.

## What the person can do now (once there is a view)

Schedule a **pipeline**: a brief ("a short weekly post on what changed in my
garden notes") and a place to publish to: a new note in the vault, a new file,
or an email from their connected Gmail. On its schedule, the drafter writes
the piece, the critic reviews it against the brief, and the drafter revises
it. The result waits as a draft. **Nothing is ever published by the
schedule.**

## The contract

- Creating one: `Schedule.addJob` with `action: "pipeline"` and
  `arguments: {brief, publish}`. The `publish` forms are in
  [QML_BRIDGES.md](../QML_BRIDGES.md) under "Creating a job". A bad brief or
  target is refused at once with a reason. The job's `grants` are what the
  drafter may read (typically `vault.read` for a notes folder).
- The drafts: the new `Drafts` context property. `drafts`, `waitingCount` (for
  a nav badge, like `Memory.pendingCount`), `text(id)`, `review(id)`,
  `edit(id, text)`, `discard(id)`, `publish(id, text)`, `publishing`, `note`.
  Details under `Drafts`.

## What the view must do

- Show the draft in full, the review beside or under it, and **`target`
  beside the Publish button, always**: where it goes is part of what the
  person agrees to.
- Call `publish` only from the person's press of Publish. That press is the
  confirmation the publishing tool would otherwise ask for; there is no
  second dialog, so the page itself has to make clear what is about to happen.
- When `note` names a missing grant (for example `mail.send` for the sending
  address), offer it there, after the person agrees, and let them press
  Publish again. The draft stays waiting until then.
- Show the draft as plain text or as Markdown you render yourself with
  pictures refused, following rule 5: a draft is model output.

## Not done

- No QML.
- E1 (image generation) and E4 (training) are what is left of Phase E. Both
  need large downloads, which the person will be asked about first.
