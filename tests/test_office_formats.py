"""Word, Excel and PowerPoint read and edited in place — and PDF read (B1).

Most of these assert exact bytes. An edited part must equal the original with
only the changed text different, and every other part must be identical. That
is the whole promise of the surgical edit; a looser test would let a round-trip
through an XML parser — which silently corrupts Office files — slip back in.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

import pytest

from akira.core.documents import ooxml, pdf, sheets, slides, word
from akira.core.documents.ooxml import Package, PackageError

DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"


def package_bytes(parts: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return out.getvalue()


def parts_of(raw: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def rels(*items) -> str:
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{g}"/>' for i, t, g in items)
    return DECL + f'<Relationships xmlns="{PKG}">{body}</Relationships>'


def types(*overrides) -> str:
    body = "".join(f'<Override PartName="{p}" ContentType="{c}"/>' for p, c in overrides)
    return (DECL + f'<Types xmlns="{CT}"><Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            f'<Default Extension="xml" ContentType="application/xml"/>{body}</Types>')


# == Word ================================================================================

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

DOCUMENT = (
    DECL + '<w:document xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    f'xmlns:w="{W}" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
    'mc:Ignorable="w14"><w:body>'
    '<w:p w:rsidR="00A1"><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
    '<w:r><w:t>Quarterly report</w:t></w:r></w:p>'
    '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">Revenue grew </w:t></w:r>'
    '<w:r><w:t>by 1</w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>2 percent.</w:t></w:r></w:p>'
    '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
    '<w:r><w:t>Hire two engineers</w:t></w:r></w:p>'
    '<w:p><w:pPr><w:pStyle w:val="Berschrift2"/></w:pPr><w:r><w:t>Risks</w:t></w:r></w:p>'
    '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="100"/><w:gridCol w:w="100"/></w:tblGrid>'
    '<w:tr><w:tc><w:p><w:r><w:t>Region</w:t></w:r></w:p></w:tc>'
    '<w:tc><w:p><w:r><w:t>Lead</w:t></w:r></w:p></w:tc></w:tr>'
    '<w:tr><w:tc><w:p><w:r><w:t>North</w:t></w:r></w:p></w:tc>'
    '<w:tc><w:p><w:r><w:t>R&amp;D &lt;team&gt;</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    '<w:p><w:r><w:instrText>PAGE 12 percent</w:instrText></w:r>'
    '<w:r><w:delText>12 percent</w:delText></w:r></w:p>'
    '<w:sectPr/></w:body></w:document>')

WORD_STYLES = (
    DECL + f'<w:styles xmlns:w="{W}">'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
    '<w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
    # A German Word's id for Heading 2. The name is the reliable part.
    '<w:style w:type="paragraph" w:styleId="Berschrift2"><w:name w:val="heading 2"/></w:style>'
    '</w:styles>')

HEADER = DECL + f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>Confidential draft</w:t></w:r></w:p></w:hdr>'

WORD_PARTS = {
    "[Content_Types].xml": types(
        ("/word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
        ("/word/styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
        ("/word/header1.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml")),
    "_rels/.rels": rels(("rId1", REL + "/officeDocument", "word/document.xml")),
    "word/_rels/document.xml.rels": rels(("rId1", REL + "/styles", "styles.xml"),
                                         ("rId2", REL + "/header", "header1.xml")),
    "word/document.xml": DOCUMENT,
    "word/styles.xml": WORD_STYLES,
    "word/header1.xml": HEADER,
}


def docx() -> Package:
    return Package(package_bytes(WORD_PARTS), "report.docx")


def test_word_structure_is_read():
    blocks = word.read(docx())
    assert [(b.kind, b.text, b.level) for b in blocks if b.kind != "table"] == [
        ("heading", "Quarterly report", 1),
        ("paragraph", "Revenue grew by 12 percent.", 0),
        ("bullet", "Hire two engineers", 0),
        ("heading", "Risks", 2),
    ]
    table = next(b for b in blocks if b.kind == "table")
    assert table.rows == (("Region", "Lead"), ("North", "R&D <team>"))


def test_word_renders_as_markdown():
    text = word.render(word.read(docx()))
    assert "# Quarterly report" in text and "## Risks" in text
    assert "- Hire two engineers" in text and "| North | R&D <team> |" in text


def test_a_replacement_across_runs_touches_only_those_runs():
    package = docx()
    new, count = word.replace(package, "12 percent", "15 percent")
    assert count == 1, "field codes and tracked deletions are not visible text"

    before, after = parts_of(package.raw), parts_of(new)
    expected = (DOCUMENT.replace("<w:t>by 1</w:t>", "<w:t>by 15 percent</w:t>")
                        .replace("<w:t>2 percent.</w:t>", "<w:t>.</w:t>"))
    assert after["word/document.xml"].decode("utf-8") == expected
    for name, data in before.items():
        if name != "word/document.xml":
            assert after[name] == data, f"{name} changed"


def test_namespaces_only_named_in_ignorable_survive():
    """The ElementTree round-trip drops these, and Word calls the file damaged."""
    new, _ = word.replace(docx(), "Risks", "Threats")
    xml = parts_of(new)["word/document.xml"].decode("utf-8")
    assert 'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"' in xml
    assert 'mc:Ignorable="w14"' in xml and xml.startswith(DECL)


def test_the_text_reads_back_changed():
    new, _ = word.replace(docx(), "12 percent", "15 percent")
    assert word.read(Package(new))[1].text == "Revenue grew by 15 percent."


def test_whitespace_at_the_edge_of_a_run_is_kept():
    new, _ = word.replace(docx(), "Quarterly report", "Quarterly report ")
    xml = parts_of(new)["word/document.xml"].decode("utf-8")
    assert '<w:t xml:space="preserve">Quarterly report </w:t>' in xml


def test_headers_are_edited_too():
    new, count = word.replace(docx(), "Confidential draft", "Final")
    assert count == 1 and b"<w:t>Final</w:t>" in parts_of(new)["word/header1.xml"]


def test_replacement_text_is_escaped():
    new, _ = word.replace(docx(), "North", "North & <East>")
    assert "North &amp; &lt;East&gt;" in parts_of(new)["word/document.xml"].decode("utf-8")
    table = next(b for b in word.read(Package(new)) if b.kind == "table")
    assert table.rows[1][0] == "North & <East>"


def test_control_characters_never_reach_the_xml():
    new, _ = word.replace(docx(), "Risks", "Ri\x00sks\x07")
    ElementTree.fromstring(parts_of(new)["word/document.xml"])
    assert word.read(Package(new))[3].text == "Risks"


def test_nothing_found_changes_nothing():
    package = docx()
    new, count = word.replace(package, "no such words", "x")
    assert count == 0 and new == package.raw


def test_a_new_word_document_holds_what_it_was_given():
    outline = ("# Plan\n\nWe will ship in May.\nIt will be fine.\n\n- Build it\n- Test it\n\n"
               "| Who | When |\n|---|---|\n| Ana | May |\n")
    raw = word.create(word.parse_outline(outline), title="Plan")
    blocks = word.read(Package(raw))
    assert [(b.kind, b.text) for b in blocks if b.kind != "table"] == [
        ("heading", "Plan"),
        ("paragraph", "We will ship in May. It will be fine."),
        ("bullet", "Build it"),
        ("bullet", "Test it"),
    ]
    assert next(b for b in blocks if b.kind == "table").rows == (("Who", "When"), ("Ana", "May"))
    for part in ("word/document.xml", "word/styles.xml", "[Content_Types].xml", "_rels/.rels"):
        ElementTree.fromstring(parts_of(raw)[part])


# == packages that should not be opened ================================================


def test_an_old_binary_document_is_told_to_save_as_the_modern_format():
    with pytest.raises(PackageError, match="docx"):
        Package(b"\xd0\xcf\x11\xe0 an old .doc file", "old.doc")


def test_a_package_that_would_expand_enormously_is_refused(monkeypatch):
    monkeypatch.setattr(ooxml, "MAX_TOTAL_BYTES", 1000)
    with pytest.raises(PackageError, match="expand"):
        Package(package_bytes({"big.xml": "x" * 5000}))


def test_a_single_huge_part_is_refused(monkeypatch):
    monkeypatch.setattr(ooxml, "MAX_PART_BYTES", 100)
    with pytest.raises(PackageError, match="too large"):
        Package(package_bytes({"a.xml": "x" * 500})).read("a.xml")


# == Excel =============================================================================

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

WORKBOOK = (DECL + f'<workbook xmlns="{S}" xmlns:r="{REL}"><workbookPr/><sheets>'
            '<sheet name="Budget" sheetId="1" r:id="rId1"/><sheet name="Notes" sheetId="2" r:id="rId2"/>'
            '</sheets><calcPr calcId="191029"/></workbook>')
SHARED = (DECL + f'<sst xmlns="{S}" count="4" uniqueCount="4"><si><t>Item</t></si><si><t>Cost</t></si>'
          '<si><t>Date</t></si><si><r><t>Pa</t></r><r><rPr><b/></rPr><t>per</t></r></si></sst>')
SHEET_STYLES = (DECL + f'<styleSheet xmlns="{S}"><numFmts count="1">'
                '<numFmt numFmtId="164" formatCode="dd/mm/yyyy"/></numFmts>'
                '<cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/></cellXfs>'
                '</styleSheet>')
SHEET1 = (DECL + f'<worksheet xmlns="{S}"><dimension ref="A1:E3"/><sheetData>'
          '<row r="1" spans="1:3"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
          '<c r="C1" t="s"><v>2</v></c></row>'
          '<row r="2" spans="1:5"><c r="A2" t="s"><v>3</v></c><c r="B2"><v>12.5</v></c>'
          '<c r="C2" s="1"><v>45000</v></c><c r="D2" s="2"><v>45001</v></c>'
          '<c r="E2"><f t="shared" ref="E2:E3" si="0">B2*2</f><v>25</v></c></row>'
          '<row r="3" spans="1:5"><c r="A3" t="inlineStr"><is><t>Ink</t></is></c><c r="B3"><v>30</v></c>'
          '<c r="C3"><f>B2+B3</f><v>42.5</v></c><c r="D3" t="b"><v>1</v></c>'
          '<c r="E3"><f t="shared" si="0"/><v>60</v></c></row>'
          '</sheetData></worksheet>')
SHEET2 = DECL + f'<worksheet xmlns="{S}"><sheetData/></worksheet>'
CALC_CHAIN = DECL + f'<calcChain xmlns="{S}"><c r="C3" i="1"/><c r="E2" i="1"/><c r="E3" i="1"/></calcChain>'

SHEET_PARTS = {
    "[Content_Types].xml": types(
        ("/xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
        ("/xl/worksheets/sheet1.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
        ("/xl/worksheets/sheet2.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
        ("/xl/sharedStrings.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"),
        ("/xl/styles.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"),
        ("/xl/calcChain.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.calcChain+xml")),
    "_rels/.rels": rels(("rId1", REL + "/officeDocument", "xl/workbook.xml")),
    "xl/_rels/workbook.xml.rels": rels(
        ("rId1", REL + "/worksheet", "worksheets/sheet1.xml"),
        ("rId2", REL + "/worksheet", "worksheets/sheet2.xml"),
        ("rId3", REL + "/sharedStrings", "sharedStrings.xml"),
        ("rId4", REL + "/styles", "styles.xml"),
        ("rId5", REL + "/calcChain", "calcChain.xml")),
    "xl/workbook.xml": WORKBOOK,
    "xl/sharedStrings.xml": SHARED,
    "xl/styles.xml": SHEET_STYLES,
    "xl/worksheets/sheet1.xml": SHEET1,
    "xl/worksheets/sheet2.xml": SHEET2,
    "xl/calcChain.xml": CALC_CHAIN,
}


def xlsx() -> Package:
    return Package(package_bytes(SHEET_PARTS), "budget.xlsx")


def sheet_xml(raw: bytes, number: int = 1) -> str:
    return parts_of(raw)[f"xl/worksheets/sheet{number}.xml"].decode("utf-8")


def row_xml(xml: str, number: int) -> str:
    start = xml.index(f'<row r="{number}"')
    return xml[start:xml.index("</row>", start)]


def test_cells_are_read_as_a_person_sees_them():
    budget, notes = sheets.read(xlsx())
    assert (budget.name, notes.name) == ("Budget", "Notes")
    assert budget.rows[1] == ["Paper", "12.5", "2023-03-15", "2023-03-16", "25"]
    assert budget.rows[2] == ["Ink", "30", "42.5", "TRUE", "60"]
    assert budget.formulas == 3 and notes.total_rows == 0


def test_the_grid_is_labelled_so_a_cell_can_be_named():
    text = sheets.render(sheets.read(xlsx()))
    assert "|   | A | B | C | D | E |" in text
    assert "| 2 | Paper | 12.5 | 2023-03-15 |" in text
    assert "## Sheet: Notes" in text and "(empty)" in text


def test_changing_a_value_keeps_the_cells_style():
    new, changed = sheets.set_cells(xlsx(), "Budget", {"C2": 45002})
    assert changed == ["C2"]
    assert '<c r="C2" s="1"><v>45002</v></c>' in sheet_xml(new)
    assert sheets.read(Package(new))[0].rows[1][2] == "2023-03-17"


def test_a_new_cell_lands_in_column_order_and_drops_the_stale_span():
    new, _ = sheets.set_cells(xlsx(), "Budget", {"F2": "done", "D1": "Note"})
    xml = sheet_xml(new)
    second = row_xml(xml, 2)
    assert second.index('r="E2"') < second.index('r="F2"')
    assert "spans=" not in second[:second.index(">")]
    first = row_xml(xml, 1)
    assert first.index('r="C1"') < first.index('r="D1"')


def test_a_new_row_lands_in_row_order():
    new, _ = sheets.set_cells(xlsx(), "Budget", {"A5": 1, "A4": "four"})
    xml = sheet_xml(new)
    assert xml.index('<row r="3"') < xml.index('<row r="4"') < xml.index('<row r="5"')


def test_an_empty_sheet_can_be_filled_and_names_are_matched_loosely():
    new, _ = sheets.set_cells(xlsx(), "notes", {"A1": "hello & <you>"})
    assert sheets.read(Package(new))[1].rows[0][0] == "hello & <you>"


def test_a_formula_is_written_and_excel_recalculates_on_open():
    new, _ = sheets.set_cells(xlsx(), "Budget", {"B4": "=SUM(B2:B3)"})
    assert "<f>SUM(B2:B3)</f>" in sheet_xml(new)
    assert 'fullCalcOnLoad="1"' in parts_of(new)["xl/workbook.xml"].decode("utf-8")


def test_overwriting_a_formula_removes_the_calculation_chain():
    """A chain naming a formula that is gone is what Excel calls damage."""
    new, _ = sheets.set_cells(xlsx(), "Budget", {"C3": 7})
    after = parts_of(new)
    assert "xl/calcChain.xml" not in after
    assert "calcChain" not in after["xl/_rels/workbook.xml.rels"].decode("utf-8")
    assert "calcChain" not in after["[Content_Types].xml"].decode("utf-8")


def test_a_plain_value_change_keeps_the_calculation_chain():
    new, _ = sheets.set_cells(xlsx(), "Budget", {"B2": 13})
    assert "xl/calcChain.xml" in parts_of(new)


def test_the_anchor_of_a_shared_formula_is_refused():
    with pytest.raises(PackageError, match="whole range"):
        sheets.set_cells(xlsx(), "Budget", {"E2": 1})


def test_clearing_a_cell_keeps_its_style():
    new, _ = sheets.set_cells(xlsx(), "Budget", {"C2": None})
    assert '<c r="C2" s="1"/>' in sheet_xml(new)


@pytest.mark.parametrize("ref", ["A0", "ZZZZ1", "B", "1A", "XFE1"])
def test_a_bad_cell_reference_is_refused(ref):
    with pytest.raises(PackageError):
        sheets.set_cells(xlsx(), "Budget", {ref: 1})


def test_an_unknown_sheet_names_the_real_ones():
    with pytest.raises(PackageError, match="Budget, Notes"):
        sheets.set_cells(xlsx(), "Summary", {"A1": 1})


def test_parts_that_were_not_edited_are_untouched():
    package = xlsx()
    new, _ = sheets.set_cells(package, "Budget", {"B2": 13})
    before, after = parts_of(package.raw), parts_of(new)
    for name, data in before.items():
        if name not in ("xl/worksheets/sheet1.xml", "xl/workbook.xml"):
            assert after[name] == data, f"{name} changed"


def test_a_new_workbook_holds_what_it_was_given():
    content = ("## Sheet: Budget\n| Item | Cost |\n|---|---|\n| Paper | 12.5 |\n| Ink | 30 |\n\n"
               '## Notes\nwho,when\n"Ana, Jr.",May\n')
    raw = sheets.create(sheets.parse_sheets(content), title="Budget")
    budget, notes = sheets.read(Package(raw))
    assert budget.name == "Budget"
    assert budget.rows == [["Item", "Cost"], ["Paper", "12.5"], ["Ink", "30"]]
    assert notes.rows[1] == ["Ana, Jr.", "May"]
    assert 's="1"' in row_xml(sheet_xml(raw), 1), "the header row is not bold"


def test_leading_zeros_stay_text():
    [(_, rows)] = sheets.parse_sheets("id,count\n007,3\n")
    assert rows[1] == ["007", 3]


# == PowerPoint ========================================================================

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
ROOT = f'xmlns:a="{A}" xmlns:r="{REL}" xmlns:p="{P}"'


def _shape(ph: str, body: str) -> str:
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="s"/><p:cNvSpPr/><p:nvPr>{ph}</p:nvPr>'
            f'</p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/>{body}</p:txBody></p:sp>')


SLIDE1 = (DECL + f'<p:sld {ROOT}><p:cSld><p:spTree>'
          + _shape('<p:ph type="title"/>', '<a:p><a:r><a:t>Road</a:t></a:r><a:r><a:rPr b="1"/><a:t>map</a:t></a:r></a:p>')
          + _shape('<p:ph idx="1"/>', '<a:p><a:r><a:t>Ship the beta</a:t></a:r></a:p>'
                   '<a:p><a:pPr lvl="1"/><a:r><a:t>Fix the install</a:t></a:r><a:r><a:t>er first</a:t></a:r></a:p>')
          + "</p:spTree></p:cSld></p:sld>")
SLIDE2 = (DECL + f'<p:sld {ROOT}><p:cSld><p:spTree>'
          + _shape('<p:ph type="title"/>', '<a:p><a:r><a:t>Next steps</a:t></a:r></a:p>')
          + '<p:graphicFrame><a:graphic><a:graphicData><a:tbl>'
          '<a:tr><a:tc><a:txBody><a:bodyPr/><a:p><a:r><a:t>Owner</a:t></a:r></a:p></a:txBody></a:tc>'
          '<a:tc><a:txBody><a:bodyPr/><a:p><a:r><a:t>Due</a:t></a:r></a:p></a:txBody></a:tc></a:tr>'
          "</a:tbl></a:graphicData></a:graphic></p:graphicFrame></p:spTree></p:cSld></p:sld>")
NOTES1 = (DECL + f'<p:notes {ROOT}><p:cSld><p:spTree>'
          + _shape('<p:ph type="sldImg"/>', "")
          + _shape('<p:ph type="body" idx="1"/>', '<a:p><a:r><a:t>Speak slowly about the beta</a:t></a:r></a:p>')
          + "</p:spTree></p:cSld></p:notes>")
PRESENTATION = (DECL + f'<p:presentation {ROOT}><p:sldIdLst><p:sldId id="256" r:id="rId3"/>'
                '<p:sldId id="257" r:id="rId2"/></p:sldIdLst></p:presentation>')

DECK_PARTS = {
    "[Content_Types].xml": types(("/ppt/presentation.xml",
                                  "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml")),
    "_rels/.rels": rels(("rId1", REL + "/officeDocument", "ppt/presentation.xml")),
    # Listed out of ZIP order on purpose: the deck's order is sldIdLst's.
    "ppt/_rels/presentation.xml.rels": rels(("rId2", REL + "/slide", "slides/slide2.xml"),
                                            ("rId3", REL + "/slide", "slides/slide1.xml")),
    "ppt/presentation.xml": PRESENTATION,
    "ppt/slides/slide1.xml": SLIDE1,
    "ppt/slides/_rels/slide1.xml.rels": rels(("rId1", REL + "/notesSlide", "../notesSlides/notesSlide1.xml")),
    "ppt/slides/slide2.xml": SLIDE2,
    "ppt/notesSlides/notesSlide1.xml": NOTES1,
}


def pptx() -> Package:
    return Package(package_bytes(DECK_PARTS), "roadmap.pptx")


def test_slides_are_read_in_the_decks_order_with_titles_levels_and_notes():
    first, second = slides.read(pptx())
    assert first.title == "Roadmap"
    assert first.lines == ((0, "Ship the beta"), (1, "Fix the installer first"))
    assert first.notes == "Speak slowly about the beta"
    assert second.title == "Next steps" and (0, "Owner | Due") in second.lines


def test_a_deck_renders_slide_by_slide():
    text = slides.render(slides.read(pptx()))
    assert "## Slide 1 — Roadmap" in text and "  - Fix the installer first" in text
    assert "Notes: Speak slowly about the beta" in text


def test_a_slide_edit_across_runs_touches_only_those_runs():
    package = pptx()
    new, count = slides.replace(package, "installer", "setup")
    assert count == 1
    expected = (SLIDE1.replace("<a:t>Fix the install</a:t>", "<a:t>Fix the setup</a:t>")
                      .replace("<a:t>er first</a:t>", "<a:t> first</a:t>"))
    after = parts_of(new)
    assert after["ppt/slides/slide1.xml"].decode("utf-8") == expected
    for name, data in parts_of(package.raw).items():
        if name != "ppt/slides/slide1.xml":
            assert after[name] == data, f"{name} changed"


def test_speaker_notes_are_edited_with_the_slides():
    new, count = slides.replace(pptx(), "beta", "release")
    assert count == 2
    assert slides.read(Package(new))[0].notes == "Speak slowly about the release"


# == PDF ===============================================================================


def tiny_pdf() -> bytes:
    content = (b"BT /F1 24 Tf 72 700 Td (Big Heading) Tj ET\n"
               b"BT /F1 12 Tf 72 660 Td (Body line one.) Tj ET\n"
               b"BT /F1 12 Tf 72 640 Td (Body line two.) Tj ET\n")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
    ]
    out = b"%PDF-1.4\n"
    for number, body in enumerate(objects, 1):
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    return out + b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"


def test_pdf_headings_come_from_type_size():
    blocks = pdf.read(tiny_pdf())
    assert blocks[0].kind == "heading" and blocks[0].text == "Big Heading"
    assert "Body line one." in word.render(blocks)


def test_something_that_is_not_a_pdf_says_so():
    with pytest.raises(PackageError, match="PDF"):
        pdf.read(b"plain text pretending")
