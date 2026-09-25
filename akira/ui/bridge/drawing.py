"""Drawings in the chat (E2) — the `Drawing` bridge.

A reply can hold a drawing: SVG in a ```svg block, which the model is told it
may write. The view shows it as a picture: `drawingsIn(text)` finds each one,
and `picture(svg, size)` gives a PNG of it, cleaned first, so nothing in it can
run or fetch anything. `check(svg)` says what was left out, for a line under
the picture. `save(svg, fileUrl)` writes it where the person chose in a save
dialog: their own act, like Save As, so it needs no grant.

What a model wrote is never shown or saved as written; see
`akira.core.making.svg`.
"""

from __future__ import annotations

import base64
import contextlib
import os
import tempfile
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Slot

from akira.core import files
from akira.core.making.svg import DrawingError, clean, drawings_in, picture

#: Pictures kept, so a reply scrolled past and back is not drawn again.
KEPT = 64

#: The largest picture the view may ask for, on its longer side.
LARGEST = 2048


class DrawingBridge(QObject):
    """Finds, cleans, shows and saves the drawings in the chat's replies."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pictures: OrderedDict[tuple[str, int], str] = OrderedDict()

    @Slot(str, result="QVariantList")
    def drawingsIn(self, text: str) -> list:
        """Each drawing in a reply, as the model wrote it; `picture` cleans it."""
        return drawings_in(text or "")

    @Slot(str, int, result=str)
    def picture(self, svg: str, longest: int) -> str:
        """A PNG of the drawing, cleaned, as a `data:` address for an `Image`; "" if unusable."""
        longest = max(16, min(int(longest or 512), LARGEST))
        key = (svg, longest)
        if key in self._pictures:
            self._pictures.move_to_end(key)
            return self._pictures[key]
        try:
            drawn = picture(clean(svg), longest, "PNG")
        except DrawingError:
            drawn = None
        address = ("data:image/png;base64," + base64.b64encode(drawn).decode("ascii")
                   if drawn else "")
        self._pictures[key] = address
        while len(self._pictures) > KEPT:
            self._pictures.popitem(last=False)
        return address

    @Slot(str, result="QVariantMap")
    def check(self, svg: str) -> dict:
        """`usable`, `width`, `height`, `removed` (what was left out) and `note`."""
        try:
            drawing = clean(svg)
        except DrawingError as exc:
            return {"usable": False, "width": 0, "height": 0, "removed": [], "note": str(exc)}
        note = ("Left out, because a drawing may not run or fetch anything: "
                + ", ".join(drawing.removed) + ".") if drawing.removed else ""
        return {"usable": True, "width": drawing.width, "height": drawing.height,
                "removed": list(drawing.removed), "note": note}

    @Slot(str, str, result=str)
    def save(self, svg: str, where: str) -> str:
        """Write the drawing, cleaned, to the file the person chose: "" or why not.

        A .svg file gets the SVG, a .png file a 1024-pixel picture of it.
        """
        url = QUrl(where)
        path = Path(url.toLocalFile() if url.isLocalFile() else where)
        suffix = path.suffix.lower()
        if suffix not in (".svg", ".png"):
            return "Save a drawing as a .svg file, or as a picture in a .png file."
        try:
            drawing = clean(svg)
        except DrawingError as exc:
            return str(exc)
        if suffix == ".svg":
            data = drawing.svg.encode("utf-8")
        else:
            data = picture(drawing, 1024, "PNG")
            if data is None:
                return "The picture could not be made."
        if not path.parent.is_dir():
            return f"{path.parent} is not a folder."
        handle, temporary = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
            files.replace(temporary, path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            return f"{path} could not be written: {exc}"
        return ""
