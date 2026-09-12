"""Text from outside is plain text (rule 5 in QML_BRIDGES.md), checked in the QML.

Qt's default for a `Text` is `AutoText`, which renders whatever looks like HTML
and loads an `<img>` in it. A web address is refused by the engine, but
`file://server/share/x.png` is opened by Windows as a network share, offering
that server the person's sign-in. So every `Text` or `Label` whose text is not a
literal written in the QML says how it is shown, and rich text appears only
where a bridge serves text made safe for it.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6.QtQml")

from akira.ui.engine import QML_ROOT  # noqa: E402

_OPEN = re.compile(r"\b(?:Text|Label)\s*\{")
_TEXT = re.compile(r"(?:\A|[;\n])[ \t]*text[ \t]*:")
_FORMAT = re.compile(r"(?:\A|[;\n])\s*textFormat\s*:")
#: A string written in the QML, alone in its statement: the whole binding is a literal.
_LITERAL = re.compile(r"""[ \t]*(?:qsTr\(\s*)?(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')"""
                      r"""[ \t]*\)?[ \t]*(?:;|\n|\Z)""")
_RICH = re.compile(r"\b(?:Text|TextEdit)\.(?:RichText|StyledText|MarkdownText|AutoText)\b")

#: Where rich text may appear, and why it is safe there.
RICH_ALLOWED = {
    # Chat replies, which the bridge serves with every picture turned into a link.
    "Akira/MessageBody.qml",
}


def _elements(source: str):
    """(line, what is written directly inside) for every Text or Label element."""
    for match in _OPEN.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        depth, i, own, quote = 1, match.end(), [], ""
        while i < len(source) and depth:
            ch = source[i]
            if quote:
                if depth == 1:
                    own.append(source[i:i + 2] if ch == "\\" else ch)
                if ch == "\\":
                    i += 2
                    continue
                if ch == quote:
                    quote = ""
            elif source.startswith("//", i):
                end = source.find("\n", i)
                i = len(source) if end < 0 else end
                continue
            elif source.startswith("/*", i):
                end = source.find("*/", i + 2)
                i = len(source) if end < 0 else end + 2
                continue
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            else:
                if ch in "\"'`":
                    quote = ch
                if depth == 1:
                    own.append(ch)
            i += 1
        yield line, "".join(own)


def unformatted(source: str) -> list[int]:
    """Lines of elements that show text from a binding without saying how."""
    lines = []
    for line, own in _elements(source):
        binding = _TEXT.search(own)
        if binding and not _LITERAL.match(own, binding.end()) and not _FORMAT.search(own):
            lines.append(line)
    return lines


def _qml_files():
    return sorted(QML_ROOT.rglob("*.qml"))


def test_every_text_showing_data_says_how_it_is_shown():
    missing = [f"{path.relative_to(QML_ROOT).as_posix()}:{line}"
               for path in _qml_files()
               for line in unformatted(path.read_text(encoding="utf-8"))]
    assert missing == [], ("A Text showing data must set textFormat, Text.PlainText for "
                           "anything from outside: " + ", ".join(missing))


def test_rich_text_only_where_a_bridge_made_it_safe():
    found = sorted({path.relative_to(QML_ROOT).as_posix() for path in _qml_files()
                    if _RICH.search(path.read_text(encoding="utf-8"))})
    assert set(found) <= RICH_ALLOWED, f"rich text in {sorted(set(found) - RICH_ALLOWED)}"


@pytest.mark.parametrize("source,flagged", [
    ('Text { text: model.title }', [1]),
    ('Text { text: "Hello" }', []),
    ("Text { text: qsTr('Hello') }", []),
    ('Text { text: row.text; textFormat: Text.PlainText }', []),
    ('Label {\n    color: "red"\n    text: root.name\n}', [1]),
    ('Text {\n  Behavior on color { ColorAnimation { duration: 1 } }\n  text: x\n}', [1]),
    ('Text {\n  // text: ignored\n  text: "literal with { brace"\n}', []),
    ('Text { text: "a \\"quoted\\"; thing // not a comment"; color: "red" }', []),
    ('Text { text: "radius " + label }', [1]),
    ('TextEdit { text: code }', []),
    ('Item {\n  Text { text: a; textFormat: Text.PlainText }\n  Text { text: b }\n}', [3]),
])
def test_the_check_sees_what_it_should(source, flagged):
    assert unformatted(source) == flagged
