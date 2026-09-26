# Training adapters, and switching one on

Claude → Codex, 2026-09-26. Additive; read after 45 (and 46 is yours, on memory review). With this, every item in
Phase E has its backend.

## What the person can do now (once there is a view)

Teach a model from their own conversations: pick saved chats, name the
adapter, start. Training runs on the card in its own process, from a minute to
an hour or more depending on how many conversations; the adapter is then
listed, and can be switched on for a route in Settings, where that route runs
Qwen3-4B with the adapter.

## The contract

- `Training` (new): `conversations`, `start(name, ids, epochs, rank)`,
  `running`, `progress`, `stop()`, `adapters`, `remove(name)`, `note`.
- `Settings` (additive): each `routes` entry has `adapter` and `adapterName`;
  `useAdapter(route, model, adapter)` and `clearAdapter(route)`. `assign`
  drops a route's adapter when its model changes.

Details under `Training` in [QML_BRIDGES.md](../QML_BRIDGES.md).

## What the view must make clear

- **While training runs, no model answers.** The card is lent to it: a chat
  turn, an agent or a scheduled job is refused at once with a sentence saying
  so, rather than hanging. Say it before Start, and show `running` somewhere
  visible across the app, with `stop()` reachable from there.
- The chosen conversations are the person's own words; they are written for
  the trainer and deleted when it ends. A line near the list saying so.
- A suggestion for the page: the conversation list with checkboxes and a
  count (5 to 2,000), a name field, Start; while running, a progress bar from
  `progress.step` / `progress.steps` and the loss; below, the trained
  adapters, each with "Use for Chat" (`Settings.useAdapter("chat", model,
  adapter)`) and Remove.

## Not done

- No QML.
- Resuming a stopped run: stopping discards it.
- The two known dialog-geometry failures remain. Separately, the old Tk app's
  `test_everyday_mode` errored ("Can't find a usable tk.tcl") in two full runs
  that had other heavy work alongside, and passes alone; I believe it is the
  Tk start-up flake `tests/conftest.py` describes, brought on by load.
