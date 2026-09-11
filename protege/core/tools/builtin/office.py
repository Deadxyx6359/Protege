"""Documents as tools: read Word, Excel, PowerPoint and PDF; create Word and
Excel files; edit Word and PowerPoint text; set cells in Excel.

Reading is `docs.read`. Creating and changing are `docs.write`, which is
irreversible, so every write stops for a person, with the real file and the
real change in the prompt.

**Creating never overwrites.** A new document written over an existing one
throws away every bit of formatting the person put there — exactly what
`edit_document` exists to avoid — so a path that already exists is refused,
with a pointer to the tool that changes a file instead.

**Changes land atomically.** The new file is written beside the old one and
moved into place in a single step, so a crash leaves the original rather than
half a document. Windows locks a file Word or Excel has open, and that is said
plainly instead of being reported as a generic failure.

The formats themselves, and why edits are surgical, are in
`protege.core.documents`.
"""

from __future__ import annotations

import json
from pathlib import Path

from protege.core.documents import Package, PackageError, pdf, sheets, slides, word, write_atomically
from protege.core.documents.ooxml import MAX_PACKAGE_BYTES
from protege.security.paths import real

from ..schema import Parameter, Requirement, Tool, ToolContext, ToolError, ToolResult

#: Text handed back to a model from one document.
MAX_READ_CHARS = 60_000

#: Cells one call may set. More than this is a job for Excel, not a prompt.
MAX_CELLS = 500

_KINDS = {".docx": "word", ".docm": "word", ".dotx": "word",
          ".xlsx": "sheets", ".xlsm": "sheets",
          ".pptx": "slides", ".pptm": "slides",
          ".pdf": "pdf"}
_OLD_FORMATS = {".doc": ".docx", ".xls": ".xlsx", ".ppt": ".pptx"}

_LOCKED = ("{name} is open in another program, which has locked it. Close it there "
           "(Word and Excel lock the files they have open) and try again.")


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _OLD_FORMATS:
        raise ToolError(f"{path.name} is in the old Office format. Open it in Office, save it "
                        f"as {_OLD_FORMATS[suffix]}, and try again with that file.")
    kind = _KINDS.get(suffix)
    if kind is None:
        raise ToolError(f"{path.name} is not a Word, Excel, PowerPoint or PDF file.")
    return kind


def _load(path: Path) -> bytes:
    if not path.is_file():
        raise ToolError(f"no such file: {path}")
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ToolError(f"{path.name} is over {MAX_PACKAGE_BYTES // 1_000_000} MB.")
    try:
        return path.read_bytes()
    except PermissionError:
        raise ToolError(_LOCKED.format(name=path.name)) from None
    except OSError as exc:
        raise ToolError(f"could not read {path.name}: {exc}") from None


def _save(path: Path, data: bytes) -> None:
    try:
        write_atomically(path, data)
    except PermissionError:
        raise ToolError(_LOCKED.format(name=path.name)) from None
    except OSError as exc:
        raise ToolError(f"could not write {path.name}: {exc}") from None


def _plural(count: int, word_: str) -> str:
    return f"{count} {word_}" + ("" if count == 1 else "s")


# -- read_document -----------------------------------------------------------------


def _run_read(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    kind = _kind(path)
    raw = _load(path)
    try:
        if kind == "pdf":
            text = word.render(pdf.read(raw))
        else:
            package = Package(raw, path.name)
            if kind == "word":
                text = word.render(word.read(package))
            elif kind == "sheets":
                text = sheets.render(sheets.read(package))
            else:
                text = slides.render(slides.read(package))
    except PackageError as exc:
        raise ToolError(str(exc)) from None

    text = text if text.strip() else "(no text found)"
    truncated = len(text) > MAX_READ_CHARS
    if truncated:
        text = text[:MAX_READ_CHARS] + f"\n\n[cut at {MAX_READ_CHARS} characters]"
    return ToolResult.success(f"{path}\n\n{text}",
                              data={"path": str(path), "kind": kind, "truncated": truncated})


read_document = Tool(
    name="read_document",
    summary=("Read a Word, Excel, PowerPoint or PDF file as text, keeping its headings, "
             "tables, slides, speaker notes and sheets. Spreadsheets come back with row "
             "numbers and column letters."),
    parameters=(Parameter("path", "string", "Absolute path to the document."),),
    requires=(Requirement("docs.read", scope_from="path"),),
    run=_run_read,
)


# -- create_document ---------------------------------------------------------------


def _run_create(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    content = str(arguments["content"])
    suffix = path.suffix.lower()
    if suffix == ".pptx":
        raise ToolError(
            "Making a slide deck from nothing is not supported yet: a deck needs a "
            "master and a theme, and one PowerPoint quietly repairs is worse than none. "
            "Make the deck in PowerPoint; edit_document can then change its text.")
    if suffix not in (".docx", ".xlsx"):
        raise ToolError(f"create_document makes .docx and .xlsx files, not "
                        f"{suffix or 'files without an extension'}.")
    if path.exists():
        raise ToolError(
            f"{path.name} already exists. Creating over it would throw away its "
            "formatting — use edit_document or update_spreadsheet to change it instead.")
    if not content.strip():
        raise ToolError("there is nothing to put in the document")

    if suffix == ".docx":
        blocks = word.parse_outline(content)
        raw = word.create(blocks, title=path.stem)
        headings = sum(block.kind == "heading" for block in blocks)
        described = f"{_plural(headings, 'heading')}, {_plural(len(blocks), 'block')}"
    else:
        found = sheets.parse_sheets(content)
        raw = sheets.create(found, title=path.stem)
        described = ", ".join(f"{name} ({_plural(len(rows), 'row')})" for name, rows in found)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ToolError(f"could not create {path.parent}: {exc}") from None
    _save(path, raw)
    return ToolResult.success(f"Created {path}: {described}.", data={"path": str(path)})


create_document = Tool(
    name="create_document",
    summary=("Create a new .docx or .xlsx file. For Word, write Markdown-style text: "
             "# headings, - bullets, blank lines between paragraphs, | pipe | tables |. "
             "For Excel, write rows as a pipe table or comma-separated lines, with a "
             "## heading to start each sheet. Never overwrites an existing file."),
    parameters=(
        Parameter("path", "string", "Absolute path for the new file, ending .docx or .xlsx."),
        Parameter("content", "string", "What to put in it, written as described above."),
    ),
    requires=(Requirement("docs.write", scope_from="path"),),
    reversible=False,
    run=_run_create,
)


# -- edit_document -------------------------------------------------------------------


def _run_edit(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    find = str(arguments["find"])
    replacement = str(arguments.get("replace") or "")
    kind = _kind(path)
    if kind == "sheets":
        raise ToolError("To change a spreadsheet, use update_spreadsheet with the cells to set.")
    if kind == "pdf":
        raise ToolError("PDF files can be read, not edited. Edit the document the PDF was made from.")
    if not find:
        raise ToolError("say what text to look for")

    raw = _load(path)
    try:
        package = Package(raw, path.name)
        edit = word.replace if kind == "word" else slides.replace
        new, count = edit(package, find, replacement)
    except PackageError as exc:
        raise ToolError(str(exc)) from None
    if not count:
        return ToolResult.failure(
            f"{find!r} does not appear in {path.name}, so nothing was changed. Matching "
            "is exact, including capitals and punctuation.")
    _save(path, new)
    return ToolResult.success(
        f"Replaced {_plural(count, 'occurrence')} of {find!r} in {path.name}. Everything "
        "else in the file — formatting, images, comments — is exactly as it was.",
        data={"count": count})


edit_document = Tool(
    name="edit_document",
    summary=("Replace text in a Word document (body, headers, footers and notes) or a "
             "PowerPoint deck (slides and speaker notes), keeping all formatting."),
    parameters=(
        Parameter("path", "string", "Absolute path to the .docx or .pptx file."),
        Parameter("find", "string", "The exact text to find."),
        Parameter("replace", "string", "What to put in its place. Empty deletes it.",
                  required=False, default=""),
    ),
    requires=(Requirement("docs.write", scope_from="path"),),
    reversible=False,
    run=_run_edit,
)


# -- update_spreadsheet ----------------------------------------------------------------


def _run_update(arguments: dict, context: ToolContext) -> ToolResult:
    path = real(arguments["path"])
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ToolError(f"{path.name} is not an Excel workbook (.xlsx).")
    try:
        cells = json.loads(str(arguments["cells"]))
    except json.JSONDecodeError as exc:
        raise ToolError(f'cells must be a JSON object such as {{"B3": 42}} ({exc})') from None
    if not isinstance(cells, dict) or not cells:
        raise ToolError('cells must be a JSON object of cell to value, such as {"B3": 42}')
    if len(cells) > MAX_CELLS:
        raise ToolError(f"at most {MAX_CELLS} cells in one change")
    for ref, value in cells.items():
        if isinstance(value, (list, dict)):
            raise ToolError(f"{ref}: a cell holds one value, not a list or an object")

    raw = _load(path)
    try:
        new, changed = sheets.set_cells(Package(raw, path.name), str(arguments["sheet"]), cells)
    except PackageError as exc:
        raise ToolError(str(exc)) from None
    _save(path, new)
    shown = ", ".join(changed[:20]) + (f" and {len(changed) - 20} more" if len(changed) > 20 else "")
    return ToolResult.success(
        f"Set {shown} on {arguments['sheet']} in {path.name}. Excel recalculates any "
        "formulas that depend on them when the file is next opened.",
        data={"cells": changed})


update_spreadsheet = Tool(
    name="update_spreadsheet",
    summary=("Set cells on one sheet of an Excel workbook, keeping each cell's formatting. "
             "Read the workbook first to see its sheets and cell references."),
    parameters=(
        Parameter("path", "string", "Absolute path to the .xlsx file."),
        Parameter("sheet", "string", "The sheet's name, as read_document shows it."),
        Parameter("cells", "string",
                  'A JSON object of cell to value, e.g. {"B3": 42, "C3": "Paid", '
                  '"D3": "=B3*2"}. Numbers stay numbers, text starting with = is a '
                  "formula, and null clears a cell."),
    ),
    requires=(Requirement("docs.write", scope_from="path"),),
    reversible=False,
    run=_run_update,
)


ALL = (read_document, create_document, edit_document, update_spreadsheet)
