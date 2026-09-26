"""Making a picture from a description (E1) — the `Images` bridge.

The person describes a picture, and `make(...)` makes it on a worker with
SDXL-Turbo on the graphics card (`akira.core.making.images`). While it is made
the language models are set aside, so an answer in progress finishes first and
the next one starts a few seconds later than usual. The very first picture
also makes the 8-bit copy of the model that fits the card, which takes minutes,
once; `prepared` says whether that has happened, and `prepare()` does it ahead
of time.

The picture is the person's: shown from `picture`, saved with `save` where
they chose in a save dialog, their own act, so no grant is needed. Nothing is
kept unless they save it.
"""

from __future__ import annotations

import base64
import contextlib
import os
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from akira.core import files
from akira.core.making import images
from akira.core.making.images import ImageError, ImageMaker, Picture


class ImagesBridge(QObject):
    """One picture at a time, made from what the person describes."""

    stateChanged = Signal()
    pictureChanged = Signal()

    #: Private: from the worker to this thread.
    _made = Signal(object, str)
    _prepared = Signal(str)

    def __init__(self, maker: ImageMaker | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._maker = maker if maker is not None else ImageMaker()
        self._busy = ""
        self._note = ""
        self._picture: Picture | None = None
        self._worker: threading.Thread | None = None
        self._made.connect(self._on_made)
        self._prepared.connect(self._on_prepared)

    # -- what the interface reads ------------------------------------------------------------

    @Property(bool, notify=stateChanged)
    def available(self) -> bool:
        return not images.unavailable()

    @Property(str, notify=stateChanged)
    def unavailableReason(self) -> str:
        return images.unavailable()

    @Property(bool, notify=stateChanged)
    def prepared(self) -> bool:
        """Whether the 8-bit copy of the model has been made; until then the first
        picture takes minutes longer."""
        return self._maker.prepared

    @Property(str, notify=stateChanged)
    def busy(self) -> str:
        """`preparing`, `making`, or "" when idle."""
        return self._busy

    @Property(str, notify=stateChanged)
    def note(self) -> str:
        return self._note

    @Property(str, notify=pictureChanged)
    def picture(self) -> str:
        """The last picture, as a `data:image/png` address for an `Image`, or ""."""
        if self._picture is None:
            return ""
        return "data:image/png;base64," + base64.b64encode(self._picture.png).decode("ascii")

    @Property("QVariantMap", notify=pictureChanged)
    def details(self) -> dict:
        """`prompt`, `width`, `height`, `steps`, `seed` and `seconds` of the last picture."""
        p = self._picture
        if p is None:
            return {}
        return {"prompt": p.prompt, "width": p.width, "height": p.height, "steps": p.steps,
                "seed": p.seed, "seconds": p.seconds}

    @Property("QVariantList", constant=True)
    def sides(self) -> list:
        return list(images.SIDES)

    # -- the person's choices ----------------------------------------------------------------

    @Slot(str, str, int, int, int, int, result=str)
    def make(self, prompt: str, negative: str, width: int, height: int, steps: int,
             seed: int) -> str:
        """Make a picture: "" once started, or why not. `seed` below 0 means a new one."""
        if self._busy:
            return "A picture is already being made."
        try:
            images.clean_prompt(prompt)
            images.check_size(width, height, steps)
        except ImageError as exc:
            return str(exc)
        problem = images.unavailable()
        if problem:
            return problem
        self._busy = "making" if self._maker.prepared else "preparing"
        self._note = ("" if self._maker.prepared else
                      "Getting the model ready for the graphics card, once. This takes a few "
                      "minutes.")
        self.stateChanged.emit()
        self._start(lambda: self._make(prompt, negative, width, height, steps, seed))
        return ""

    @Slot(result=str)
    def prepare(self) -> str:
        """Make the 8-bit copy now, so the first picture is quick: "" once started."""
        if self._busy:
            return "Something is already running."
        if self._maker.prepared:
            return ""
        self._busy = "preparing"
        self.stateChanged.emit()
        self._start(self._prepare)
        return ""

    @Slot(str, result=str)
    def save(self, where: str) -> str:
        """Write the last picture to the .png file the person chose: "" or why not."""
        if self._picture is None:
            return "There is no picture to save."
        url = QUrl(where)
        path = Path(url.toLocalFile() if url.isLocalFile() else where)
        if path.suffix.lower() != ".png":
            return "A picture is saved as a .png file."
        if not path.parent.is_dir():
            return f"{path.parent} is not a folder."
        handle, temporary = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(self._picture.png)
            files.replace(temporary, path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            return f"{path} could not be written: {exc}"
        return ""

    @Slot()
    def clear(self) -> None:
        self._picture = None
        self.pictureChanged.emit()

    # -- the worker ---------------------------------------------------------------------------

    def _start(self, job) -> None:
        self._worker = threading.Thread(target=job, name="akira-picture", daemon=True)
        self._worker.start()

    def _make(self, prompt, negative, width, height, steps, seed) -> None:
        try:
            made = self._maker.make(prompt, negative=negative, width=width, height=height,
                                    steps=steps, seed=seed if seed >= 0 else None)
        except ImageError as exc:
            self._made.emit(None, str(exc))
        except Exception as exc:  # noqa: BLE001 - a crashed worker must not be silent
            self._made.emit(None, f"The picture could not be made: {exc}")
        else:
            self._made.emit(made, "")

    def _prepare(self) -> None:
        try:
            self._maker.prepare()
        except ImageError as exc:
            self._prepared.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self._prepared.emit(f"The model could not be made ready: {exc}")
        else:
            self._prepared.emit("")

    @Slot(object, str)
    def _on_made(self, picture, problem: str) -> None:
        self._busy = ""
        if picture is not None:
            self._picture = picture
            self._note = f"Made in {picture.seconds:g} seconds."
            self.pictureChanged.emit()
        else:
            self._note = problem
        self.stateChanged.emit()

    @Slot(str)
    def _on_prepared(self, problem: str) -> None:
        self._busy = ""
        self._note = problem or "The model is ready."
        self.stateChanged.emit()

    def close(self) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(1.0)
