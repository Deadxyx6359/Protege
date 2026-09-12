"""Excel workbooks: read with coordinates, update cells in place, create new ones.

Reading shows each sheet as a grid labelled with row numbers and column
letters, so whoever reads it can name the cell they want changed. Dates are
recognised from their number formats — to Excel a date is a number whose format
says "show me as a date" — and shown as dates. Formulas show their last
calculated value, which is what a person sees.

Updating is surgical, like the Word and PowerPoint edits. A cell keeps its
style when its value changes, and text is written inline rather than into the
shared-string table, so no other part changes on its account. Two cases need
care:

  * **A replaced formula leaves the calculation chain pointing at nothing.**
    Excel reports that as damage and "repairs" the file. The chain is only a
    cache that Excel rebuilds, so it is removed when a formula is overwritten.
  * **A cell anchoring a shared or array formula carries it for a whole range.**
    Changing it would break every other cell in that range, so it is refused
    with the reason rather than done.

Every update also asks Excel to recalculate on open, so formulas that depend on
a changed cell show the right answer the first time the file is opened.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .ooxml import (
    APP_PROPERTIES,
    APP_REL,
    APP_TYPE,
    CORE_REL,
    CORE_TYPE,
    OFFICE_DOCUMENT,
    REL,
    XML_DECL,
    Package,
    PackageError,
    attribute,
    build_package,
    clean_text,
    content_types,
    core_properties,
    decode_part,
    encode_part,
    escape,
    main_part,
    namespace_prefix,
    qualified,
    relationships_xml,
)

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_M = "{%s}" % MAIN
_R = "{%s}" % REL

MAX_ROWS_SHOWN = 200
MAX_COLS_SHOWN = 30
MAX_ROW = 1_048_576
MAX_COL = 16_384
MAX_TEXT = 32_767

_WORKBOOK_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
_SHEET_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
_STYLES_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"

_REF = re.compile(r"([A-Za-z]{1,3})([1-9][0-9]{0,6})")

#: Excel's built-in number formats that show a date or a time.
_BUILTIN_KINDS = {14: "date", 15: "date", 16: "date", 17: "date", 18: "time",
                  19: "time", 20: "time", 21: "time", 22: "datetime",
                  45: "time", 46: "time", 47: "time"}

_STYLES = (XML_DECL + f'<styleSheet xmlns="{MAIN}">'
           '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
           '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
           '<fills count="2"><fill><patternFill patternType="none"/></fill>'
           '<fill><patternFill patternType="gray125"/></fill></fills>'
           '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
           '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
           '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
           '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
           '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
           "</styleSheet>")


def column_index(letters: str) -> int:
    number = 0
    for char in letters.upper():
        number = number * 26 + (ord(char) - 64)
    return number


def column_letters(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def split_ref(ref: str) -> tuple[int, int]:
    """(row, column) for a reference like `B3`, or a reason it is not one."""
    match = _REF.fullmatch(str(ref).strip())
    if not match:
        raise PackageError(f"{ref!r} is not a cell reference like B3.")
    row, column = int(match.group(2)), column_index(match.group(1))
    if row > MAX_ROW or column > MAX_COL:
        raise PackageError(f"{ref} is beyond the edge of a worksheet.")
    return row, column


@dataclass(frozen=True, slots=True)
class SheetInfo:
    name: str
    part: str


@dataclass(slots=True)
class Sheet:
    name: str
    rows: list[list[str]] = field(default_factory=list)
    total_rows: int = 0
    total_cols: int = 0
    formulas: int = 0


# -- reading ------------------------------------------------------------------------


def _related(package: Package, main: str, kind_suffix: str) -> str | None:
    for kind, target in package.relationships(main).values():
        if kind.endswith(kind_suffix) and package.has(target):
            return target
    return None


def workbook_sheets(package: Package, main: str | None = None) -> list[SheetInfo]:
    main = main or main_part(package, "xl/workbook.xml")
    relations = package.relationships(main)
    listed = []
    for sheet in package.xml(main).iter(f"{_M}sheet"):
        relation = relations.get(sheet.get(f"{_R}id", ""))
        if relation and relation[0].endswith("/worksheet"):
            listed.append(SheetInfo(sheet.get("name", ""), relation[1]))
    return listed


def _shared_strings(package: Package, main: str) -> list[str]:
    part = _related(package, main, "/sharedStrings")
    if part is None:
        return []
    strings = []
    for item in package.xml(part).findall(f"{_M}si"):
        pieces = []
        for child in item:
            if child.tag == f"{_M}t":
                pieces.append(child.text or "")
            elif child.tag == f"{_M}r":
                text = child.find(f"{_M}t")
                if text is not None:
                    pieces.append(text.text or "")
        strings.append("".join(pieces))
    return strings


def _format_kind(code: str) -> str:
    bare = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code).lower()
    has_date = "y" in bare or "d" in bare
    has_time = "h" in bare or "s" in bare
    if has_date and has_time:
        return "datetime"
    return "date" if has_date else "time" if has_time else ""


def _number_kinds(package: Package, main: str) -> dict[int, str]:
    """Style index → `date`, `time` or `datetime`, for the styles that show one."""
    part = _related(package, main, "/styles")
    if part is None:
        return {}
    root = package.xml(part)
    custom: dict[int, str] = {}
    formats = root.find(f"{_M}numFmts")
    if formats is not None:
        for fmt in formats.findall(f"{_M}numFmt"):
            try:
                custom[int(fmt.get("numFmtId", "-1"))] = fmt.get("formatCode", "")
            except ValueError:
                continue
    kinds: dict[int, str] = {}
    xfs = root.find(f"{_M}cellXfs")
    if xfs is None:
        return kinds
    for index, xf in enumerate(xfs.findall(f"{_M}xf")):
        try:
            number = int(xf.get("numFmtId", "0"))
        except ValueError:
            continue
        kind = _format_kind(custom[number]) if number in custom else _BUILTIN_KINDS.get(number, "")
        if kind:
            kinds[index] = kind
    return kinds


def _date1904(package: Package, main: str) -> bool:
    properties = package.xml(main).find(f"{_M}workbookPr")
    return properties is not None and properties.get("date1904", "").lower() in ("1", "true")


def _as_date(serial: float, kind: str, date1904: bool) -> str | None:
    base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
    try:
        moment = base + timedelta(days=serial)
    except (OverflowError, ValueError):
        return None
    if kind == "date":
        return moment.date().isoformat()
    if kind == "time":
        return moment.strftime("%H:%M:%S")
    return moment.strftime("%Y-%m-%d %H:%M")


def _cell_value(cell, strings: list[str], kinds: dict[int, str], date1904: bool) -> str:
    kind = cell.get("t", "n")
    value_node = cell.find(f"{_M}v")
    text = value_node.text if value_node is not None else None
    if kind == "s":
        try:
            return strings[int(text)]
        except (TypeError, ValueError, IndexError):
            return ""
    if kind == "inlineStr":
        inline = cell.find(f"{_M}is")
        return "".join(t.text or "" for t in inline.iter(f"{_M}t")) if inline is not None else ""
    if kind == "b":
        return "TRUE" if text == "1" else "FALSE"
    if text is None:
        return ""
    if kind in ("str", "e"):
        return text
    try:
        style = int(cell.get("s", "0") or "0")
    except ValueError:
        style = 0
    shown_as = kinds.get(style)
    if shown_as:
        try:
            shown = _as_date(float(text), shown_as, date1904)
        except ValueError:
            shown = None
        if shown:
            return shown
    return text


def read(package: Package) -> list[Sheet]:
    main = main_part(package, "xl/workbook.xml")
    strings = _shared_strings(package, main)
    kinds = _number_kinds(package, main)
    date1904 = _date1904(package, main)
    result = []
    for info in workbook_sheets(package, main):
        sheet = Sheet(info.name)
        data = package.xml(info.part).find(f"{_M}sheetData")
        grid: dict[int, dict[int, str]] = {}
        last_row = 0
        for row in data.findall(f"{_M}row") if data is not None else ():
            try:
                number = int(row.get("r") or last_row + 1)
            except ValueError:
                number = last_row + 1
            last_row = number
            last_col = 0
            for cell in row.findall(f"{_M}c"):
                ref = _REF.fullmatch(cell.get("r") or "")
                column = column_index(ref.group(1)) if ref else last_col + 1
                last_col = column
                if cell.find(f"{_M}f") is not None:
                    sheet.formulas += 1
                shown = _cell_value(cell, strings, kinds, date1904)
                if shown != "":
                    grid.setdefault(number, {})[column] = shown
        if grid:
            sheet.total_rows = max(grid)
            sheet.total_cols = max(max(columns) for columns in grid.values())
            width = min(sheet.total_cols, MAX_COLS_SHOWN)
            for number in range(1, min(sheet.total_rows, MAX_ROWS_SHOWN) + 1):
                columns = grid.get(number, {})
                sheet.rows.append([columns.get(c, "") for c in range(1, width + 1)])
        result.append(sheet)
    return result


def _shown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render(sheets: list[Sheet]) -> str:
    """Every sheet as a grid with its row numbers and column letters."""
    out: list[str] = []
    for sheet in sheets:
        if out:
            out.append("")
        heading = f"## Sheet: {sheet.name}"
        if not sheet.total_rows:
            out += [heading, "(empty)"]
            continue
        heading += f" — {sheet.total_rows} rows × {sheet.total_cols} columns"
        if sheet.formulas:
            heading += f"; {sheet.formulas} formulas, shown by their last calculated value"
        out.append(heading)
        width = len(sheet.rows[0])
        out.append("|   | " + " | ".join(column_letters(c) for c in range(1, width + 1)) + " |")
        out.append("|---|" + "---|" * width)
        for number, row in enumerate(sheet.rows, 1):
            out.append(f"| {number} | " + " | ".join(_shown(v) for v in row) + " |")
        if sheet.total_rows > MAX_ROWS_SHOWN or sheet.total_cols > MAX_COLS_SHOWN:
            out.append(f"(showing the first {min(sheet.total_rows, MAX_ROWS_SHOWN)} rows "
                       f"and {min(sheet.total_cols, MAX_COLS_SHOWN)} columns)")
    return "\n".join(out)


# -- updating ------------------------------------------------------------------------


def _cell_xml(prefix: str, ref: str, style: str, value: object) -> str:
    c, v, f = qualified(prefix, "c"), qualified(prefix, "v"), qualified(prefix, "f")
    s = f' s="{style}"' if style else ""
    if value is None or value == "":
        return f'<{c} r="{ref}"{s}/>'
    if isinstance(value, bool):
        return f'<{c} r="{ref}"{s} t="b"><{v}>{int(value)}</{v}></{c}>'
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise PackageError(f"{ref}: a cell cannot hold {value}.")
        return f'<{c} r="{ref}"{s}><{v}>{value!r}</{v}></{c}>'
    text = clean_text(str(value))
    if len(text) > MAX_TEXT:
        raise PackageError(f"{ref}: a cell holds at most {MAX_TEXT} characters.")
    if text.startswith("=") and len(text) > 1:
        return f'<{c} r="{ref}"{s}><{f}>{escape(text[1:])}</{f}></{c}>'
    inline, t = qualified(prefix, "is"), qualified(prefix, "t")
    return (f'<{c} r="{ref}"{s} t="inlineStr"><{inline}><{t} xml:space="preserve">'
            f"{escape(text)}</{t}></{inline}></{c}>")


def _put(xml: str, prefix: str, row: int, column: int, ref: str,
         value: object) -> tuple[str, bool]:
    """Set one cell in a sheet's XML. Returns the XML and whether a formula went."""
    c, row_tag = qualified(prefix, "c"), qualified(prefix, "row")
    cell = re.compile(rf'<{re.escape(c)}\b(?=[^>]*\br="{ref}")[^>]*?(?:/>|>.*?</{re.escape(c)}>)',
                      re.S)
    found = cell.search(xml)
    if found:
        whole = found.group(0)
        opening = whole[:whole.index(">") + 1]
        style = re.search(r'\bs="(\d+)"', opening)
        formula = re.search(rf"<{re.escape(qualified(prefix, 'f'))}\b([^>]*)", whole)
        if formula and re.search(r'\bref="', formula.group(1)):
            raise PackageError(
                f"{ref} holds the formula for a whole range of cells, so changing it here "
                "would break the rest of that range. Change it in Excel instead.")
        new = _cell_xml(prefix, ref, style.group(1) if style else "", value)
        return xml[:found.start()] + new + xml[found.end():], formula is not None

    new = _cell_xml(prefix, ref, "", value)
    row_pattern = re.compile(rf'<{re.escape(row_tag)}\b(?=[^>]*\br="{row}")([^>]*?)(/?)>')
    found_row = row_pattern.search(xml)
    if found_row:
        # `spans` is only an optimisation hint, and a wrong one is worse than none.
        attributes = re.sub(r'\s+spans="[^"]*"', "", found_row.group(1))
        if found_row.group(2):
            return (xml[:found_row.start()] + f"<{row_tag}{attributes}>{new}</{row_tag}>"
                    + xml[found_row.end():]), False
        close = xml.find(f"</{row_tag}>", found_row.end())
        if close < 0:
            raise PackageError("a row in this sheet is never closed; the file is damaged")
        content = xml[found_row.end():close]
        insert = len(content)
        for existing in re.finditer(rf'<{re.escape(c)}\b[^>]*\br="([A-Z]+)\d+"', content):
            if column_index(existing.group(1)) > column:
                insert = existing.start()
                break
        content = content[:insert] + new + content[insert:]
        return xml[:found_row.start()] + f"<{row_tag}{attributes}>" + content + xml[close:], False

    sheet_data = qualified(prefix, "sheetData")
    new_row = f'<{row_tag} r="{row}">{new}</{row_tag}>'
    empty = re.search(rf"<{re.escape(sheet_data)}\s*/>", xml)
    if empty:
        return (xml[:empty.start()] + f"<{sheet_data}>{new_row}</{sheet_data}>"
                + xml[empty.end():]), False
    opening = re.search(rf"<{re.escape(sheet_data)}\b[^>]*>", xml)
    close = xml.find(f"</{sheet_data}>")
    if opening is None or close < 0:
        raise PackageError("this sheet has no cell data section")
    insert = close
    for existing in re.finditer(rf'<{re.escape(row_tag)}\b[^>]*\br="(\d+)"',
                                xml[opening.end():close]):
        if int(existing.group(1)) > row:
            insert = opening.end() + existing.start()
            break
    return xml[:insert] + new_row + xml[insert:], False


def _recalculate_on_open(workbook: str) -> str:
    prefix = namespace_prefix(workbook, MAIN) or ""
    calc_tag = qualified(prefix, "calcPr")
    calc = re.search(rf"<{re.escape(calc_tag)}\b([^>]*?)(/?)>", workbook)
    if calc:
        attributes = calc.group(1)
        if re.search(r'\bfullCalcOnLoad="', attributes):
            attributes = re.sub(r'\bfullCalcOnLoad="[^"]*"', 'fullCalcOnLoad="1"', attributes)
        else:
            attributes += ' fullCalcOnLoad="1"'
        return workbook[:calc.start()] + f"<{calc_tag}{attributes}{calc.group(2)}>" + workbook[calc.end():]
    # Not present: it goes after the elements the schema puts before it.
    anchor = -1
    for element in ("sheets", "functionGroups", "externalReferences", "definedNames"):
        closing = f"</{qualified(prefix, element)}>"
        position = workbook.find(closing)
        if position >= 0:
            anchor = max(anchor, position + len(closing))
    if anchor < 0:
        raise PackageError("the workbook has no list of sheets; the file is damaged")
    return workbook[:anchor] + f'<{calc_tag} fullCalcOnLoad="1"/>' + workbook[anchor:]


def _drop_calc_chain(package: Package, main: str, replacements: dict[str, bytes],
                     remove: set[str]) -> None:
    chain = _related(package, main, "/calcChain")
    if chain is None:
        return
    remove.add(chain)
    folder, _, name = main.rpartition("/")
    rels_part = f"{folder}/_rels/{name}.rels" if folder else f"_rels/{name}.rels"
    rels, bom = decode_part(package.read(rels_part))
    rels = re.sub(r'<(?:\w+:)?Relationship\b[^>]*Type="[^"]*/calcChain"[^>]*/>', "", rels)
    replacements[rels_part] = encode_part(rels, bom)
    types, bom = decode_part(package.read("[Content_Types].xml"))
    types = re.sub(r'<(?:\w+:)?Override\b[^>]*PartName="/' + re.escape(chain) + r'"[^>]*/>', "", types)
    replacements["[Content_Types].xml"] = encode_part(types, bom)


def set_cells(package: Package, sheet_name: str,
              values: dict[str, object]) -> tuple[bytes, list[str]]:
    """Set cells on one sheet. Returns the new file and the cells changed.

    Numbers are written as numbers, `True`/`False` as booleans, text beginning
    with `=` as a formula, `None` or `""` clears a cell (keeping its style), and
    anything else as text.
    """
    if not values:
        raise PackageError("there are no cells to change")
    main = main_part(package, "xl/workbook.xml")
    listed = workbook_sheets(package, main)
    info = (next((s for s in listed if s.name == sheet_name), None)
            or next((s for s in listed if s.name.lower() == sheet_name.strip().lower()), None))
    if info is None:
        raise PackageError(f"There is no sheet called {sheet_name!r}. The sheets are: "
                           + ", ".join(s.name for s in listed) + ".")
    xml, bom = decode_part(package.read(info.part))
    prefix = namespace_prefix(xml, MAIN)
    if prefix is None:
        raise PackageError(f"{info.name} is not a worksheet this can edit.")

    targets = []
    for ref, value in values.items():
        row, column = split_ref(ref)
        targets.append((row, column, column_letters(column) + str(row), value))
    targets.sort(key=lambda item: (item[0], item[1]))

    formula_replaced = False
    for row, column, ref, value in targets:
        xml, replaced = _put(xml, prefix, row, column, ref, value)
        formula_replaced = formula_replaced or replaced

    replacements = {info.part: encode_part(xml, bom)}
    workbook, wb_bom = decode_part(package.read(main))
    replacements[main] = encode_part(_recalculate_on_open(workbook), wb_bom)
    remove: set[str] = set()
    if formula_replaced:
        _drop_calc_chain(package, main, replacements, remove)
    return package.rewritten(replacements, remove), [t[2] for t in targets]


# -- creating ------------------------------------------------------------------------


def _typed(text: str) -> object:
    if re.fullmatch(r"-?(?:0|[1-9]\d{0,14})", text):
        return int(text)
    if re.fullmatch(r"-?(?:0|[1-9]\d{0,14})\.\d+", text):
        return float(text)
    if text.upper() in ("TRUE", "FALSE"):
        return text.upper() == "TRUE"
    return text


def parse_sheets(content: str) -> list[tuple[str, list[list[object]]]]:
    """`## Sheet name` headings, then rows as pipe tables or comma-separated lines.

    Numbers become numbers, TRUE/FALSE booleans, and text beginning with `=` a
    formula. Leading zeros keep a value as text, so an ID like 007 survives.
    """
    found: list[tuple[str, list[list[object]]]] = []
    name, rows = "Sheet1", []
    for line in content.splitlines():
        stripped = line.strip()
        heading = re.match(r"#{1,6}\s+(?:Sheet:\s*)?(.*)", stripped)
        if heading:
            if rows:
                found.append((name, rows))
                rows = []
            name = heading.group(1).strip() or name
            continue
        if not stripped:
            continue
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if any(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
        else:
            cells = [c.strip() for c in next(csv.reader([stripped]))]
        rows.append([_typed(c) for c in cells])
    if rows or not found:
        found.append((name, rows))
    return found


def _sheet_name(name: str, taken: set[str], number: int) -> str:
    clean = re.sub(r"[\[\]:*?/\\]", " ", clean_text(name)).strip().strip("'")[:31].strip()
    clean = clean or f"Sheet{number}"
    candidate, count = clean, 2
    while candidate.lower() in taken:
        suffix = f" ({count})"
        candidate = clean[:31 - len(suffix)] + suffix
        count += 1
    taken.add(candidate.lower())
    return candidate


def _sheet_xml(rows: list[list[object]]) -> str:
    header = len(rows) > 1 and all(isinstance(v, str) for v in rows[0] if v != "")
    body = []
    for number, row in enumerate(rows, 1):
        cells = "".join(
            _cell_xml("", f"{column_letters(c)}{number}", "1" if header and number == 1 else "", value)
            for c, value in enumerate(row, 1) if value != "")
        body.append(f'<row r="{number}">{cells}</row>')
    return XML_DECL + f'<worksheet xmlns="{MAIN}"><sheetData>{"".join(body)}</sheetData></worksheet>'


def create(sheets: list[tuple[str, list[list[object]]]], *, title: str) -> bytes:
    """A new .xlsx holding \a sheets. A first row of text is set in bold."""
    sheets = sheets or [("Sheet1", [])]
    taken: set[str] = set()
    names: list[str] = []
    parts: dict[str, str] = {}
    overrides = {"xl/workbook.xml": _WORKBOOK_TYPE, "xl/styles.xml": _STYLES_TYPE}
    for number, (name, rows) in enumerate(sheets, 1):
        names.append(_sheet_name(name, taken, number))
        overrides[f"xl/worksheets/sheet{number}.xml"] = _SHEET_TYPE
        parts[f"xl/worksheets/sheet{number}.xml"] = _sheet_xml(rows)
    overrides["docProps/core.xml"] = CORE_TYPE
    overrides["docProps/app.xml"] = APP_TYPE

    listing = "".join(f'<sheet name="{attribute(n)}" sheetId="{i}" r:id="rId{i}"/>'
                      for i, n in enumerate(names, 1))
    workbook = (XML_DECL + f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{listing}</sheets>'
                '<calcPr fullCalcOnLoad="1"/></workbook>')
    relations = [(f"rId{i}", REL + "/worksheet", f"worksheets/sheet{i}.xml")
                 for i in range(1, len(names) + 1)]
    relations.append((f"rId{len(names) + 1}", REL + "/styles", "styles.xml"))
    return build_package({
        "[Content_Types].xml": content_types(overrides),
        "_rels/.rels": relationships_xml([
            ("rId1", OFFICE_DOCUMENT, "xl/workbook.xml"),
            ("rId2", CORE_REL, "docProps/core.xml"),
            ("rId3", APP_REL, "docProps/app.xml"),
        ]),
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": relationships_xml(relations),
        "xl/styles.xml": _STYLES,
        **parts,
        "docProps/core.xml": core_properties(title),
        "docProps/app.xml": APP_PROPERTIES,
    })
