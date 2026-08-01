"""Documents into unlockable topics.

The feature exists to remove the one piece of friction that stops someone
teaching the model anything: typing a dozen topic ids by hand for a document
that already has a dozen headings. So the tests care about two things --
whether the outline is recovered, and whether the ids that come out of it are
ones a person would recognise later in the knowledge web.

They also pin the boundary that matters: importing writes *locked* notes.
A convenience that quietly unlocked what it imported would be a shortcut around
the entire point of the program.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from protege.documents import (
    Block,
    Document,
    DocumentError,
    ProposedNote,
    extract,
    propose_notes,
    slug_words,
    subject_words,
    suggest_domain,
    write_notes,
)
from protege.vault import extract_topics, parse_frontmatter


def docx_bytes(paragraphs: list[tuple[str, int]]) -> bytes:
    """A minimal but real .docx: a ZIP with one word/document.xml."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = []
    for text, level in paragraphs:
        style = f'<w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>' if level else ""
        body.append(f"<w:p>{style}<w:r><w:t>{text}</w:t></w:r></w:p>")
    xml = f'<?xml version="1.0"?><w:document {ns}><w:body>{"".join(body)}</w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def write(tmp_path, name: str, data: bytes | str):
    path = tmp_path / name
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


LONG = "Sentence number {} explaining the material in enough words to count. " * 6


# --- reading -----------------------------------------------------------------


def test_docx_headings_come_through_exactly(tmp_path):
    """Word names its heading levels outright, so this one is not guesswork."""
    path = write(tmp_path, "notes.docx", docx_bytes([
        ("Solar Cells", 1),
        ("The photovoltaic effect converts light to current.", 0),
        ("Fill Factor", 2),
        ("Ratio of maximum power to the product of Voc and Isc.", 0),
    ]))
    document = extract(path)
    assert document.kind == "docx"
    assert [(b.text.split()[0], b.level) for b in document.blocks] == [
        ("Solar", 1), ("The", 0), ("Fill", 2), ("Ratio", 0),
    ]


def test_markdown_headings_and_setext(tmp_path):
    path = write(tmp_path, "notes.md", "Title\n=====\n\nBody text.\n\n## Sub\n\nMore.\n")
    document = extract(path)
    assert [(b.text, b.level) for b in document.blocks] == [
        ("Title", 1), ("Body text.", 0), ("Sub", 2), ("More.", 0),
    ]


def test_plain_text_only_guesses_at_obvious_headings(tmp_path):
    """Over-detection would shatter a document into one-line topics."""
    path = write(tmp_path, "notes.txt",
                 "Ohm's Law\n\nVoltage equals current times resistance.\n"
                 "It is the first thing anyone learns.\n")
    document = extract(path)
    assert document.blocks[0] == Block("Ohm's Law", 1)
    assert document.blocks[1].level == 0


def test_a_binary_file_is_refused_with_a_reason(tmp_path):
    path = write(tmp_path, "thing.bin", b"\x00\x01\x02binary")
    with pytest.raises(DocumentError, match="binary"):
        extract(path)


def test_an_empty_document_is_refused(tmp_path):
    with pytest.raises(DocumentError):
        extract(write(tmp_path, "empty.txt", "   \n\n  \n"))


def test_a_zip_that_is_not_word_says_so(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(DocumentError, match="not a Word document"):
        extract(write(tmp_path, "thing.docx", buffer.getvalue()))


# --- naming ------------------------------------------------------------------


def test_slug_drops_leading_numbering():
    """"3.2 Thevenin's Theorem" is about Thevenin, not about 3.2."""
    assert slug_words("3.2 Thevenin's Theorem") == "thevenin_s_theorem"
    assert slug_words("Chapter 4 - Diodes") == "diodes"


def test_subject_words_ignore_words_about_the_document():
    """A domain called `study_guide` collects unrelated handouts under one branch."""
    assert subject_words("Study Guide: Solar Energy Lecture 4A") == "solar_energy"
    assert subject_words("FPGA_Midterm_Report") == "fpga"


def test_a_generic_title_defers_to_the_filename():
    """A report whose first heading is "1. Introduction" is not about introductions."""
    document = Document(
        title="1. Introduction",
        blocks=(Block("1. Introduction", 1), Block(LONG, 0)),
        source="FPGA_Midterm_Report.docx",
        kind="docx",
    )
    assert suggest_domain(document) == "fpga"


def test_a_pdf_trusts_its_filename_over_its_biggest_line():
    """A PDF has no title -- only whichever line was set largest, which may be
    a table header on page four."""
    document = Document(
        title="Delivery: Fully hands-on and Project-based Learning",
        blocks=(Block("Delivery: Fully hands-on", 1), Block(LONG, 0)),
        source="AI_Agents_Syllabus_2026.pdf",
        kind="pdf",
    )
    assert suggest_domain(document) == "ai_agents"


# --- proposing ---------------------------------------------------------------


def proposal(paragraphs, source="doc.docx", kind="docx", title=None):
    blocks = tuple(Block(t, level) for t, level in paragraphs)
    document = Document(title or blocks[0].text, blocks, source, kind)
    return document, propose_notes(document, suggest_domain(document))


def test_one_note_per_section_with_ids_from_the_headings():
    _doc, notes = proposal([
        ("Solar Cells", 1),
        ("Key Concepts", 2), (LONG, 0),
        ("Important Terms", 2), (LONG, 0),
        ("Formulas to Know", 2), (LONG, 0),
    ], source="Study_Guide_Solar_Cells.docx")
    assert [n.topic for n in notes] == [
        "solar_cells_key_concepts",
        "solar_cells_important_terms",
        "solar_cells_formulas_know",
    ]


def test_a_lone_top_heading_does_not_swallow_the_document():
    """A Word file whose only Heading 1 is its own title would otherwise import
    as one undifferentiated wall."""
    _doc, notes = proposal([
        ("Charge Controllers", 1),
        ("PWM", 2), (LONG, 0),
        ("MPPT", 2), (LONG, 0),
    ])
    assert len(notes) == 2, "split should have descended past the single Heading 1"


def test_the_domain_is_not_repeated_inside_its_own_topics():
    _doc, notes = proposal([
        ("Solar Energy", 1), (LONG, 0),
        ("Solar Energy Basics", 1), (LONG, 0),
    ], source="Solar_Energy.docx")
    for note in notes:
        assert not note.topic.startswith("solar_energy_solar_energy"), note.topic


def test_tiny_sections_merge_instead_of_becoming_empty_topics():
    """A PDF's inferred headings include every table header and figure caption.
    Each as its own topic would be a knowledge web full of lies."""
    _doc, notes = proposal([
        ("Real Section", 1), (LONG, 0),
        ("Table 1", 1), ("Col A Col B", 0),
        ("Table 2", 1), ("Col C Col D", 0),
    ])
    assert len(notes) == 1
    assert "Table 1" in notes[0].body and "Table 2" in notes[0].body


def test_a_document_with_no_headings_becomes_one_note_named_for_itself():
    _doc, notes = proposal([(LONG, 0)], source="Charge_Controllers.docx",
                           title="Charge Controllers")
    assert [n.topic for n in notes] == ["charge_controllers"]


def test_duplicate_ids_are_numbered_and_flagged():
    _doc, notes = proposal([
        ("Overview", 1), (LONG, 0),
        ("Overview", 1), (LONG, 0),
    ], source="Diodes.docx")
    assert notes[0].topic == "diodes_overview"
    assert notes[1].topic == "diodes_overview_2"
    assert notes[1].warnings


def test_every_proposed_id_is_a_valid_topic():
    from protege.vault import coerce_topic

    _doc, notes = proposal([
        ("Step 1 - Feature Engineering", 1), (LONG, 0),
        ("Deliverables & Grading (100 Marks)", 1), (LONG, 0),
        ("What You Will Build", 1), (LONG, 0),
    ], source="Project 1 - Intro to AI&Agents.docx")
    for note in notes:
        assert coerce_topic(note.topic) == note.topic, note.topic


# --- writing -----------------------------------------------------------------


def test_written_notes_are_tagged_and_locked_not_unlocked(tmp_path):
    """Import stocks the shelves. It does not read the books.

    If this ever fails, importing a document has become a way to give the model
    knowledge without teaching it -- which is the one thing the application
    exists to prevent.
    """
    document = Document("Solar", (Block("Solar", 1),), "solar.docx", "docx")
    notes = [ProposedNote("Key Concepts", "solar_key_concepts", LONG)]
    written = write_notes(tmp_path, notes, document, "2026-01-01T00:00:00Z")

    assert len(written) == 1
    frontmatter, body, _ = parse_frontmatter(written[0].read_text(encoding="utf-8"))
    topics, _ = extract_topics(frontmatter)
    assert topics == ("solar_key_concepts",)
    assert "Key Concepts" in body

    from protege.schemas import Manifest

    assert not Manifest.initial().is_unlocked("solar_key_concepts")


def test_deselected_sections_are_not_written(tmp_path):
    document = Document("Solar", (Block("Solar", 1),), "solar.docx", "docx")
    notes = [
        ProposedNote("Keep", "solar_keep", LONG),
        ProposedNote("Drop", "solar_drop", LONG, include=False),
    ]
    written = write_notes(tmp_path, notes, document, "2026-01-01T00:00:00Z")
    assert [p.stem for p in written] == ["solar_keep"]


def test_the_source_is_recorded_in_frontmatter(tmp_path):
    """Six months on, "where did this come from" is the first question."""
    document = Document("Solar", (Block("Solar", 1),), "lecture4a.pdf", "pdf")
    written = write_notes(tmp_path, [ProposedNote("Fill Factor", "solar_fill", LONG)],
                          document, "2026-01-01T00:00:00Z")
    text = written[0].read_text(encoding="utf-8")
    assert "lecture4a.pdf" in text and "Fill Factor" in text


def test_an_unusable_topic_id_refuses_rather_than_writing_something_else(tmp_path):
    document = Document("Solar", (Block("Solar", 1),), "solar.docx", "docx")
    with pytest.raises(DocumentError, match="topic id"):
        write_notes(tmp_path, [ProposedNote("X", "!!!", LONG)], document, "t")


def test_two_notes_never_overwrite_each_other(tmp_path):
    document = Document("Solar", (Block("Solar", 1),), "solar.docx", "docx")
    written = write_notes(
        tmp_path,
        [ProposedNote("A", "solar_x", LONG), ProposedNote("B", "solar_x", LONG)],
        document, "t",
    )
    assert len(set(written)) == 2
