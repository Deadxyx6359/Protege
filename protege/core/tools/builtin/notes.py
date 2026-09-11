"""The Obsidian vault as tools: search it, read notes with their links, write
and append, keep the daily note, and undo.

Reading is `vault.read`. Writing is `vault.write`, which does not stop to ask —
a second brain that needs approving line by line is not one — and is honest
about that because every write can be undone: the previous version is kept
and `restore_note` brings it back.

**Rewriting a note needs the version that was read.** An existing note is only
replaced by someone who has seen it, so a change made in Obsidian meanwhile is
refused rather than silently overwritten. Appending checks the same way itself.

**Every path is checked, including the ones this code works out.** The daily
note's location comes from the vault's settings, not from the argument the
permission was checked against, so it is checked again before anything is
written there. Search and backlinks read only the notes the policy allows.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from protege.core.brain import ConflictError, Index, Vault, VaultError, find_root
from protege.security.paths import real

from ..schema import Parameter, Requirement, Tool, ToolContext, ToolError, ToolResult
from .knowledge import cite_file, present

MAX_BODY_CHARS = 40_000
MAX_HITS = 12


def _vault(path: Path, context: ToolContext) -> Vault:
    root = find_root(path) or (path if path.is_dir() else path.parent)
    try:
        return Vault(root, may_read=lambda p: bool(context.policy.allows("vault.read", str(p))))
    except VaultError as exc:
        raise ToolError(str(exc)) from None


# -- search_notes -------------------------------------------------------------------


def _run_search(arguments: dict, context: ToolContext) -> ToolResult:
    folder = real(arguments["vault"])
    if not folder.is_dir():
        raise ToolError(f"not a folder: {folder}")
    vault = _vault(folder, context)
    query = str(arguments["query"])
    try:
        index = Index(vault)
        index.refresh()
        results = index.search(query, limit=MAX_HITS)
    except VaultError as exc:
        raise ToolError(str(exc)) from None
    return present(results, query, noun="note", cite=cite_file)


search_notes = Tool(
    name="search_notes",
    summary=("Search an Obsidian vault for the sections most about a query, best first, "
             "each with its note and heading."),
    parameters=(
        Parameter("vault", "string", "Absolute path to the vault folder."),
        Parameter("query", "string", "What to look for, in a few words. A #tag works too."),
    ),
    requires=(Requirement("vault.read", scope_from="vault"),),
    run=_run_search,
)


# -- read_note ------------------------------------------------------------------------


def _run_read(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    vault = _vault(path, context)
    try:
        note = vault.read(path)
        backlinks = vault.backlinks(path)
        resolved = [(link, vault.resolve(link.target, note.path)) for link in note.links]
    except VaultError as exc:
        raise ToolError(str(exc)) from None

    lines = [f"{note.rel} — version {note.version}"]
    if note.error:
        lines.append(f"Problem: {note.error}")
    if note.tags:
        lines.append("Tags: " + ", ".join("#" + t for t in note.tags))
    if note.frontmatter:
        dumped = yaml.safe_dump(note.frontmatter, sort_keys=False, allow_unicode=True).strip()
        lines += ["Properties:", *("  " + line for line in dumped.splitlines())]
    if resolved:
        lines.append("Links to: " + ", ".join(
            vault.rel(target) if target else f"{link.target} (no such note yet)"
            for link, target in resolved))
    if backlinks:
        lines.append("Linked from: " + ", ".join(backlinks))
    body = note.body
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + f"\n\n[cut at {MAX_BODY_CHARS} characters]"
    lines += ["", body.strip() or "(empty)", "",
              f"To replace this note, pass version {note.version} to write_note."]
    return ToolResult.success("\n".join(lines), data={"version": note.version, "rel": note.rel})


read_note = Tool(
    name="read_note",
    summary=("Read a note from an Obsidian vault, with its tags, properties, the notes it "
             "links to, the notes that link to it, and its current version."),
    parameters=(Parameter("path", "string", "Absolute path to the .md note."),),
    requires=(Requirement("vault.read", scope_from="path"),),
    run=_run_read,
)


# -- write_note -----------------------------------------------------------------------


def _run_write(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    content = str(arguments["content"])
    version = str(arguments.get("version") or "").strip()
    vault = _vault(path, context)
    try:
        if path.exists():
            if not version:
                raise ToolError(
                    "That note already exists. Read it with read_note and pass the version it "
                    "shows, so nothing written in Obsidian since is overwritten — or use "
                    "append_to_note to add to it instead.")
            new = vault.write(path, content, expected=version)
            verb = "Updated"
        else:
            new = vault.create(path, content)
            verb = "Created"
    except ConflictError as exc:
        return ToolResult.failure(str(exc))
    except VaultError as exc:
        raise ToolError(str(exc)) from None
    tail = (" The previous version is kept; restore_note can bring it back."
            if verb == "Updated" else "")
    return ToolResult.success(f"{verb} {vault.rel(path)} (version {new}).{tail}",
                              data={"version": new})


write_note = Tool(
    name="write_note",
    summary=("Create a note in an Obsidian vault, or replace one you have read. Replacing "
             "needs the version read_note showed. The previous version is always kept."),
    parameters=(
        Parameter("path", "string", "Absolute path to the .md note."),
        Parameter("content", "string", "The whole note, frontmatter included if it has any."),
        Parameter("version", "string", "The version read_note showed. Needed to replace a note.",
                  required=False),
    ),
    requires=(Requirement("vault.write", scope_from="path"),),
    run=_run_write,
)


# -- append_to_note -------------------------------------------------------------------


def _append(vault: Vault, path: Path, text: str, heading: str | None) -> str:
    try:
        vault.append(path, text, heading)
    except ConflictError as exc:
        raise ToolError(f"{exc} Nothing was added.") from None
    except VaultError as exc:
        raise ToolError(str(exc)) from None
    where = f" under “{heading}”" if heading else ""
    return f"Added to {vault.rel(path)}{where}."


def _run_append(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    heading = str(arguments.get("heading") or "").strip() or None
    return ToolResult.success(_append(_vault(path, context), path, str(arguments["text"]), heading))


append_to_note = Tool(
    name="append_to_note",
    summary=("Add text to the end of a note, or to the end of one of its sections, creating "
             "the note if it does not exist. Nothing else in the note changes."),
    parameters=(
        Parameter("path", "string", "Absolute path to the .md note."),
        Parameter("text", "string", "What to add."),
        Parameter("heading", "string", "Add it at the end of this section, creating the section "
                  "if needed.", required=False),
    ),
    requires=(Requirement("vault.write", scope_from="path"),),
    run=_run_append,
)


# -- add_to_daily_note ------------------------------------------------------------------


def _run_daily(arguments: dict, context: ToolContext) -> ToolResult:
    folder = real(arguments["vault"])
    if not folder.is_dir():
        raise ToolError(f"not a folder: {folder}")
    vault = _vault(folder, context)
    try:
        target = vault.daily_path(date.today())
    except VaultError as exc:
        raise ToolError(str(exc)) from None
    # The permission was checked against the folder given, but the daily note's
    # place comes from the vault's settings and can lie outside it.
    decision = context.policy.allows("vault.write", str(target))
    if not decision:
        raise ToolError(f"Not permitted: {decision.reason}. Today's note would be "
                        f"{vault.rel(target)}, which is outside what may be written.")
    heading = str(arguments.get("heading") or "").strip() or None
    return ToolResult.success(_append(vault, target, str(arguments["text"]), heading))


add_to_daily_note = Tool(
    name="add_to_daily_note",
    summary=("Add text to today's daily note, where the vault's own daily-notes settings put "
             "it, creating the note if needed."),
    parameters=(
        Parameter("vault", "string", "Absolute path to the vault folder."),
        Parameter("text", "string", "What to add."),
        Parameter("heading", "string", "Add it under this section of the day's note.",
                  required=False),
    ),
    requires=(Requirement("vault.write", scope_from="vault"),),
    run=_run_daily,
)


# -- history and restore ------------------------------------------------------------------


def _run_history(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    vault = _vault(path, context)
    try:
        entries = vault.history(path)
    except VaultError as exc:
        raise ToolError(str(exc)) from None
    if not entries:
        return ToolResult.success(f"No earlier versions of {vault.rel(path)} have been kept.")
    lines = [f"Earlier versions of {vault.rel(path)}, newest first:"]
    lines += [f"- {version}, replaced {when}" for version, when in entries]
    return ToolResult.success("\n".join(lines), data={"versions": [v for v, _ in entries]})


note_history = Tool(
    name="note_history",
    summary="List the earlier versions of a note that can be restored.",
    parameters=(Parameter("path", "string", "Absolute path to the .md note."),),
    requires=(Requirement("vault.read", scope_from="path"),),
    run=_run_history,
)


def _run_restore(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    vault = _vault(path, context)
    try:
        new = vault.restore(path, str(arguments["version"]).strip())
    except VaultError as exc:
        raise ToolError(str(exc)) from None
    return ToolResult.success(
        f"Restored {vault.rel(path)} to version {arguments['version']}. What it replaced is "
        f"kept too (now version {new}).", data={"version": new})


restore_note = Tool(
    name="restore_note",
    summary="Put an earlier version of a note back. The version it replaces is kept as well.",
    parameters=(
        Parameter("path", "string", "Absolute path to the .md note."),
        Parameter("version", "string", "The version to restore, from note_history."),
    ),
    requires=(Requirement("vault.write", scope_from="path"),),
    run=_run_restore,
)


ALL = (search_notes, read_note, write_note, append_to_note, add_to_daily_note,
       note_history, restore_note)
