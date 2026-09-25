"""Drawings (E2): SVG as something a model writes, and Akira cleans before anyone sees it.

A model draws by writing SVG, which is text: shapes, paths, gradients and words
placed on a canvas. But SVG is also a document format with a lot more in it
than drawing. It can carry scripts and event handlers, links that fetch from
the internet when shown, other documents embedded whole (`foreignObject`),
pictures from elsewhere, animations that rewrite links, and declarations that
expand into gigabytes. A model writes whatever the conversation led it to,
including what a web page it read told it to. So nothing a model draws is shown
or saved as it was written.

`clean` rebuilds the drawing from what is known to be safe, and only that:
drawing elements, and the attributes that position, colour and style them. A
link may point only inside the drawing (`#id`). A style may refer only inside
the drawing too. Everything else is left out, and `Drawing.removed` says what,
so the model can be told. A drawing that is not SVG at all, or whose outer
element is not `<svg>`, is refused.

`picture` renders a clean drawing to a PNG with Qt's own SVG renderer, which
fetches nothing. It needs the interface running (a `QGuiApplication`), because
Qt draws text only then; without one it returns None.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"

#: The longest drawing read, in characters. A logo is a few kilobytes.
MAX_CHARACTERS = 500_000

#: The most elements a drawing may have, and how deeply they may nest.
MAX_ELEMENTS = 5_000
MAX_DEPTH = 40

#: The largest a picture of a drawing is made, on its longer side, in pixels.
MAX_PICTURE = 2048

#: What a drawing is made of. Nothing that runs, fetches, embeds or animates.
ELEMENTS = frozenset({
    "svg", "g", "defs", "symbol", "use", "title", "desc", "style",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan", "textPath",
    "linearGradient", "radialGradient", "stop", "pattern", "clipPath", "mask", "marker",
    "filter", "feBlend", "feColorMatrix", "feComponentTransfer", "feComposite",
    "feDisplacementMap", "feDropShadow", "feFlood", "feFuncA", "feFuncB", "feFuncG", "feFuncR",
    "feGaussianBlur", "feMerge", "feMergeNode", "feMorphology", "feOffset", "feTurbulence",
})

#: What those elements may say about themselves: where, what shape, what colour.
ATTRIBUTES = frozenset({
    "id", "class", "style", "transform", "viewBox", "preserveAspectRatio", "version",
    "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
    "fx", "fy", "fr", "d", "points", "pathLength", "href",
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray",
    "stroke-dashoffset", "opacity", "color", "display", "visibility", "overflow",
    "clip-path", "clip-rule", "mask", "filter", "paint-order", "vector-effect",
    "shape-rendering", "text-rendering", "mix-blend-mode", "isolation",
    "font-family", "font-size", "font-weight", "font-style", "font-variant", "font-stretch",
    "text-anchor", "dominant-baseline", "alignment-baseline", "baseline-shift",
    "letter-spacing", "word-spacing", "text-decoration", "writing-mode", "dx", "dy",
    "rotate", "textLength", "lengthAdjust", "startOffset", "side", "method", "spacing",
    "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
    "spreadMethod", "patternUnits", "patternContentUnits", "patternTransform",
    "clipPathUnits", "maskUnits", "maskContentUnits", "markerWidth", "markerHeight",
    "markerUnits", "refX", "refY", "orient", "marker-start", "marker-mid", "marker-end",
    "filterUnits", "primitiveUnits", "in", "in2", "result", "stdDeviation", "mode",
    "type", "values", "operator", "k1", "k2", "k3", "k4", "flood-color", "flood-opacity",
    "baseFrequency", "numOctaves", "seed", "stitchTiles", "scale", "xChannelSelector",
    "yChannelSelector", "radius", "tableValues", "slope", "intercept", "amplitude",
    "exponent", "lighting-color",
})

#: Anything that reaches out of the drawing, or hides that it does.
_REACHES_OUT = re.compile(
    r"url\s*\(\s*(?![\"']?#)|@import|expression\s*\(|javascript:|vbscript:|data:|\\|&#|<",
    re.IGNORECASE)

_DECLARATION = re.compile(r"<!\s*(DOCTYPE|ENTITY|ELEMENT|ATTLIST)", re.IGNORECASE)
_BLOCK = re.compile(r"```[ \t]*(?:svg|xml)?[ \t]*\n(.*?)```", re.IGNORECASE | re.DOTALL)
_BARE = re.compile(r"<svg\b.*?</svg\s*>", re.IGNORECASE | re.DOTALL)


class DrawingError(ValueError):
    """Why a drawing cannot be used at all, said so a model can fix it."""


@dataclass(frozen=True)
class Drawing:
    """A drawing, rebuilt from what is safe in what was written."""

    svg: str
    width: float
    height: float
    """Its size in its own units, from its viewBox or its width and height."""
    removed: tuple[str, ...] = ()
    """What was left out, each named once, such as "script" or "onclick"."""


def drawings_in(text: str) -> list[str]:
    """The SVG in a model's reply: each ```svg block, or else each bare <svg>…</svg>."""
    blocks = [block for block in _BLOCK.findall(text) if "<svg" in block.lower()]
    return blocks or _BARE.findall(text)


def _local(name: str) -> tuple[str, str]:
    """(namespace, name) of an element's or attribute's name."""
    if name.startswith("{"):
        namespace, _, local = name[1:].partition("}")
        return namespace, local
    return "", name


def _number(text: str | None) -> float:
    found = re.match(r"\s*([0-9]*\.?[0-9]+)", text or "")
    return float(found.group(1)) if found else 0.0


def _size(root: ElementTree.Element) -> tuple[float, float]:
    box = (root.get("viewBox") or "").replace(",", " ").split()
    if len(box) == 4:
        try:
            width, height = float(box[2]), float(box[3])
            if width > 0 and height > 0:
                return width, height
        except ValueError:
            pass
    width, height = _number(root.get("width")), _number(root.get("height"))
    if width > 0 and height > 0:
        return width, height
    return 0.0, 0.0


def clean(text: str) -> Drawing:
    """\a text rebuilt as a drawing that cannot run, fetch or embed anything.

    Raises `DrawingError` when there is no usable drawing in it.
    """
    text = (text or "").strip()
    if not text:
        raise DrawingError("There is no drawing: the SVG is empty.")
    if len(text) > MAX_CHARACTERS:
        raise DrawingError(f"The SVG is longer than {MAX_CHARACTERS:,} characters. "
                           "Draw it more simply.")
    if _DECLARATION.search(text):
        # Declarations are how a few lines of XML become gigabytes, or reach a
        # file. A drawing never needs one.
        raise DrawingError("The SVG has a <!DOCTYPE> or <!ENTITY> declaration. Leave it out: "
                           "a drawing needs none.")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise DrawingError(f"The SVG is not well-formed XML: {exc}.") from None
    namespace, name = _local(root.tag)
    if name != "svg" or namespace not in ("", SVG_NS):
        raise DrawingError(f"A drawing is an <svg> element; this is <{name}>.")

    removed: dict[str, None] = {}
    count = 0

    def rebuild(element: ElementTree.Element, depth: int) -> ElementTree.Element | None:
        nonlocal count
        namespace, name = _local(element.tag)
        if name == "a" and namespace in ("", SVG_NS):
            # A link around shapes: the shapes are kept, as a group, without it.
            removed["a link (what it held is kept)"] = None
            held = list(element)
            element = ElementTree.Element(f"{{{SVG_NS}}}g",
                                          {k: v for k, v in element.attrib.items()
                                           if _local(k)[1] not in ("href", "target")})
            element.extend(held)
            name = "g"
        if namespace not in ("", SVG_NS) or name not in ELEMENTS:
            removed[name] = None
            return None
        count += 1
        if count > MAX_ELEMENTS or depth > MAX_DEPTH:
            raise DrawingError(f"The SVG has more than {MAX_ELEMENTS:,} elements, or nests "
                               f"them more than {MAX_DEPTH} deep. Draw it more simply.")
        made = ElementTree.Element(f"{{{SVG_NS}}}{name}")
        for key, value in element.attrib.items():
            space, attribute = _local(key)
            if space == XLINK_NS and attribute == "href":
                attribute = "href"
            elif space == XML_NS and attribute == "space":
                made.set(key, value)
                continue
            elif space or attribute not in ATTRIBUTES:
                removed[attribute] = None
                continue
            if attribute == "href":
                if not value.strip().startswith("#") or _REACHES_OUT.search(value):
                    removed["a link out of the drawing"] = None
                    continue
                # Written as xlink:href, which every renderer, Qt's included, reads.
                made.set(f"{{{XLINK_NS}}}href", value.strip())
                continue
            if _REACHES_OUT.search(value):
                removed[f"{attribute} that reaches out of the drawing"] = None
                continue
            made.set(attribute, value)
        if name == "style":
            css = "".join(element.itertext())
            if _REACHES_OUT.search(css):
                removed["a style that reaches out of the drawing"] = None
                return None
            made.text = css
        elif element.text and name in ("text", "tspan", "textPath", "title", "desc"):
            made.text = element.text
        for child in element:
            kept = rebuild(child, depth + 1)
            if kept is not None:
                if child.tail and name in ("text", "tspan", "textPath"):
                    kept.tail = child.tail
                made.append(kept)
        return made

    rebuilt = rebuild(root, 0)
    assert rebuilt is not None  # the root was checked above
    width, height = _size(rebuilt)
    if not (width and height):
        raise DrawingError("The SVG has no size. Give the <svg> a viewBox, such as "
                           "viewBox=\"0 0 512 512\".")
    ElementTree.register_namespace("", SVG_NS)
    ElementTree.register_namespace("xlink", XLINK_NS)
    svg = ElementTree.tostring(rebuilt, encoding="unicode")
    return Drawing(svg, width, height, tuple(removed))


def picture(drawing: Drawing, longest: int = 512, form: str = "PNG") -> bytes | None:
    """\a drawing rendered, \a longest pixels on its longer side, as PNG (or JPG).

    None without a running interface, or if Qt cannot render it.
    """
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
        from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    if not isinstance(QGuiApplication.instance(), QGuiApplication):
        return None
    longest = max(16, min(int(longest), MAX_PICTURE))
    scale = longest / max(drawing.width, drawing.height)
    width = max(1, round(drawing.width * scale))
    height = max(1, round(drawing.height * scale))
    renderer = QSvgRenderer(QByteArray(drawing.svg.encode("utf-8")))
    if not renderer.isValid():
        return None
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    # JPEG has no transparency, so it is drawn on white; PNG keeps it.
    image.fill(QColor(255, 255, 255) if form.upper() in ("JPG", "JPEG") else QColor(0, 0, 0, 0))
    painter = QPainter(image)
    try:
        renderer.render(painter, QRectF(0, 0, width, height))
    finally:
        painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, form.upper()):
        return None
    return bytes(buffer.data())
