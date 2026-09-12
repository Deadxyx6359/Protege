"""Turning a document into unlockable knowledge.

Importing a text file already worked, but only as *one note with one set of
tags you type yourself*. A twenty-page set of lecture notes is not one topic;
it is a dozen, and typing a dozen topic ids by hand is exactly the friction
that stops someone teaching the model anything.

So this module reads the structure a document already has -- its headings --
and proposes one note per section, each with a topic id derived from its own
heading. A PDF of "Digital Circuits" with sections on Ohm's law, Kirchhoff and
Thevenin arrives as `dc_ohms_law`, `dc_kirchhoff`, `dc_thevenin`: three locked
topics sitting in the knowledge web, ready to be unlocked one at a time by
demonstrating them.

Nothing here bypasses the lock. Imported notes are notes: tagged with a locked
topic, they stay invisible to the model until that topic is unlocked, exactly
like a note typed by hand. Import is a faster way to *stock the shelves*, not a
way to skip the teaching -- which is the point of the application, and would be
a strange thing to undermine in the name of convenience.

Three formats, three levels of confidence:

* **Markdown and plain text** -- headings are explicit, or nearly so.
* **.docx** -- a ZIP of XML. Paragraph styles name their heading level
  outright, so the outline is exact.
* **.pdf** -- no structure at all, only positioned glyphs. Headings are
  inferred from type size (see `pdftext`), which is right for ordinary
  documents and wrong for anything that sets its headings in body-size bold.

The proposal is always shown before anything is written. Structure recovered by
inference is a suggestion, and the user is the one who knows what the document
is about.
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .vault import coerce_topic

MAX_DOCUMENT_BYTES = 20_000_000
# Longer than this and it is a paragraph that happens to be short, not a title.
MAX_HEADING_CHARS = 90
# A topic id long enough to be unreadable helps nobody.
MAX_TOPIC_WORDS = 4

DOCUMENT_SUFFIXES = (
    ("Documents", "*.pdf *.docx *.md *.markdown *.txt"),
    ("PDF", "*.pdf"),
    ("Word", "*.docx"),
    ("Markdown and text", "*.md *.markdown *.txt"),
    ("All files", "*.*"),
)


class DocumentError(ValueError):
    """The document cannot be read, with a reason the user can act on."""


@dataclass(frozen=True)
class Block:
    """One paragraph. `level` is 0 for body text, 1-6 for a heading."""

    text: str
    level: int = 0


@dataclass(frozen=True)
class Document:
    title: str
    blocks: tuple[Block, ...]
    source: str
    kind: str

    @property
    def headings(self) -> tuple[Block, ...]:
        return tuple(b for b in self.blocks if b.level)

    @property
    def word_count(self) -> int:
        return sum(len(b.text.split()) for b in self.blocks)


@dataclass
class ProposedNote:
    """One section, ready to be written -- or edited first, or dropped."""

    heading: str
    topic: str
    body: str
    include: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.body.split())


# --- reading -----------------------------------------------------------------


def extract(path: str | Path) -> Document:
    """Read any supported document into a title and a list of blocks."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise DocumentError(f"cannot read {path.name}: {exc}") from exc
    if size > MAX_DOCUMENT_BYTES:
        raise DocumentError(
            f"{path.name} is {size / 1_000_000:.0f} MB. Split it, or import the "
            "chapter you actually want to teach."
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DocumentError(f"cannot read {path.name}: {exc}") from exc

    suffix = path.suffix.lower()
    if suffix == ".pdf" or raw.startswith(b"%PDF"):
        blocks = _from_pdf(raw)
        kind = "pdf"
    elif suffix == ".docx" or raw.startswith(b"PK\x03\x04"):
        blocks = _from_docx(raw, path.name)
        kind = "docx"
    else:
        text = _as_text(raw, path.name)
        if suffix in (".md", ".markdown"):
            blocks, kind = _from_markdown(text), "markdown"
        else:
            blocks, kind = _from_plain(text), "text"

    blocks = tuple(b for b in blocks if b.text.strip())
    if not blocks:
        raise DocumentError(f"{path.name} has no readable text in it.")
    return Document(_title_of(blocks, path), blocks, path.name, kind)


def _as_text(raw: bytes, name: str) -> str:
    if b"\x00" in raw[:8192]:
        raise DocumentError(
            f"{name} looks like a binary file. Akira reads PDF, Word (.docx), "
            "Markdown and plain text."
        )
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentError(f"{name} is not text Akira can decode.")


def _title_of(blocks: tuple[Block, ...], path: Path) -> str:
    for block in blocks:
        if block.level:
            return block.text
    return path.stem.replace("_", " ").replace("-", " ").strip() or path.name


# --- .docx -------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _from_docx(raw: bytes, name: str) -> list[Block]:
    """Paragraphs and their outline level, straight out of word/document.xml.

    A .docx is a ZIP of XML, so this needs no parser beyond the standard
    library, and paragraph styles carry the heading level explicitly -- which
    makes Word the one format whose outline is recovered exactly rather than
    guessed at.
    """
    import io
    from xml.etree import ElementTree

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise DocumentError(f"{name} is not a readable .docx file: {exc}") from exc
    try:
        with archive.open("word/document.xml") as handle:
            payload = handle.read()
    except KeyError:
        raise DocumentError(
            f"{name} is a ZIP but not a Word document. If it is an .doc from an "
            "older Word, open it and Save As .docx."
        ) from None
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise DocumentError(f"{name} has damaged internal XML: {exc}") from exc

    blocks: list[Block] = []
    for paragraph in root.iter(f"{_W}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{_W}t")).strip()
        if not text:
            continue
        blocks.append(Block(text, _docx_level(paragraph)))
    return blocks


def _docx_level(paragraph) -> int:
    for style in paragraph.iter(f"{_W}pStyle"):
        value = (style.get(f"{_W}val") or "").lower()
        match = re.fullmatch(r"heading\s*([1-9])", value)
        if match:
            return min(6, int(match.group(1)))
        if value in ("title", "subtitle"):
            return 1
    for outline in paragraph.iter(f"{_W}outlineLvl"):
        try:
            return min(6, int(outline.get(f"{_W}val", "9")) + 1)
        except ValueError:
            return 0
    return 0


# --- markdown and plain text --------------------------------------------------


def _from_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(Block(" ".join(paragraph).strip()))
            paragraph.clear()

    for line in text.splitlines():
        heading = re.match(r"\s{0,3}(#{1,6})\s+(.*)", line)
        if heading:
            flush()
            blocks.append(Block(heading.group(2).strip(), len(heading.group(1))))
            continue
        underline = re.fullmatch(r"\s{0,3}(=+|-+)\s*", line)
        if underline and paragraph and len(paragraph) == 1:
            blocks.append(Block(paragraph[0], 1 if "=" in line else 2))
            paragraph.clear()
            continue
        if not line.strip():
            flush()
            continue
        paragraph.append(line.strip())
    flush()
    return blocks


def _from_plain(text: str) -> list[Block]:
    """Plain text has no headings, only lines that look like one.

    Deliberately timid: a short line, no sentence-ending punctuation, and blank
    space around it. Over-detecting here would shatter a document into dozens
    of one-line topics, which is worse than proposing a single note the user
    can split themselves.
    """
    lines = text.splitlines()
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(Block(" ".join(paragraph).strip()))
            paragraph.clear()

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        before_blank = index == 0 or not lines[index - 1].strip()
        after_blank = index + 1 >= len(lines) or not lines[index + 1].strip()
        looks_like_heading = (
            before_blank and after_blank
            and len(stripped) <= MAX_HEADING_CHARS
            and not stripped.endswith((".", ",", ";", ":"))
            and len(stripped.split()) <= 10
        )
        if looks_like_heading:
            flush()
            blocks.append(Block(stripped, 1))
            continue
        paragraph.append(stripped)
    flush()
    return blocks


# --- pdf ---------------------------------------------------------------------


def _from_pdf(raw: bytes) -> list[Block]:
    """Rank type sizes to recover an outline a PDF never recorded.

    The body size is the one most of the *characters* are set in -- counting
    lines instead would let a title page full of short lines outvote the body.
    Anything a clear step larger is a heading, and the distinct larger sizes,
    ranked, give the levels.
    """
    from .pdftext import PdfError, extract_lines

    try:
        lines = extract_lines(raw)
    except PdfError as exc:
        raise DocumentError(str(exc)) from exc

    weight: Counter[float] = Counter()
    for line in lines:
        weight[round(line.size, 1)] += len(line.text)
    body_size = weight.most_common(1)[0][0] if weight else 0.0

    bigger = sorted({s for s in weight if s > body_size * 1.12}, reverse=True)
    level_of = {size: min(6, rank + 1) for rank, size in enumerate(bigger)}

    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(Block(" ".join(paragraph).strip()))
            paragraph.clear()

    for line in lines:
        text = line.text.strip()
        if not text:
            continue
        level = level_of.get(round(line.size, 1), 0)
        if level and len(text) <= MAX_HEADING_CHARS:
            flush()
            blocks.append(Block(text, level))
            continue
        paragraph.append(text)
        # A line ending in sentence punctuation closes the paragraph; PDFs
        # break lines for layout, not for meaning, so joining is the default.
        if text.endswith((".", "!", "?", ":")) and len(" ".join(paragraph)) > 240:
            flush()
    flush()
    return blocks


# --- proposing notes ----------------------------------------------------------


_STOPWORDS = frozenset(
    "a an and are as at be by for from how in into is it of on or that the to "
    "what when where which who why with your you".split()
)

# Words that describe the *document* rather than its subject. "Study Guide:
# Solar Energy Lecture 4A" is about solar energy; a domain called `study_guide`
# would collect every unrelated handout under one branch of the knowledge web
# and tell the user nothing about any of them.
_DOCUMENT_WORDS = frozenset(
    "study guide guides lecture lectures notes note summary summaries chapter "
    "section part unit week day slides slide handout handouts syllabus review "
    "reviewer exam exams midterm final finals draft final_draft copy version "
    "outline overview intro introduction pdf docx document documents worksheet "
    "homework assignment quiz test paper report".split()
)
# Below this a section is a caption or a table cell, not a topic. Merged into
# whatever came before rather than proposed as something to teach.
MIN_SECTION_WORDS = 30
# A proposal past this size is noise the user has to wade through, not help.
MAX_PROPOSED_NOTES = 40


def slug_words(text: str, limit: int = MAX_TOPIC_WORDS) -> str:
    """The memorable part of a heading, as topic-id words.

    Leading numbering goes ("3.2 Thevenin's Theorem" is about Thevenin, not
    about 3.2), then stopwords, then everything past the word limit. What
    survives has to still read as the heading it came from -- a topic id is
    something the user types into an unlock dialog and recognises in the
    knowledge web.
    """
    text = re.sub(r"^\s*(chapter|section|part|lecture|unit|appendix)\b", " ", text, flags=re.I)
    # "3.2 ", "4 - ", "II. " -- the whole numbering token, not just its first
    # digit. Stripping one character at a time left "3.2 Thevenin" as
    # `2_thevenin`, which is a worse id than the one it replaced.
    text = re.sub(r"^\s*\d+(?:\.\d+)*\s*[.)\-:]?\s*", " ", text)
    words = [w for w in re.split(r"[^0-9A-Za-z]+", text.lower()) if w]
    kept = [w for w in words if w not in _STOPWORDS] or words
    return "_".join(kept[:limit])


def subject_words(text: str, limit: int = 2, *, strict: bool = False) -> str:
    """The words that say what something is *about*.

    `strict` returns nothing rather than falling back to the words it just
    rejected. Used when there is another candidate to try: a report whose first
    heading is "1. Introduction" should be named after its filename, not
    land in the knowledge web as a domain called `introduction`.
    """
    words = [w for w in slug_words(text, limit=12).split("_") if w]
    meaningful = [
        w for w in words
        # "6ab", "4a", "2" -- numbering that survived the leading-number strip.
        if w not in _DOCUMENT_WORDS and not re.fullmatch(r"\d+[a-z]*", w)
    ]
    if not meaningful and strict:
        return ""
    return "_".join((meaningful or words)[:limit])


def suggest_domain(document: Document) -> str:
    """A short prefix shared by every topic from this document.

    Topics group into domains by their first underscore-separated segment, so
    the prefix is what decides whether an import lands as one legible branch of
    the knowledge web or scatters across it.

    The filename is consulted as well as the title, and for a PDF it is trusted
    *more*: a PDF has no title, only whichever line happened to be set largest,
    and that is as likely to be a table header halfway down page four as
    anything describing the document.
    """
    candidates = [Path(document.source).stem, document.title]
    if document.kind != "pdf":
        candidates.reverse()
    for strict in (True, False):
        for candidate in candidates:
            slug = coerce_topic(subject_words(candidate, strict=strict))
            if slug:
                return slug
    return "imported"


def propose_notes(document: Document, domain: str) -> list[ProposedNote]:
    """Split the document into one note per section.

    Splitting happens at a single heading level -- deeper headings stay inside
    their section as markdown, because they are what the section is *made of*.
    Which level is chosen matters more than it sounds:

    * The shallowest level is tried first, and abandoned if it yields only one
      section. A Word document whose only Heading 1 is its own title would
      otherwise import as a single undifferentiated wall.
    * Sections shorter than `MIN_SECTION_WORDS` merge into the one before them.
      A PDF's inferred headings include every table header and figure caption,
      and each of those would otherwise become a topic with nothing in it --
      dozens of empty branches in the knowledge web, all of them lies about
      what the document contains.
    """
    domain = coerce_topic(domain) or "imported"
    levels = sorted({b.level for b in document.blocks if b.level})
    if not levels:
        return [_note(domain, document.title, _render(document.blocks), set(),
                      whole_document=True)]

    for level in levels:
        sections = _split_at(document, level)
        if len(sections) >= 2:
            break
    else:
        sections = _split_at(document, levels[0])

    notes: list[ProposedNote] = []
    used: set[str] = set()
    carried = ""
    for heading, blocks in sections:
        body = _render(blocks)
        if not body.strip():
            continue
        if carried:
            body = f"{carried}\n\n{body}".strip()
            carried = ""
        if len(body.split()) < MIN_SECTION_WORDS:
            # Too small to stand alone. Fold it into the neighbouring section
            # rather than dropping it -- but forward if there is nothing behind
            # it yet, which is the common case of a document opening with its
            # own title above the first real section.
            fragment = f"## {heading}\n\n{body}" if heading else body
            if notes:
                notes[-1].body = f"{notes[-1].body}\n\n{fragment}".strip()
            else:
                carried = fragment
            continue
        notes.append(_note(domain, heading, body, used))
    if carried:
        notes.append(_note(domain, document.title, carried, used))

    if len(notes) > MAX_PROPOSED_NOTES:
        tail = notes[MAX_PROPOSED_NOTES - 1:]
        notes = notes[:MAX_PROPOSED_NOTES - 1]
        merged = "\n\n".join(f"## {n.heading}\n\n{n.body}" for n in tail)
        notes.append(_note(domain, "remainder", merged, used))
        notes[-1].warnings.append(
            f"{len(tail)} further sections were merged here -- split them by hand "
            "if any deserves its own topic"
        )
    return notes


def _split_at(document: Document, level: int) -> list[tuple[str, list[Block]]]:
    """(heading, blocks) pairs, cut at every heading of exactly `level`.

    The first pair carries an empty heading when the document opens with body
    text before any heading.
    """
    sections: list[tuple[str, list[Block]]] = []
    heading = ""
    current: list[Block] = []
    for block in document.blocks:
        if block.level == level:
            if heading or any(b.text.strip() for b in current):
                sections.append((heading, current))
            heading, current = block.text, []
            continue
        current.append(block)
    if heading or any(b.text.strip() for b in current):
        sections.append((heading, current))
    return sections


def _render(blocks) -> str:
    out = []
    for block in blocks:
        if block.level:
            out.append(f"\n{'#' * min(6, block.level + 1)} {block.text}\n")
        else:
            out.append(block.text)
    return "\n\n".join(part.strip() for part in out if part.strip()).strip()


def _note(domain: str, heading: str, body: str, used: set[str], *,
          whole_document: bool = False) -> ProposedNote:
    if whole_document:
        # No headings anywhere: the document *is* the topic.
        tail = ""
    else:
        # A section headed by the document's own title would otherwise produce
        # `solar_energy_solar_energy_lecture`. Anything the domain already says
        # is dropped, as is bare numbering.
        domain_words = set(domain.split("_"))
        tail = "_".join(
            w for w in slug_words(heading).split("_")
            if w and w not in domain_words and not re.fullmatch(r"\d+[a-z]*", w)
        )
        # "intro", not "overview": documents very often have their own section
        # called Overview, and colliding with it forces an ugly numbered id.
        tail = tail or "intro"
    topic = coerce_topic(f"{domain}_{tail}" if tail else domain) or domain
    warnings: list[str] = []
    if topic in used:
        suffix = 2
        while coerce_topic(f"{topic}_{suffix}") in used:
            suffix += 1
        topic = coerce_topic(f"{topic}_{suffix}") or topic
        warnings.append("a section above proposed the same id, so this one is numbered")
    used.add(topic)
    if len(body.split()) < MIN_SECTION_WORDS:
        warnings.append("very short -- probably not enough to teach or unlock from")
    return ProposedNote(
        heading=heading.strip() or "(opening section)", topic=topic,
        body=body, warnings=warnings,
    )


# --- writing ------------------------------------------------------------------


def write_notes(directory: Path, notes: list[ProposedNote], document: Document,
                imported_at: str) -> list[Path]:
    """Write the included notes as topic-tagged vault notes. Returns the paths.

    One file per note, named after its topic so the vault browser reads the way
    the knowledge web does. Each carries the section heading and source
    filename in its frontmatter, because six months from now "where did this
    come from" is the first question anyone asks of an imported note.
    """
    from .store import write_text
    from .vault import render_note

    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for note in notes:
        if not note.include or not note.body.strip():
            continue
        topic = coerce_topic(note.topic)
        if topic is None:
            raise DocumentError(
                f"'{note.topic}' cannot be used as a topic id. Letters, digits and "
                "underscores, starting with a letter."
            )
        # The topic id *is* the filename. It is already restricted to letters,
        # digits and underscores, and naming the file after the topic means the
        # vault browser and the knowledge web read the same way -- passing it
        # through the generic slugifier turned the underscores into hyphens and
        # broke that correspondence for no benefit.
        target = directory / f"{topic}.md"
        counter = 2
        while target.exists():
            target = directory / f"{topic}-{counter}.md"
            counter += 1
        write_text(target, render_note(
            [topic],
            f"# {note.heading}\n\n{note.body}".strip(),
            extra={
                "kind": "imported",
                "source_file": document.source,
                "source_section": note.heading,
                "imported_at": imported_at,
            },
        ))
        written.append(target)
    return written
