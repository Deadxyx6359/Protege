"""PowerPoint decks: read slide by slide, and edit their text in place.

Reading follows the deck's own order — the slide list in `presentation.xml`,
not the order the parts happen to sit in the ZIP — and separates each slide's
title from its body, keeps bullet levels, reads tables, and includes the
speaker notes, which is often where the real content of a talk lives.

Editing replaces text across runs in the slides and their notes, and leaves
everything else — layouts, images, animations, the master — exactly as it was.

Creating a deck from nothing is deliberately not here yet. A valid deck needs a
slide master, a layout and a theme, and one that PowerPoint quietly "repairs"
on opening is worse than none. Until that can be checked against PowerPoint
itself, decks are made in PowerPoint and edited here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ooxml import (
    REL,
    Package,
    decode_part,
    encode_part,
    main_part,
    replace_text,
)

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "{%s}" % P
_A = "{%s}" % A
_R = "{%s}" % REL


@dataclass(frozen=True, slots=True)
class Slide:
    number: int
    title: str
    lines: tuple[tuple[int, str], ...]
    """(bullet level, text) for everything on the slide that is not its title."""
    notes: str
    part: str
    notes_part: str | None


def slide_parts(package: Package) -> list[str]:
    """The slides' part names, in the order the deck presents them."""
    main = main_part(package, "ppt/presentation.xml")
    relations = package.relationships(main)
    listing = package.xml(main).find(f"{_P}sldIdLst")
    parts = []
    for slide in listing.findall(f"{_P}sldId") if listing is not None else ():
        relation = relations.get(slide.get(f"{_R}id", ""))
        if relation and relation[0].endswith("/slide") and package.has(relation[1]):
            parts.append(relation[1])
    return parts


def _paragraphs(body) -> list[tuple[int, str]]:
    out = []
    for paragraph in body.findall(f"{_A}p") if body is not None else ():
        pieces = []
        for node in paragraph.iter():
            if node.tag == f"{_A}t":
                pieces.append(node.text or "")
            elif node.tag == f"{_A}br":
                pieces.append("\n")
        text = "".join(pieces).strip()
        if not text:
            continue
        properties = paragraph.find(f"{_A}pPr")
        level = properties.get("lvl", "0") if properties is not None else "0"
        out.append((int(level) if level.isdigit() else 0, text))
    return out


def _placeholder(shape) -> str | None:
    ph = shape.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
    return None if ph is None else ph.get("type", "body")


def _notes_part(package: Package, part: str) -> str | None:
    for kind, target in package.relationships(part).values():
        if kind.endswith("/notesSlide") and package.has(target):
            return target
    return None


def read(package: Package) -> list[Slide]:
    slides = []
    for number, part in enumerate(slide_parts(package), 1):
        root = package.xml(part)
        title = ""
        lines: list[tuple[int, str]] = []
        for shape in root.iter(f"{_P}sp"):
            paragraphs = _paragraphs(shape.find(f"{_P}txBody"))
            if not paragraphs:
                continue
            if _placeholder(shape) in ("title", "ctrTitle") and not title:
                title = " ".join(text for _, text in paragraphs)
            else:
                lines.extend(paragraphs)
        for table in root.iter(f"{_A}tbl"):
            for row in table.findall(f"{_A}tr"):
                cells = [" ".join(t for _, t in _paragraphs(cell.find(f"{_A}txBody")))
                         for cell in row.findall(f"{_A}tc")]
                lines.append((0, " | ".join(cells)))

        notes_part = _notes_part(package, part)
        notes = []
        if notes_part:
            for shape in package.xml(notes_part).iter(f"{_P}sp"):
                if _placeholder(shape) == "body":
                    notes.extend(text for _, text in _paragraphs(shape.find(f"{_P}txBody")))
        slides.append(Slide(number, title, tuple(lines), "\n".join(notes), part, notes_part))
    return slides


def render(slides: list[Slide]) -> str:
    out: list[str] = []
    for slide in slides:
        if out:
            out.append("")
        out.append(f"## Slide {slide.number}" + (f" — {slide.title}" if slide.title else ""))
        out.extend("  " * level + "- " + text for level, text in slide.lines)
        if slide.notes:
            out.append("Notes: " + slide.notes.replace("\n", " "))
    return "\n".join(out)


def replace(package: Package, find: str, replacement: str) -> tuple[bytes, int]:
    """Replace \a find in every slide and its notes. Returns the new file and the count."""
    parts: list[str] = []
    for part in slide_parts(package):
        parts.append(part)
        notes = _notes_part(package, part)
        if notes:
            parts.append(notes)
    replacements: dict[str, bytes] = {}
    total = 0
    for part in parts:
        xml, bom = decode_part(package.read(part))
        # DrawingML keeps whitespace as written, so no xml:space is needed.
        edited, count = replace_text(xml, A, "p", "t", find, replacement, preserve_space=False)
        if count:
            replacements[part] = encode_part(edited, bom)
            total += count
    if not total:
        return package.raw, 0
    return package.rewritten(replacements), total
