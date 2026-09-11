"""Word documents: read with their structure, edited in place, created new.

Reading recovers what matters to a reader — headings and their levels,
paragraphs, bulleted items, tables — and renders it as plain Markdown-ish text
a model can work with. Heading levels come from the styles part when there is
one, because a style's outline level is authoritative and its id is not: a
German Word calls Heading 1 "Berschrift1".

Editing replaces text across runs (see `ooxml.replace_text`) in the body,
headers, footers, footnotes and endnotes, and leaves every other byte alone.
Tracked deletions (`w:delText`) and field codes (`w:instrText`) are never
touched, since they are not visible text.

Creating builds a small, valid package from an outline: headings, paragraphs,
bulleted items and tables, with styles Word recognises, so headings appear in
its navigation pane.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
    build_package,
    clean_text,
    content_types,
    core_properties,
    decode_part,
    encode_part,
    escape,
    main_part,
    relationships_xml,
    replace_text,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = "{%s}" % W

_DOCUMENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_STYLES_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
_STYLES_REL = REL + "/styles"

#: US Letter with one-inch margins, in twentieths of a point.
_TEXT_WIDTH = 9360
_SECTION = ('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" '
            'w:right="1440" w:bottom="1440" w:left="1440" w:header="720" '
            'w:footer="720" w:gutter="0"/></w:sectPr>')


@dataclass(frozen=True, slots=True)
class Block:
    """One piece of a document's structure."""

    kind: str
    """`heading`, `paragraph`, `bullet` or `table`."""
    text: str = ""
    level: int = 0
    rows: tuple[tuple[str, ...], ...] = ()


# -- reading ------------------------------------------------------------------------


def _outline(value: str | None) -> int:
    """An outline level attribute as a heading level; 0 for body text."""
    try:
        number = int(value or "9")
    except ValueError:
        return 0
    return number + 1 if 0 <= number < 9 else 0


def _style_levels(package: Package, folder: str) -> dict[str, int]:
    part = f"{folder}/styles.xml" if folder else "styles.xml"
    if not package.has(part):
        return {}
    levels: dict[str, int] = {}
    for style in package.xml(part).iter(f"{_W}style"):
        if style.get(f"{_W}type") != "paragraph":
            continue
        name_node = style.find(f"{_W}name")
        name = (name_node.get(f"{_W}val", "") if name_node is not None else "").lower()
        outline = style.find(f"{_W}pPr/{_W}outlineLvl")
        level = _outline(outline.get(f"{_W}val")) if outline is not None else 0
        named = re.fullmatch(r"heading\s*([1-9])", name)
        if named:
            level = int(named.group(1))
        elif name == "title":
            level = 1
        if level:
            levels[style.get(f"{_W}styleId", "")] = min(level, 6)
    return levels


def _paragraph_text(paragraph) -> str:
    pieces = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            pieces.append(node.text or "")
        elif node.tag == f"{_W}tab":
            pieces.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            pieces.append("\n")
    return "".join(pieces).strip()


def _level(paragraph, styles: dict[str, int]) -> int:
    properties = paragraph.find(f"{_W}pPr")
    if properties is None:
        return 0
    outline = properties.find(f"{_W}outlineLvl")
    if outline is not None:
        return min(_outline(outline.get(f"{_W}val")), 6)
    style = properties.find(f"{_W}pStyle")
    if style is not None:
        style_id = style.get(f"{_W}val", "")
        if style_id in styles:
            return styles[style_id]
        named = re.fullmatch(r"heading\s*([1-9])", style_id.lower())
        if named:
            return min(int(named.group(1)), 6)
        if style_id.lower() == "title":
            return 1
    return 0


def _is_bullet(paragraph) -> bool:
    properties = paragraph.find(f"{_W}pPr")
    if properties is None:
        return False
    if properties.find(f"{_W}numPr") is not None:
        return True
    style = properties.find(f"{_W}pStyle")
    return style is not None and "list" in style.get(f"{_W}val", "").lower()


def _walk(container, styles: dict[str, int], blocks: list[Block]) -> None:
    for child in container:
        if child.tag == f"{_W}p":
            text = _paragraph_text(child)
            if not text:
                continue
            level = _level(child, styles)
            if level:
                blocks.append(Block("heading", text, level))
            elif _is_bullet(child):
                # A typed bullet glyph, as `create` writes, is list furniture,
                # not part of the item.
                blocks.append(Block("bullet", re.sub(r"^[•·▪◦‣]\s*", "", text)))
            else:
                blocks.append(Block("paragraph", text))
        elif child.tag == f"{_W}tbl":
            rows = []
            for row in child.findall(f"{_W}tr"):
                cells = []
                for cell in row.findall(f"{_W}tc"):
                    texts = [_paragraph_text(p) for p in cell.iter(f"{_W}p")]
                    cells.append(" ".join(t for t in texts if t))
                rows.append(tuple(cells))
            if rows:
                blocks.append(Block("table", rows=tuple(rows)))
        elif child.tag == f"{_W}sdt":
            content = child.find(f"{_W}sdtContent")
            if content is not None:
                _walk(content, styles, blocks)


def read(package: Package) -> list[Block]:
    main = main_part(package, "word/document.xml")
    body = package.xml(main).find(f"{_W}body")
    if body is None:
        raise PackageError(f"{package.name} is not a Word document.")
    blocks: list[Block] = []
    _walk(body, _style_levels(package, main.rpartition("/")[0]), blocks)
    return blocks


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(blocks: list[Block]) -> str:
    """Blocks as Markdown-ish text: `#` headings, `-` bullets, pipe tables."""
    out: list[str] = []
    previous = ""
    for block in blocks:
        if out and not (block.kind == previous == "bullet"):
            out.append("")
        if block.kind == "heading":
            out.append("#" * block.level + " " + block.text)
        elif block.kind == "bullet":
            out.append("- " + block.text)
        elif block.kind == "table":
            width = max(len(row) for row in block.rows)
            for index, row in enumerate(block.rows):
                cells = list(row) + [""] * (width - len(row))
                out.append("| " + " | ".join(_cell(c) for c in cells) + " |")
                if index == 0:
                    out.append("|" + "---|" * width)
        else:
            out.append(block.text)
        previous = block.kind
    return "\n".join(out)


# -- editing ------------------------------------------------------------------------


def text_parts(package: Package) -> list[str]:
    """The parts that hold visible text: the body, headers, footers and notes."""
    main = main_part(package, "word/document.xml")
    folder = main.rpartition("/")[0]
    pattern = re.compile(re.escape(folder) + r"/(?:header\d*|footer\d*|footnotes|endnotes)\.xml")
    return [main] + sorted(name for name in package.names() if pattern.fullmatch(name))


def replace(package: Package, find: str, replacement: str) -> tuple[bytes, int]:
    """Replace \a find everywhere it is visible. Returns the new file and the count."""
    replacements: dict[str, bytes] = {}
    total = 0
    for part in text_parts(package):
        xml, bom = decode_part(package.read(part))
        edited, count = replace_text(xml, W, "p", "t", find, replacement, preserve_space=True)
        if count:
            replacements[part] = encode_part(edited, bom)
            total += count
    if not total:
        return package.raw, 0
    return package.rewritten(replacements), total


# -- creating -------------------------------------------------------------------------


def parse_outline(content: str) -> list[Block]:
    """Markdown-ish text as blocks: `#` headings, `-` bullets, pipe tables."""
    blocks: list[Block] = []
    paragraph: list[str] = []
    table: list[tuple[str, ...]] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(Block("paragraph", " ".join(paragraph)))
            paragraph.clear()

    def flush_table() -> None:
        if table:
            blocks.append(Block("table", rows=tuple(table)))
            table.clear()

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            flush_paragraph()
            cells = tuple(c.strip() for c in stripped.strip("|").split("|"))
            if any(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            table.append(cells)
            continue
        flush_table()
        if not stripped:
            flush_paragraph()
            continue
        heading = re.match(r"(#{1,6})\s+(.*)", stripped)
        if heading:
            flush_paragraph()
            blocks.append(Block("heading", heading.group(2).strip(), min(len(heading.group(1)), 3)))
            continue
        bullet = re.match(r"[-*•]\s+(.*)", stripped)
        if bullet:
            flush_paragraph()
            blocks.append(Block("bullet", bullet.group(1).strip()))
            continue
        paragraph.append(stripped)
    flush_paragraph()
    flush_table()
    return blocks


def _text_run(text: str, bold: bool = False) -> str:
    text = clean_text(text)
    space = ' xml:space="preserve"' if text != text.strip() else ""
    properties = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f"<w:r>{properties}<w:t{space}>{escape(text)}</w:t></w:r>"


def _paragraph(text: str, style: str = "", bold: bool = False) -> str:
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{properties}{_text_run(text, bold)}</w:p>"


def _block_xml(block: Block) -> str:
    if block.kind == "heading":
        return _paragraph(block.text, f"Heading{max(1, min(block.level, 3))}")
    if block.kind == "bullet":
        return ('<w:p><w:pPr><w:pStyle w:val="ListBullet"/></w:pPr>'
                '<w:r><w:t>•</w:t></w:r><w:r><w:tab/></w:r>'
                f'{_text_run(block.text)}</w:p>')
    if block.kind == "table":
        width = max(len(row) for row in block.rows)
        column = _TEXT_WIDTH // max(width, 1)
        sides = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                        for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
        grid = "".join(f'<w:gridCol w:w="{column}"/>' for _ in range(width))
        rows = []
        for index, row in enumerate(block.rows):
            cells = list(row) + [""] * (width - len(row))
            rows.append("<w:tr>" + "".join(
                f'<w:tc><w:tcPr><w:tcW w:w="{column}" w:type="dxa"/></w:tcPr>'
                f"{_paragraph(cell, bold=index == 0)}</w:tc>" for cell in cells) + "</w:tr>")
        return (f'<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>{sides}'
                f'</w:tblBorders></w:tblPr><w:tblGrid>{grid}</w:tblGrid>{"".join(rows)}</w:tbl>'
                # Word wants a paragraph after a table, or it adds one itself.
                "<w:p/>")
    return _paragraph(block.text)


def _heading_style(level: int, size: int) -> str:
    return (f'<w:style w:type="paragraph" w:styleId="Heading{level}"><w:name w:val="heading {level}"/>'
            '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
            f'<w:pPr><w:keepNext/><w:spacing w:before="{360 - level * 60}" w:after="120"/>'
            f'<w:outlineLvl w:val="{level - 1}"/></w:pPr>'
            f'<w:rPr><w:b/><w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr></w:style>')


_STYLES = (XML_DECL + f'<w:styles xmlns:w="{W}">'
           '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" '
           'w:eastAsia="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:szCs w:val="22"/>'
           '<w:lang w:val="en-US"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>'
           '<w:spacing w:after="160" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
           '</w:docDefaults>'
           '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>'
           '<w:qFormat/></w:style>'
           + _heading_style(1, 32) + _heading_style(2, 26) + _heading_style(3, 24) +
           '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/>'
           '<w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="60"/>'
           '<w:ind w:left="360" w:hanging="360"/></w:pPr></w:style>'
           "</w:styles>")


def create(blocks: list[Block], *, title: str) -> bytes:
    """A new .docx holding \a blocks."""
    body = "".join(_block_xml(block) for block in blocks) or "<w:p/>"
    document = XML_DECL + f'<w:document xmlns:w="{W}"><w:body>{body}{_SECTION}</w:body></w:document>'
    return build_package({
        "[Content_Types].xml": content_types({
            "word/document.xml": _DOCUMENT_TYPE,
            "word/styles.xml": _STYLES_TYPE,
            "docProps/core.xml": CORE_TYPE,
            "docProps/app.xml": APP_TYPE,
        }),
        "_rels/.rels": relationships_xml([
            ("rId1", OFFICE_DOCUMENT, "word/document.xml"),
            ("rId2", CORE_REL, "docProps/core.xml"),
            ("rId3", APP_REL, "docProps/app.xml"),
        ]),
        "word/document.xml": document,
        "word/_rels/document.xml.rels": relationships_xml([("rId1", _STYLES_REL, "styles.xml")]),
        "word/styles.xml": _STYLES,
        "docProps/core.xml": core_properties(title),
        "docProps/app.xml": APP_PROPERTIES,
    })
