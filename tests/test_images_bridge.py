"""The Images bridge's Stop: what the Pictures sheet's Stop button calls."""

from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from akira.core.making import images  # noqa: E402
from akira.ui.bridge.images import ImagesBridge  # noqa: E402


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


class SlowMaker:
    """Makes nothing until stopped, as `ImageMaker` does on a long picture."""

    prepared = True

    def __init__(self):
        self.started = threading.Event()
        self._stop = threading.Event()

    def make(self, prompt, **options):
        self.started.set()
        assert self._stop.wait(5), "it was never stopped"
        raise images.Stopped()

    def stop(self):
        self._stop.set()


def pump_until(app, predicate, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    return predicate()


def test_a_picture_being_made_is_stopped_from_the_interface(app, monkeypatch):
    monkeypatch.setattr(images, "unavailable", lambda: "")
    maker = SlowMaker()
    bridge = ImagesBridge(maker)
    assert bridge.stop() == "Nothing is being made."
    assert bridge.make("a fox", "", 512, 512, 4, -1) == ""
    assert maker.started.wait(5) and bridge.busy == "making"
    assert bridge.stop() == ""
    assert bridge.note == "Stopping…"
    assert pump_until(app, lambda: bridge.busy == "")
    assert bridge.note == "Stopped." and bridge.picture == ""
    bridge.close()
