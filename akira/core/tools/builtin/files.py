"""Reading, listing, searching and writing files.

Every path here has already survived the permission check — the policy resolves
it, rejects traversal, alternate data streams and reserved device names, and
confirms it lies inside a granted root. These tools re-resolve anyway, because
the check and the open are separate moments and the path could be a symlink
that changed between them. That race is narrow and not fully closed here; it is
noted rather than claimed shut.

Output is capped everywhere. A tool that returns a 40 MB file does not give the
model a 40 MB file, it destroys the conversation's context and loses the work
that came before.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from akira.security.paths import real

from ..schema import Parameter, Requirement, Tool, ToolContext, ToolError, ToolResult

#: Files bigger than this are summarised rather than returned. Roughly 50k
#: tokens, which would already crowd out most of an 8k context.
MAX_READ_BYTES = 200_000

MAX_ENTRIES = 400
MAX_MATCHES = 120

#: Extensions that are never worth handing to a language model as text.
_BINARY = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tif", ".tiff",
    ".mp3", ".wav", ".ogg", ".flac", ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".zip", ".gz", ".bz2", ".xz", ".7z", ".rar", ".tar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".gguf", ".safetensors", ".pyc",
    ".pdf", ".docx", ".xlsx", ".pptx",
}

#: Directories never worth walking. Skipped in listings and searches alike.
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".idea", ".vscode",
}


def _read_text(path: Path) -> str:
    """Decode a text file, or say plainly that it is not one."""
    if path.suffix.lower() in _BINARY:
        raise ToolError(
            f"{path.name} is a binary file ({path.suffix}); "
            "there is no text to read. Use a document tool if one applies."
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ToolError(f"could not read {path.name}: {exc}") from None

    if b"\x00" in data[:8192]:
        raise ToolError(f"{path.name} looks like a binary file, not text")

    truncated = len(data) > MAX_READ_BYTES
    if truncated:
        data = data[:MAX_READ_BYTES]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    if truncated:
        text += f"\n\n[truncated — {path.stat().st_size} bytes total]"
    return text


# -- read --------------------------------------------------------------------


def _run_read(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    if not path.exists():
        raise ToolError(f"no such file: {path}")
    if path.is_dir():
        raise ToolError(f"{path} is a directory — use list_directory")

    text = _read_text(path)
    lines = text.splitlines()
    numbered = "\n".join(f"{i + 1:>5}  {line}" for i, line in enumerate(lines))
    return ToolResult.success(
        f"{path} ({len(lines)} lines)\n\n{numbered}",
        data={"path": str(path), "lines": len(lines)})


read_file = Tool(
    name="read_file",
    summary="Read a text file and return its contents with line numbers.",
    parameters=(
        Parameter("path", "string", "Absolute path to the file."),
    ),
    requires=(Requirement("files.read", scope_from="path"),),
    run=_run_read,
)


# -- list --------------------------------------------------------------------


def _run_list(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    if not path.is_dir():
        raise ToolError(f"not a directory: {path}")

    entries = []
    try:
        for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if child.name in _SKIP_DIRS or child.name.startswith(".") and child.is_dir():
                continue
            if child.is_dir():
                entries.append(f"{child.name}/")
            else:
                try:
                    size = child.stat().st_size
                except OSError:
                    size = 0
                entries.append(f"{child.name}  ({size:,} bytes)")
            if len(entries) >= MAX_ENTRIES:
                entries.append(f"… more than {MAX_ENTRIES} entries, list truncated")
                break
    except OSError as exc:
        raise ToolError(f"could not list {path}: {exc}") from None

    body = "\n".join(entries) if entries else "(empty)"
    return ToolResult.success(f"{path}\n\n{body}", data={"path": str(path),
                                                         "count": len(entries)})


list_directory = Tool(
    name="list_directory",
    summary="List the files and folders in a directory.",
    parameters=(
        Parameter("path", "string", "Absolute path to the directory."),
    ),
    requires=(Requirement("files.read", scope_from="path"),),
    run=_run_list,
)


# -- search ------------------------------------------------------------------


def _run_search(arguments: dict, context: ToolContext) -> ToolResult:
    root = real(arguments["path"])
    needle = arguments["text"]
    pattern = arguments.get("filename_pattern") or "*"
    if not root.is_dir():
        raise ToolError(f"not a directory: {root}")

    lowered = needle.lower()
    matches: list[str] = []
    scanned = 0

    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in names:
            if not fnmatch.fnmatch(name, pattern):
                continue
            candidate = Path(current) / name
            if candidate.suffix.lower() in _BINARY:
                continue
            scanned += 1
            try:
                if candidate.stat().st_size > MAX_READ_BYTES * 4:
                    continue
                text = candidate.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if lowered in line.lower():
                    matches.append(f"{candidate}:{number}: {line.strip()[:200]}")
                    if len(matches) >= MAX_MATCHES:
                        break
            if len(matches) >= MAX_MATCHES:
                break
        if len(matches) >= MAX_MATCHES:
            break

    if not matches:
        return ToolResult.success(
            f"No matches for {needle!r} in {root} ({scanned} files searched).")
    header = f"{len(matches)} match(es) for {needle!r} in {root}"
    if len(matches) >= MAX_MATCHES:
        header += " — stopped at the limit"
    return ToolResult.success(header + "\n\n" + "\n".join(matches),
                              data={"count": len(matches)})


search_files = Tool(
    name="search_files",
    summary="Search a folder's text files for a piece of text, like grep.",
    parameters=(
        Parameter("path", "string", "Absolute path to the folder to search."),
        Parameter("text", "string", "The text to look for. Case-insensitive."),
        Parameter("filename_pattern", "string",
                  "Optional glob to limit which files are searched, e.g. '*.py'.",
                  required=False, default="*"),
    ),
    requires=(Requirement("files.read", scope_from="path"),),
    run=_run_search,
)


# -- write -------------------------------------------------------------------


def _run_write(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    content = arguments["content"]

    existed = path.exists()
    if existed and path.is_dir():
        raise ToolError(f"{path} is a directory")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise ToolError(f"could not write {path}: {exc}") from None

    verb = "Updated" if existed else "Created"
    lines = content.count("\n") + 1
    return ToolResult.success(f"{verb} {path} ({lines} lines).",
                              data={"path": str(path), "created": not existed})


write_file = Tool(
    name="write_file",
    summary="Write text to a file, replacing anything already there.",
    parameters=(
        Parameter("path", "string", "Absolute path to the file."),
        Parameter("content", "string", "The complete new contents of the file."),
    ),
    requires=(Requirement("files.write", scope_from="path"),),
    # Replacing a file's contents cannot be undone from here, so it asks.
    reversible=False,
    run=_run_write,
)


ALL = (read_file, list_directory, search_files, write_file)
