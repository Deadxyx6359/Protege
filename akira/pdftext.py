"""Text extraction from PDF, using nothing but the standard library.

Akira never downloads anything, so pdfminer and PyMuPDF are not options. That
leaves reading the format directly, which is less alarming than it sounds for
the job at hand: we do not need to lay out glyphs or reproduce a page, only to
recover the words in reading order and work out which ones were headings.

The route through a PDF is:

    file bytes -> indirect objects -> page objects -> content streams
               -> text operators -> character codes -> Unicode

Each step has a wrinkle worth knowing about.

**Objects** may sit directly in the file (`12 0 obj ... endobj`) or be packed
inside a compressed *object stream*, which is how every PDF written by Word
2016 or Chrome's print-to-PDF stores them. Skipping object streams means
finding no pages at all in a large fraction of real documents, so they are
expanded.

**Character codes are not text.** A subset-embedded font maps bytes to glyph
indices in its own private order, so the byte 0x03 might be "e". The document
carries a `/ToUnicode` CMap per font to undo this. Where one exists it is
authoritative; where none does, the bytes are conventional single-byte
encodings and cp1252 is the right guess.

**There are no spaces or line breaks.** A PDF positions text; it does not
separate words. Both have to be inferred -- from the kerning numbers inside a
`TJ` array, and from the text-positioning operators between one run and the
next.

**Headings are inferred from type size,** which is the one strong signal the
format does give us. The most common size on the page is the body; anything
meaningfully larger is a heading, ranked by size. Bold-only headings and
all-caps headings set at body size are missed.

What this cannot do, and says so rather than returning nonsense: scanned
documents (there is no text to find, only an image of text), encrypted
documents, and the LZW filter, which no current producer emits.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass


class PdfError(ValueError):
    """The PDF cannot be read as text, with a reason the user can act on."""


@dataclass(frozen=True)
class TextLine:
    """One run of text and the type size it was set at."""

    text: str
    size: float


# --- object layer ------------------------------------------------------------

_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
_NAME_VALUE = r"/%s\s*"


def _find_objects(raw: bytes) -> dict[int, bytes]:
    """Map object number -> raw body, for objects written directly in the file.

    Each body runs to the start of the next `N 0 obj`, not to the next
    `endobj`. Compressed stream data is arbitrary binary and turns up the bytes
    `endobj` often enough to matter -- bounding on that truncated the stream and
    left it undecompressable, which read as "this PDF has no text in it".
    """
    objects: dict[int, bytes] = {}
    matches = list(_OBJ_RE.finditer(raw))
    for index, match in enumerate(matches):
        number = int(match.group(1))
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        body = raw[match.end():stop]
        tail = body.rfind(b"endobj")
        # Later definitions win: an incrementally updated PDF appends the new
        # version of an object after the old one.
        objects[number] = body[:tail] if tail != -1 else body
    return objects


def _dict_of(body: bytes) -> bytes:
    """The `<< ... >>` dictionary at the head of an object body."""
    start = body.find(b"<<")
    if start == -1:
        return b""
    depth = 0
    index = start
    while index < len(body) - 1:
        pair = body[index:index + 2]
        if pair == b"<<":
            depth += 1
            index += 2
            continue
        if pair == b">>":
            depth -= 1
            index += 2
            if depth == 0:
                return body[start:index]
            continue
        index += 1
    return body[start:]


def _lookup(dictionary: bytes, key: str) -> bytes | None:
    """The raw value for `/key`.

    The value's own type decides where it ends. Scanning for "the next `/`"
    works for numbers and references and is catastrophically wrong for a name
    value: `/Filter /FlateDecode` starts with a slash, so the scan terminated
    at offset zero and every filter came back empty. Nothing decompressed, and
    the extractor read compressed bytes as if they were page content.
    """
    match = re.search((_NAME_VALUE % re.escape(key)).encode("ascii"), dictionary)
    if match is None:
        return None
    rest = dictionary[match.end():]
    if rest[:2] == b"<<":
        return _dict_of(rest)
    if rest[:1] == b"[":
        depth = 0
        for index, char in enumerate(rest):
            if char == 0x5B:
                depth += 1
            elif char == 0x5D:
                depth -= 1
                if depth == 0:
                    return rest[:index + 1]
        return rest
    if rest[:1] == b"/":
        name = re.match(rb"/[^\s/\[\]<>(){}]*", rest)
        return name.group() if name else b""
    stop = re.search(rb"(?=/)|(?=>>)|[\r\n]", rest)
    return (rest[:stop.start()] if stop else rest).strip()


def _refs(value: bytes | None) -> list[int]:
    """Every `N 0 R` indirect reference in a value."""
    if not value:
        return []
    return [int(n) for n in re.findall(rb"(\d+)\s+\d+\s+R\b", value)]


def _int(value: bytes | None, default: int = 0) -> int:
    if not value:
        return default
    match = re.search(rb"-?\d+", value)
    return int(match.group()) if match else default


def _decode_stream(body: bytes) -> bytes | None:
    """The decoded stream payload of an object, or None if it has no stream."""
    marker = body.find(b"stream")
    if marker == -1:
        return None
    start = marker + len(b"stream")
    if body[start:start + 2] == b"\r\n":
        start += 2
    elif body[start:start + 1] in (b"\n", b"\r"):
        start += 1
    end = body.rfind(b"endstream")
    if end == -1 or end < start:
        return None
    data = body[start:end]

    header = _dict_of(body)
    filters = _lookup(header, "Filter") or b""
    if b"LZWDecode" in filters:
        raise PdfError(
            "this PDF uses the LZW filter, which Akira cannot decompress. "
            "Re-saving it from any current PDF viewer will convert it."
        )
    if b"FlateDecode" in filters:
        for wbits in (15, -15):
            try:
                return zlib.decompress(data, wbits)
            except zlib.error:
                continue
        # A truncated stream still usually yields most of its text.
        try:
            return zlib.decompressobj().decompress(data)
        except zlib.error:
            return None
    if b"ASCIIHexDecode" in filters:
        hex_text = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
        if len(hex_text) % 2:
            hex_text += b"0"
        return bytes.fromhex(hex_text.decode("ascii"))
    return data


def _expand_object_streams(raw: bytes, objects: dict[int, bytes]) -> dict[int, bytes]:
    """Pull objects out of `/Type /ObjStm` containers.

    Without this, a PDF from any recent version of Word or Chrome looks like it
    has no pages: everything but the stream containers themselves lives inside
    them.
    """
    expanded = dict(objects)
    for body in list(objects.values()):
        header = _dict_of(body)
        if b"/ObjStm" not in header:
            continue
        payload = _decode_stream(body)
        if payload is None:
            continue
        count = _int(_lookup(header, "N"))
        first = _int(_lookup(header, "First"))
        pairs = payload[:first].split()
        for index in range(count):
            try:
                number = int(pairs[index * 2])
                offset = int(pairs[index * 2 + 1])
            except (IndexError, ValueError):
                break
            end = None
            if index + 1 < count:
                try:
                    end = first + int(pairs[index * 2 + 3])
                except (IndexError, ValueError):
                    end = None
            chunk = payload[first + offset:end] if end else payload[first + offset:]
            # Direct definitions take precedence -- an incremental update that
            # replaces an object writes it into the file body, not the stream.
            expanded.setdefault(number, chunk)
    return expanded


# --- ToUnicode CMaps ---------------------------------------------------------

_BFCHAR = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_HEX = re.compile(rb"<([0-9A-Fa-f]+)>")


def _utf16_of(hex_bytes: bytes) -> str:
    raw = bytes.fromhex(hex_bytes.decode("ascii"))
    if len(raw) % 2:
        raw += b"\x00"
    try:
        return raw.decode("utf-16-be", "ignore")
    except UnicodeDecodeError:
        return ""


def _parse_cmap(payload: bytes) -> dict[int, str]:
    """code -> replacement text, from a /ToUnicode CMap stream."""
    mapping: dict[int, str] = {}
    width = 1

    for block in _BFCHAR.findall(payload):
        items = _HEX.findall(block)
        for index in range(0, len(items) - 1, 2):
            src, dst = items[index], items[index + 1]
            width = max(width, len(src) // 2)
            mapping[int(src, 16)] = _utf16_of(dst)

    for block in _BFRANGE.findall(payload):
        # Two forms: `<lo> <hi> <dst>` walks the destination forward, and
        # `<lo> <hi> [<d1> <d2> ...]` lists each one.
        for entry in re.finditer(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)", block
        ):
            lo_hex, hi_hex, dst = entry.group(1), entry.group(2), entry.group(3)
            lo, hi = int(lo_hex, 16), int(hi_hex, 16)
            width = max(width, len(lo_hex) // 2)
            if hi - lo > 65535:
                continue
            if dst.startswith(b"["):
                for offset, item in enumerate(_HEX.findall(dst)):
                    mapping[lo + offset] = _utf16_of(item)
            else:
                base = _utf16_of(_HEX.match(dst).group(1))
                if not base:
                    continue
                for offset in range(hi - lo + 1):
                    mapping[lo + offset] = base[:-1] + chr(ord(base[-1]) + offset)

    if mapping:
        mapping["width"] = width  # type: ignore[index]
    return mapping


# --- content streams ---------------------------------------------------------

_TOKEN = re.compile(
    rb"""
      (?P<hex><[0-9A-Fa-f\s]*>)
    | (?P<name>/[^\s/\[\]<>(){}]+)
    | (?P<number>-?\d*\.?\d+)
    | (?P<array>\[)
    | (?P<array_end>\])
    | (?P<op>[A-Za-z'"*][A-Za-z0-9'"*]*)
    """,
    re.X,
)


def _literal_string(data: bytes, start: int) -> tuple[bytes, int]:
    """Read a `( ... )` string starting at `start` (the paren). Returns (raw, next)."""
    out = bytearray()
    depth = 0
    index = start
    while index < len(data):
        char = data[index]
        if char == 0x5C:  # backslash
            nxt = data[index + 1:index + 2]
            escapes = {b"n": 10, b"r": 13, b"t": 9, b"b": 8, b"f": 12,
                       b"(": 40, b")": 41, b"\\": 92}
            if nxt in escapes:
                out.append(escapes[nxt])
                index += 2
                continue
            octal = re.match(rb"[0-7]{1,3}", data[index + 1:index + 4])
            if octal:
                out.append(int(octal.group(), 8) & 0xFF)
                index += 1 + len(octal.group())
                continue
            index += 2
            continue
        if char == 0x28:  # (
            depth += 1
            if depth > 1:
                out.append(char)
            index += 1
            continue
        if char == 0x29:  # )
            depth -= 1
            if depth == 0:
                return bytes(out), index + 1
            out.append(char)
            index += 1
            continue
        out.append(char)
        index += 1
    return bytes(out), index


def _decode(raw: bytes, cmap: dict) -> str:
    if not cmap:
        return raw.decode("cp1252", "replace")
    width = cmap.get("width", 1)
    out = []
    if width >= 2:
        for index in range(0, len(raw) - 1, 2):
            code = (raw[index] << 8) | raw[index + 1]
            out.append(cmap.get(code, ""))
    else:
        for byte in raw:
            out.append(cmap.get(byte, ""))
    return "".join(out)


# A TJ kerning adjustment more negative than this is a word gap rather than
# ordinary letter spacing. PDF units are thousandths of an em.
WORD_GAP = -140


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if not ordered:
        return 0.0
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# A run of at most this many characters suggests the producer is placing text
# glyph by glyph rather than word by word.
GLYPH_RUN = 2
# How much wider than the typical advance a step has to be to mean a space.
GAP_RATIO = 1.55


def _join_runs(runs: list[tuple[float, str]]) -> str:
    """Assemble one line's positioned runs, restoring spaces if they are missing.

    A PDF has no space character in the usual sense; a gap is just the next
    glyph being placed further along. Well-behaved producers emit whole words
    and encode the gap as a large negative kern inside a `TJ` array, which is
    handled while scanning. Others place every glyph individually, and those
    arrive here as a queue of one-character runs with no spaces anywhere.

    For that case the step sizes give it away: within a word the step is one
    glyph's advance, and at a word boundary it is that plus a space. Rather
    than guess an em width -- which varies by font and by glyph -- take the
    median step on this very line as the yardstick and call anything half again
    as wide a space. Self-calibrating, and it costs one sort per line.
    """
    if not runs:
        return ""
    if max(len(text) for _x, text in runs) > GLYPH_RUN:
        return "".join(text for _x, text in runs)

    steps = [runs[i + 1][0] - runs[i][0] for i in range(len(runs) - 1)]
    positive = [s for s in steps if s > 0]
    if not positive:
        return "".join(text for _x, text in runs)
    threshold = _median(positive) * GAP_RATIO

    out = [runs[0][1]]
    for index, step in enumerate(steps):
        if step > threshold and not out[-1].endswith(" "):
            out.append(" ")
        out.append(runs[index + 1][1])
    return "".join(out)


def _read_content(data: bytes, fonts: dict[str, dict]) -> list[TextLine]:
    """Walk a content stream's text operators into sized lines.

    Line breaks are inferred from *vertical* movement only. Treating every
    text-positioning operator as a break -- which is the obvious first
    implementation -- shatters any document that places glyphs individually
    into one line per character.
    """
    lines: list[TextLine] = []
    runs: list[tuple[float, str]] = []
    pending: list[str] = []
    size = 0.0
    line_size = 0.0
    x = y = 0.0
    leading = 0.0
    cmap: dict = {}
    stack: list = []
    in_array = False

    def commit_run() -> None:
        if pending:
            runs.append((x, "".join(pending)))
            pending.clear()

    def flush() -> None:
        nonlocal line_size
        commit_run()
        text = _join_runs(runs).strip()
        if text:
            lines.append(TextLine(text, line_size or size))
        runs.clear()
        line_size = 0.0

    def operands(count: int) -> list[float]:
        found = [value for kind, value in stack if kind == "num"]
        return found[-count:] if len(found) >= count else []

    index = 0
    length = len(data)
    while index < length:
        char = data[index]
        if char == 0x28:  # a literal string
            raw, index = _literal_string(data, index)
            stack.append(("str", raw))
            if in_array:
                pending.append(_decode(raw, cmap))
            continue
        if char == 0x25:  # comment
            index = data.find(b"\n", index) + 1 or length
            continue

        match = _TOKEN.match(data, index)
        if match is None:
            index += 1
            continue
        index = match.end()

        if match.group("hex") is not None:
            digits = re.sub(rb"[^0-9A-Fa-f]", b"", match.group("hex")[1:-1])
            if len(digits) % 2:
                digits += b"0"
            raw = bytes.fromhex(digits.decode("ascii"))
            stack.append(("str", raw))
            if in_array:
                pending.append(_decode(raw, cmap))
            continue
        if match.group("name") is not None:
            stack.append(("name", match.group("name")[1:].decode("latin-1")))
            continue
        if match.group("number") is not None:
            value = float(match.group("number"))
            if in_array and value <= WORD_GAP and pending and not pending[-1].endswith(" "):
                pending.append(" ")
            stack.append(("num", value))
            continue
        if match.group("array") is not None:
            in_array = True
            continue
        if match.group("array_end") is not None:
            in_array = False
            continue

        op = match.group("op").decode("latin-1")
        if op == "Tf":
            # `/F1 12 Tf` -- the name and size are the two preceding operands.
            for kind, value in reversed(stack):
                if kind == "num":
                    size = float(value)
                    break
            for kind, value in reversed(stack):
                if kind == "name":
                    cmap = fonts.get(value, {})
                    break
        elif op in ("Tj", "'", '"'):
            for kind, value in reversed(stack):
                if kind == "str":
                    if op != "Tj":
                        flush()
                        y -= leading
                    pending.append(_decode(value, cmap))
                    break
        elif op == "TJ":
            pass  # accumulated as the array was scanned
        elif op == "TL":
            values = operands(1)
            if values:
                leading = values[0]
        elif op in ("Td", "TD"):
            values = operands(2)
            if values:
                commit_run()
                if op == "TD":
                    leading = -values[1]
                if abs(values[1]) > 0.1:
                    flush()
                x += values[0]
                y += values[1]
        elif op == "Tm":
            values = operands(6)
            if values:
                commit_run()
                if abs(values[5] - y) > 0.1:
                    flush()
                x, y = values[4], values[5]
        elif op == "T*":
            flush()
            y -= leading
        elif op in ("BT", "ET"):
            # Not a line break. Word wraps *every* text run in its own
            # `BT ... ET`, so breaking here put one word per line and made the
            # heading detection downstream meaningless. The block only resets
            # the text matrix; the `Tm` that follows says where the text
            # actually goes, and only a change in its y is a new line.
            commit_run()
        if op in ("Tj", "TJ", "'", '"') and not line_size:
            line_size = size
        stack.clear()

    flush()
    return lines


# --- assembly ----------------------------------------------------------------


def _fonts_for(page_dict: bytes, objects: dict[int, bytes],
               cmap_cache: dict[int, dict]) -> dict[str, dict]:
    """Resource name (`F1`) -> ToUnicode map, for one page."""
    resources = _lookup(page_dict, "Resources") or b""
    if not resources.startswith(b"<<"):
        for number in _refs(resources):
            resources = _dict_of(objects.get(number, b""))
            break
    font_dict = _lookup(resources, "Font") or b""
    if not font_dict.startswith(b"<<"):
        for number in _refs(font_dict):
            font_dict = _dict_of(objects.get(number, b""))
            break

    fonts: dict[str, dict] = {}
    for entry in re.finditer(rb"/([^\s/\[\]<>(){}]+)\s+(\d+)\s+\d+\s+R", font_dict):
        name = entry.group(1).decode("latin-1")
        font_body = objects.get(int(entry.group(2)))
        if font_body is None:
            continue
        for cmap_ref in _refs(_lookup(_dict_of(font_body), "ToUnicode")):
            if cmap_ref not in cmap_cache:
                payload = _decode_stream(objects.get(cmap_ref, b""))
                cmap_cache[cmap_ref] = _parse_cmap(payload) if payload else {}
            fonts[name] = cmap_cache[cmap_ref]
            break
    return fonts


def extract_lines(raw: bytes) -> list[TextLine]:
    """Every text line in the document, in page order, with its type size."""
    if not raw.startswith(b"%PDF"):
        raise PdfError("this file does not start with a PDF header.")
    if re.search(rb"/Encrypt\b", raw):
        raise PdfError(
            "this PDF is encrypted. Open it in a PDF viewer and re-save or print "
            "it to a new PDF without a password, then import that."
        )

    objects = _expand_object_streams(raw, _find_objects(raw))
    pages = [
        (number, _dict_of(body))
        for number, body in objects.items()
        if re.search(rb"/Type\s*/Page\b", _dict_of(body))
    ]
    if not pages:
        raise PdfError("no pages found -- the file may be damaged or not a real PDF.")

    cmap_cache: dict[int, dict] = {}
    lines: list[TextLine] = []
    for _number, page_dict in sorted(pages):
        fonts = _fonts_for(page_dict, objects, cmap_cache)
        for content_ref in _refs(_lookup(page_dict, "Contents")):
            payload = _decode_stream(objects.get(content_ref, b""))
            if payload:
                lines.extend(_read_content(payload, fonts))

    if not any(line.text.strip() for line in lines):
        raise PdfError(
            "no text found. This is almost always a scanned document -- the pages "
            "are images, and reading them would need OCR, which Akira has no "
            "offline model for. Retyping the parts you want to teach is the only "
            "route, and is usually the right amount of material anyway."
        )
    return lines
