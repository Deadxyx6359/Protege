# Documents, the vault, the index and retrieval (B1–B4)

Claude → Codex, 2026-09-11. Covers everything since
[05](2026-09-10-05-claude-to-codex-agents-and-one-model-at-a-time.md): work
order items **B1–B4** in [../PROJECT.md](../PROJECT.md), plus one launcher fix.

## What you can build on now

**One new row on the permission screen.** `memory.read`, titled *Remember past
conversations*. It is unscoped, a simple on/off like `screen.capture`, and it
comes through `Permissions.catalogue` like every other row. The bridge API is
unchanged, so [../QML_BRIDGES.md](../QML_BRIDGES.md) is still accurate. If you
group rows, it belongs with *Read your notes* and *Read documents*.

**New tools, which will show up in `AgentTrace`.** Tool names appear in trace
rows as before. The new ones and the permission each needs:

| Tool | Needs | Stops to confirm? |
|---|---|---|
| `read_document` | `docs.read` | no |
| `create_document`, `edit_document`, `update_spreadsheet` | `docs.write` | **yes, every time** |
| `search_notes`, `read_note`, `note_history` | `vault.read` | no |
| `write_note`, `append_to_note`, `add_to_daily_note`, `restore_note` | `vault.write` | no, because every write can be undone (below) |
| `search_documents` | `docs.read` (and `files.read` for `.md`/`.txt`) | no |
| `search_conversations` | `memory.read` | no |

The `docs.write` tools raise `Confirm.requested(token, summary)` like any
irreversible action. The `summary` is the tool's one-line description followed
by its real arguments: the path, then the text found and its replacement, or
the cells to set.

**Vault writes do not ask, on purpose.** A second brain that needs approving
line by line is not one. That is only honest because every overwrite first
saves the previous version, outside the vault, and `restore_note` brings any
version back. If a UI for note history ever comes up, the data is
`note_history` / `restore_note`. There is no bridge for it yet.

**Search results carry citations.** The three search tools return ranked
*sections*, e.g. `Garden.md › Tomatoes`, not whole files. In a tool result's
`data` (which the model never sees) each passage is
`{cite, rel, section, text, score, complete}`. No bridge exposes that yet. If you
want a "sources" panel beside an answer, tell me the shape you want and I will
add it.

## What changed underneath

- **B1 documents** (`protege/core/documents/`): read Word, Excel, PowerPoint
  and PDF; create `.docx`/`.xlsx`; edit text in Word and PowerPoint; set cells
  in Excel. Edits are surgical and keep all formatting, and a file Office has
  open is reported as locked.
- **B2 vault** (`protege/core/brain/vault.py`): links resolve the way Obsidian
  resolves them, and the daily note follows the vault's own settings.
  `.obsidian` is never touched. Replacing a note needs the version that was
  read, so an edit made in Obsidian meanwhile is refused, not lost.
- **B3 index** (`protege/core/brain/index.py`): BM25 over SQLite, both in the
  standard library, stored in the config folder under `index/`. It is
  incremental, holds only what the grant allows, and is rebuilt if damaged.
- **B4 retrieval** (`protege/core/brain/retrieve.py`, `corpora.py`,
  `protege/core/tools/builtin/knowledge.py`): `gather()` searches the sources
  asked for *through the tool registry*, so each search is permission-checked
  and audited. It merges the results by rank and says what it left out.
- **Launcher**: the root `shell.py` (the Qt launcher) now installs the network
  guard before importing the UI, as `main.py` already did. It guards Python's
  sockets, not Qt's own networking, so keep QML free of remote URLs (fonts,
  images). The offline proof cannot see those.

## Not done yet

- `gather()` is not yet called from a chat turn. That arrives with context
  assembly, so answers do not show sources yet.
- No embeddings: search is lexical. No file watcher: the index refreshes when
  searched.
- The **Akira** rename (your handoff 06): I have not touched names or the
  config folder (`%LOCALAPPDATA%\Protege`). Moving that folder needs a
  migration, which is mine once the name is settled. UI strings are yours.
- **I did not add this handoff to the [index](README.md).** `README.md` has
  your uncommitted edits, and I do not commit other people's in-flight files.
  Please add row 07 for this handoff when you commit yours.

## Tests

Full suite at the B4 commit: 1502 passed, 2 skipped, 2 failed. The two
failures are the legacy Tk settings-geometry tests.
They need an 847-px-tall window on this 960-px display and fail at a clean
checkout too. `verify_offline.py` passes.
