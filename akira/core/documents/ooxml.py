"""Office Open XML packages — .docx, .xlsx, .pptx — read, and edited in place.

An OOXML file is a ZIP of XML parts. Everything here works on those parts with
the standard library, for two reasons.

**No new dependencies.** python-docx and its relatives are not installed, and
installing them is the network step `requirements.txt` audits one package at a
time. Nothing the document tools need is beyond `zipfile` and a careful
reading of the XML.

**Fidelity.** Parsing a part with ElementTree and writing it back does not give
back the same XML. It renames namespace prefixes, and it drops declarations
that no element uses — including the ones named only inside `mc:Ignorable`,
which Word then reports as unreadable content. So edits here are *surgical*:
the text of individual runs is spliced into the original XML string, every
other byte of that part stays as it was, and every other part of the package
is copied through unchanged. Reading does parse, because nothing is written
back from a parse.

**Hostile files.** A document can come from anywhere. The declared sizes of
every member are checked before anything is read — a few kilobytes of ZIP can
declare gigabytes — and a single part stops being read one byte past its limit
regardless of what it declares.
"""

from __future__ import annotations

import contextlib
import html
import io
import os
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree
from akira.core import files

MAX_PACKAGE_BYTES = 100_000_000
MAX_PART_BYTES = 40_000_000
MAX_TOTAL_BYTES = 300_000_000
MAX_MEMBERS = 10_000

REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"

OFFICE_DOCUMENT = REL + "/officeDocument"
CORE_REL = PKG_REL + "/metadata/core-properties"
APP_REL = REL + "/extended-properties"
CORE_TYPE = "application/vnd.openxmlformats-package.core-properties+xml"
APP_TYPE = "application/vnd.openxmlformats-officedocument.extended-properties+xml"

XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

APP_PROPERTIES = (XML_DECL + "<Properties xmlns=\"http://schemas.openxmlformats.org/"
                  "officeDocument/2006/extended-properties\"><Application>Akira"
                  "</Application></Properties>")

_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


class PackageError(ValueError):
    """Not a readable or editable Office document, with a reason for the person."""


def clean_text(text: str) -> str:
    """Text that is legal inside XML. Control characters have no place there."""
    text = text.encode("utf-8", "replace").decode("utf-8")
    return _INVALID_XML.sub("", text)


def escape(text: str) -> str:
    """Escape text content: `&`, `<` and `>`.

    Not `xml.sax.saxutils.escape`, which does the same job, because importing
    that module imports `urllib.request` — and a networking module has no place
    in this process, used or not.
    """
    return html.escape(text, quote=False)


def attribute(text: str) -> str:
    """Escape an attribute value, quotes included."""
    return html.escape(text, quote=True)


def decode_part(data: bytes) -> tuple[str, bool]:
    """A part's XML as text, and whether it began with a byte-order mark."""
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        return data.decode("utf-8-sig"), bom
    except UnicodeDecodeError:
        raise PackageError(
            "part of this document is not stored as UTF-8, so it cannot be edited "
            "without risking its contents") from None


def encode_part(text: str, bom: bool) -> bytes:
    data = text.encode("utf-8")
    return b"\xef\xbb\xbf" + data if bom else data


def resolve(folder: str, target: str) -> str:
    """A relationship target, resolved against the folder of its source part."""
    if target.startswith("/"):
        return target.lstrip("/")
    parts = folder.split("/") if folder else []
    for piece in target.split("/"):
        if piece == "..":
            if parts:
                parts.pop()
        elif piece and piece != ".":
            parts.append(piece)
    return "/".join(parts)


class Package:
    """An OOXML package, opened defensively."""

    def __init__(self, raw: bytes, name: str = "the document") -> None:
        self.name = name
        if len(raw) > MAX_PACKAGE_BYTES:
            raise PackageError(f"{name} is over {MAX_PACKAGE_BYTES // 1_000_000} MB.")
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            raise PackageError(
                f"{name} is not a modern Office document. Older .doc, .xls and "
                ".ppt files need saving as .docx, .xlsx or .pptx first.") from None
        infos = self._zip.infolist()
        if len(infos) > MAX_MEMBERS:
            raise PackageError(f"{name} holds {len(infos)} parts, which no real document does.")
        total = sum(info.file_size for info in infos)
        if total > MAX_TOTAL_BYTES:
            raise PackageError(
                f"{name} would expand to {total // 1_000_000} MB — far more than any "
                "real document needs — so it was not opened.")
        self.raw = raw
        self._infos = {info.filename: info for info in infos}

    def has(self, part: str) -> bool:
        return part in self._infos

    def names(self) -> list[str]:
        return list(self._infos)

    def read(self, part: str) -> bytes:
        info = self._infos.get(part)
        if info is None:
            raise PackageError(f"{self.name} has no {part} inside it.")
        if info.file_size > MAX_PART_BYTES:
            raise PackageError(f"{part} in {self.name} is too large to read.")
        with self._zip.open(info) as stream:
            data = stream.read(MAX_PART_BYTES + 1)
        if len(data) > MAX_PART_BYTES:
            raise PackageError(f"{part} in {self.name} is larger than it declares.")
        return data

    def xml(self, part: str) -> ElementTree.Element:
        try:
            return ElementTree.fromstring(self.read(part))
        except ElementTree.ParseError as exc:
            raise PackageError(f"{part} in {self.name} is damaged: {exc}") from None

    def relationships(self, part: str) -> dict[str, tuple[str, str]]:
        """Id → (type, resolved target part) for the relationships of \a part.

        The package's own relationships are those of the part `""`.
        """
        folder, _, filename = part.rpartition("/")
        rels = f"{folder}/_rels/{filename}.rels" if folder else f"_rels/{filename}.rels"
        if not self.has(rels):
            return {}
        result = {}
        for relation in self.xml(rels).iter(f"{{{PKG_REL}}}Relationship"):
            if relation.get("TargetMode") == "External":
                continue
            result[relation.get("Id", "")] = (relation.get("Type", ""),
                                              resolve(folder, relation.get("Target", "")))
        return result

    def rewritten(self, replacements: dict[str, bytes],
                  remove: set[str] | frozenset[str] = frozenset()) -> bytes:
        """The package with some parts replaced and every other part carried over."""
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as target:
            for info in self._zip.infolist():
                if info.filename in remove:
                    continue
                data = (replacements[info.filename] if info.filename in replacements
                        else self._zip.read(info))
                clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                clone.compress_type = info.compress_type
                clone.external_attr = info.external_attr
                clone.create_system = info.create_system
                target.writestr(clone, data)
            for name, data in replacements.items():
                if name not in self._infos:
                    added = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
                    added.compress_type = zipfile.ZIP_DEFLATED
                    target.writestr(added, data)
        return out.getvalue()


def main_part(package: Package, fallback: str) -> str:
    for kind, target in package.relationships("").values():
        if kind.endswith("/officeDocument") and package.has(target):
            return target
    if package.has(fallback):
        return fallback
    raise PackageError(f"{package.name} has no main document part.")


def write_atomically(path: Path, data: bytes) -> None:
    """Replace \a path in one step, so a crash never leaves half a document."""
    handle, temporary = tempfile.mkstemp(prefix=".protege-", suffix=path.suffix,
                                         dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        files.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


# -- building new packages -------------------------------------------------------


def build_package(parts: dict[str, str | bytes]) -> bytes:
    out = io.BytesIO()
    stamp = time.localtime()[:6]
    with zipfile.ZipFile(out, "w") as target:
        for name, content in parts.items():
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, content.encode("utf-8") if isinstance(content, str) else content)
    return out.getvalue()


def content_types(overrides: dict[str, str]) -> str:
    items = "".join(f'<Override PartName="/{name}" ContentType="{kind}"/>'
                    for name, kind in overrides.items())
    return (XML_DECL + f'<Types xmlns="{CONTENT_TYPES}">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>' + items + "</Types>")


def relationships_xml(items: list[tuple[str, str, str]]) -> str:
    body = "".join(f'<Relationship Id="{rid}" Type="{kind}" Target="{target}"/>'
                   for rid, kind, target in items)
    return XML_DECL + f'<Relationships xmlns="{PKG_REL}">{body}</Relationships>'


def core_properties(title: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (XML_DECL +
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{escape(clean_text(title))}</dc:title><dc:creator>Akira</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified>'
            "</cp:coreProperties>")


# -- editing text in runs, surgically ------------------------------------------------


@dataclass(frozen=True, slots=True)
class Run:
    """One text element: where its opening tag and its content sit in the XML."""

    open_start: int
    open_end: int
    end: int
    text: str


def namespace_prefix(xml: str, namespace: str) -> str | None:
    """The prefix \a xml binds to \a namespace: "" if it is the default, None if unbound."""
    match = re.search(r"xmlns(?::([A-Za-z_][\w.\-]*))?\s*=\s*[\"']" + re.escape(namespace)
                      + r"[\"']", xml)
    if match is None:
        return None
    return match.group(1) or ""


def qualified(prefix: str, local: str) -> str:
    return f"{prefix}:{local}" if prefix else local


def paragraph_runs(xml: str, para_tag: str, text_tag: str) -> list[list[Run]]:
    """Every text run, grouped by the paragraph that directly holds it.

    A tokenising scan rather than a parse, because the positions are what
    matter. Paragraphs can nest — a text box inside a paragraph holds its own
    paragraphs — so an open-paragraph stack assigns each run to its innermost
    paragraph, and a match never crosses from one paragraph into another.
    """
    token = re.compile(r"<(/?)(" + re.escape(para_tag) + "|" + re.escape(text_tag)
                       + r")(?=[\s/>])([^>]*)>")
    groups: list[list[Run]] = []
    stack: list[list[Run]] = []
    for match in token.finditer(xml):
        closing, tag, rest = match.groups()
        empty = rest.rstrip().endswith("/")
        if tag == para_tag:
            if closing:
                if stack:
                    groups.append(stack.pop())
            elif not empty:
                stack.append([])
            continue
        if closing or empty:
            continue
        end = xml.find("</" + text_tag, match.end())
        if end < 0:
            raise PackageError("a run of text is never closed; the document is damaged")
        if stack:
            stack[-1].append(Run(match.start(), match.end(), end,
                                 html.unescape(xml[match.end():end])))
    return groups


def _replace_in_paragraph(runs: list[Run], find: str, replacement: str,
                          edits: list[tuple[Run, str]]) -> int:
    full = "".join(run.text for run in runs)
    matches: list[tuple[int, int]] = []
    position = full.find(find)
    while position >= 0:
        matches.append((position, position + len(find)))
        position = full.find(find, position + len(find))
    if not matches:
        return 0

    start = 0
    for run in runs:
        end = start + len(run.text)
        pieces: list[str] = []
        cursor = start
        for a, b in matches:
            if b <= start or a >= end:
                continue
            if a > cursor:
                pieces.append(full[cursor:min(a, end)])
            if start <= a < end:
                # The replacement lands in the run where the match begins, so it
                # takes that run's formatting. The rest of the match is trimmed
                # from the runs it spilled into.
                pieces.append(replacement)
            cursor = max(cursor, min(b, end))
        if cursor < end:
            pieces.append(full[cursor:end])
        text = "".join(pieces)
        if text != run.text:
            edits.append((run, text))
        start = end
    return len(matches)


def replace_text(xml: str, namespace: str, para_local: str, text_local: str,
                 find: str, replacement: str, *, preserve_space: bool) -> tuple[str, int]:
    """Replace \a find in the runs of \a xml. Returns the new XML and the count.

    Only the content of the text elements that change is touched, plus an
    `xml:space="preserve"` on an opening tag whose new text begins or ends in
    whitespace, where the format would otherwise trim it.
    """
    if not find:
        raise PackageError("there is nothing to look for")
    prefix = namespace_prefix(xml, namespace)
    if prefix is None:
        return xml, 0
    replacement = clean_text(replacement)
    edits: list[tuple[Run, str]] = []
    count = 0
    for runs in paragraph_runs(xml, qualified(prefix, para_local), qualified(prefix, text_local)):
        count += _replace_in_paragraph(runs, find, replacement, edits)

    for run, text in sorted(edits, key=lambda item: item[0].open_start, reverse=True):
        xml = xml[:run.open_end] + escape(text) + xml[run.end:]
        opening = xml[run.open_start:run.open_end]
        if preserve_space and text != text.strip() and "xml:space" not in opening:
            xml = (xml[:run.open_end - 1] + ' xml:space="preserve"'
                   + xml[run.open_end - 1:])
    return xml, count
