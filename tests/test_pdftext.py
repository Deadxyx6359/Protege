"""Reading text out of a PDF with no library to do it.

The parser is built from small PDFs written by hand in these tests, because a
PDF is a container format and the interesting cases are all structural: is the
stream compressed, are the objects packed into an object stream, does the font
carry a ToUnicode map, is the text placed word by word or glyph by glyph.

Every failure this module has had was silent -- it returned *something*, just
not text. So the assertions check for the actual words rather than for a
non-empty result.
"""

from __future__ import annotations

import zlib

import pytest

from protege.pdftext import PdfError, extract_lines


def obj(number: int, body: bytes) -> bytes:
    return b"%d 0 obj\n" % number + body + b"\nendobj\n"


def stream_obj(number: int, header: bytes, payload: bytes, *, deflate: bool = False) -> bytes:
    if deflate:
        payload = zlib.compress(payload)
        header = header.replace(b">>", b"/Filter /FlateDecode>>")
    header = header.replace(b">>", b"/Length %d>>" % len(payload))
    return obj(number, header + b"\nstream\n" + payload + b"\nendstream")


def build(content: bytes, *, deflate: bool = False, extra: bytes = b"",
          font_ref: bytes = b"") -> bytes:
    """A one-page PDF whose content stream is `content`."""
    resources = b"<</Font <</F1 4 0 R>>>>" if font_ref else b"<<>>"
    return (
        b"%PDF-1.4\n"
        + obj(1, b"<</Type /Catalog /Pages 2 0 R>>")
        + obj(2, b"<</Type /Pages /Kids [3 0 R] /Count 1>>")
        + obj(3, b"<</Type /Page /Parent 2 0 R /Contents 5 0 R /Resources "
              + resources + b">>")
        + font_ref
        + stream_obj(5, b"<<>>", content, deflate=deflate)
        + extra
        + b"trailer\n<</Root 1 0 R>>\n%%EOF\n"
    )


def text_of(raw: bytes) -> str:
    return "\n".join(line.text for line in extract_lines(raw))


SIMPLE = b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (Hello world) Tj ET"


# --- the basics --------------------------------------------------------------


def test_plain_uncompressed_text():
    assert "Hello world" in text_of(build(SIMPLE))


def test_flate_compressed_text():
    """Every real PDF compresses its content streams."""
    assert "Hello world" in text_of(build(SIMPLE, deflate=True))


def test_a_missing_pdf_header_is_refused():
    with pytest.raises(PdfError, match="PDF header"):
        extract_lines(b"just some bytes")


def test_an_encrypted_pdf_says_what_to_do():
    raw = build(SIMPLE).replace(b"trailer\n<</Root 1 0 R>>",
                                b"trailer\n<</Root 1 0 R /Encrypt 9 0 R>>")
    with pytest.raises(PdfError, match="encrypted"):
        extract_lines(raw)


def test_a_pdf_with_no_text_is_named_as_a_scan():
    """The single most likely reason an import comes back empty."""
    with pytest.raises(PdfError, match="scanned"):
        extract_lines(build(b"BT /F1 12 Tf ET"))


# --- the bugs that shipped ---------------------------------------------------


def test_a_name_valued_key_is_read_to_its_end():
    """`/Filter /FlateDecode` -- the value starts with a slash.

    Scanning for "the next `/`" to find where a value ends terminated at offset
    zero, so no filter was ever detected, nothing decompressed, and compressed
    bytes were parsed as page content. It produced garbage rather than an
    error, which is how it survived a first pass.
    """
    from protege.pdftext import _lookup

    assert _lookup(b"<</Filter /FlateDecode/Length 40>>", "Filter") == b"/FlateDecode"
    assert _lookup(b"<</Length 40/Filter /FlateDecode>>", "Length") == b"40"


def test_binary_stream_data_containing_endobj_does_not_truncate_the_object():
    """Compressed data is arbitrary bytes and turns up `endobj` often enough."""
    payload = b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (endobj marker here) Tj ET"
    assert "endobj marker here" in text_of(build(payload))


def test_a_word_style_bt_et_per_run_stays_on_one_line():
    """Word wraps *every* run in its own BT/ET block.

    Treating that as a line break gave one word per line, which made the
    type-size heading detection downstream meaningless.
    """
    content = (
        b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (Course) Tj ET\n"
        b"BT /F1 12 Tf 1 0 0 1 120 700 Tm ( Syllabus) Tj ET\n"
        b"BT /F1 12 Tf 1 0 0 1 72 680 Tm (Second line) Tj ET\n"
    )
    lines = [line.text for line in extract_lines(build(content))]
    assert lines == ["Course Syllabus", "Second line"]


def test_a_vertical_move_is_a_line_break_and_a_horizontal_one_is_not():
    content = (
        b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (left) Tj 40 0 Td (right) Tj "
        b"0 -20 Td (below) Tj ET"
    )
    lines = [line.text for line in extract_lines(build(content))]
    assert lines[-1] == "below"
    assert any("left" in line and "right" in line for line in lines)


# --- spacing -----------------------------------------------------------------


def test_kerning_inside_a_tj_array_becomes_a_space():
    """A PDF has no spaces; a large negative kern is where one belongs."""
    content = b"BT /F1 12 Tf 1 0 0 1 72 700 Tm [(Hello)-400(world)] TJ ET"
    assert "Hello world" in text_of(build(content))


def test_small_kerning_does_not_become_a_space():
    content = b"BT /F1 12 Tf 1 0 0 1 72 700 Tm [(Hel)-20(lo)] TJ ET"
    assert "Hello" in text_of(build(content))


def test_glyph_by_glyph_placement_recovers_word_gaps():
    """Some producers place every character. The step sizes give the words away:
    within a word it is one advance, at a boundary it is that plus a space."""
    positions = [(72, "F"), (79, "P"), (86, "G"), (93, "A"), (112, "b"), (119, "i"),
                 (126, "t")]
    content = b"BT /F1 12 Tf "
    for x, char in positions:
        content += b"1 0 0 1 %d 700 Tm (%s) Tj " % (x, char.encode())
    content += b"ET"
    assert text_of(build(content)) == "FPGA bit"


# --- fonts -------------------------------------------------------------------


def test_a_tounicode_cmap_is_applied():
    """A subset font maps bytes to its own glyph order -- 0x01 might be "H"."""
    cmap = (
        b"/CIDInit /ProcSet findresource begin\n"
        b"1 begincmap\n"
        b"2 beginbfchar\n<01> <0048>\n<02> <0069>\nendbfchar\n"
        b"endcmap\n"
    )
    font = obj(4, b"<</Type /Font /Subtype /TrueType /ToUnicode 6 0 R>>")
    content = b"BT /F1 12 Tf 1 0 0 1 72 700 Tm <0102> Tj ET"
    raw = build(content, font_ref=font, extra=stream_obj(6, b"<<>>", cmap))
    assert "Hi" in text_of(raw)


def test_a_bfrange_walks_its_destination_forward():
    cmap = (
        b"1 beginbfrange\n<01> <03> <0061>\nendbfrange\n"
    )
    font = obj(4, b"<</Type /Font /Subtype /TrueType /ToUnicode 6 0 R>>")
    content = b"BT /F1 12 Tf 1 0 0 1 72 700 Tm <010203> Tj ET"
    raw = build(content, font_ref=font, extra=stream_obj(6, b"<<>>", cmap))
    assert "abc" in text_of(raw)


def test_text_without_a_cmap_decodes_as_cp1252():
    assert "café" in text_of(
        build(b"BT /F1 12 Tf 1 0 0 1 72 700 Tm (caf\xe9) Tj ET")
    )


# --- object streams ----------------------------------------------------------


def test_objects_packed_into_an_object_stream_are_found():
    """How every PDF from Word 2016 or Chrome stores its page objects.

    Skipping these finds no pages at all in a large share of real documents --
    and "no pages" was reported to the user as a damaged file.
    """
    page = b"<</Type /Page /Parent 2 0 R /Contents 5 0 R /Resources <<>>>>"
    packed = b"3 0 " + page
    container = stream_obj(
        7, b"<</Type /ObjStm /N 1 /First 4>>", packed, deflate=True
    )
    raw = (
        b"%PDF-1.5\n"
        + obj(1, b"<</Type /Catalog /Pages 2 0 R>>")
        + obj(2, b"<</Type /Pages /Kids [3 0 R] /Count 1>>")
        + stream_obj(5, b"<<>>", SIMPLE)
        + container
        + b"trailer\n<</Root 1 0 R>>\n%%EOF\n"
    )
    assert "Hello world" in text_of(raw)


# --- escaping ----------------------------------------------------------------


def test_escaped_parentheses_and_octal_in_a_literal_string():
    content = (
        rb"BT /F1 12 Tf 1 0 0 1 72 700 Tm (a \(b\) c \101 d) Tj ET"
    )
    assert "a (b) c A d" in text_of(build(content))


def test_a_damaged_stream_does_not_crash_the_whole_document():
    """One unreadable page must not lose the other twenty."""
    good = stream_obj(5, b"<<>>", SIMPLE)
    broken = obj(9, b"<</Filter /FlateDecode/Length 8>>\nstream\nnot-zlib\nendstream")
    raw = (
        b"%PDF-1.4\n"
        + obj(1, b"<</Type /Catalog /Pages 2 0 R>>")
        + obj(2, b"<</Type /Pages /Kids [3 0 R] /Count 1>>")
        + obj(3, b"<</Type /Page /Parent 2 0 R /Contents 5 0 R /Resources <<>>>>")
        + good + broken
        + b"trailer\n<</Root 1 0 R>>\n%%EOF\n"
    )
    assert "Hello world" in text_of(raw)
