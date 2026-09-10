"""Exercise real Qt scene playback and lifecycle without loading a model.

Kept in a separate process from the legacy tests, which own a QCoreApplication
and cannot promote it to the QGuiApplication required for scene rendering.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from PySide6.QtCore import QDateTime
from PySide6.QtGui import QGuiApplication
from protege.ui.engine import build_engine, configure_application, load
from preview_scenes import settle


def fingerprint(window):
    image = window.grabWindow()
    assert not image.isNull(), "Empty scene capture"
    return hashlib.sha256(bytes(image.constBits())).hexdigest()


def main():
    app = QGuiApplication(sys.argv[:1])
    configure_application(app)
    engine, theme = build_engine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    window = load(engine, REPO / "protege/ui/qml/SceneGallery.qml")
    window.setWidth(960)
    window.setHeight(540)
    for scene in ("coast", "space"):
        window.setProperty("sceneName", scene)
        frames = []
        for frame in range(4):
            window.setProperty("sceneFrame", frame)
            settle(window, 180)
            frames.append(fingerprint(window))
        assert len(set(frames)) >= 3, f"{scene}: filmstrip crop is not playing"
        window.setProperty("sceneFrame", 0)
        settle(window)
        assert fingerprint(window) == frames[0], f"{scene}: nondeterministic loop"
        item = window.property("sceneItem")
        window.setProperty("animate", True)
        item.setProperty("frameDuration", 180)
        settle(window, 220)
        assert item.property("playing"), f"{scene}: playback did not start"
        window.setProperty("sceneActive", False)
        settle(window, 30)
        stopped = item.property("_frame")
        settle(window, 400)
        assert not item.property("playing") and stopped == item.property("_frame"), f"{scene}: hidden scene still ticking"
        window.setProperty("sceneActive", True)
        item.setProperty("motion", 0)
        settle(window, 30)
        assert not item.property("playing") and item.property("displayedFrame") == 0, f"{scene}: reduced motion is not still"
        item.setProperty("motion", 1)
        window.showMinimized()
        settle(window, 80)
        assert not item.property("playing"), f"{scene}: minimized scene still ticking"
        window.showNormal()
        window.setProperty("animate", False)
        print(f"PASS {scene}: cached frames, deterministic wrap, hidden, minimized, reduced motion")
    window.setProperty("sceneName", "coast")
    window.setProperty("sceneWeather", "thunder")
    settle(window)
    storm = fingerprint(window)
    window.setProperty("sceneLightning", True)
    settle(window)
    assert fingerprint(window) != storm, "Lightning preview did not render"
    window.setProperty("sceneLightning", False)
    window.setProperty("sceneWeather", "clear")
    window.setProperty("sceneDate", QDateTime.fromString("2026-09-10T14:00:00", "yyyy-MM-ddTHH:mm:ss"))
    settle(window)
    item = window.property("sceneItem")
    assert item.property("season") == "summer"
    for width, height in ((636, 556), (1176, 856), (1800, 900)):
        window.setWidth(width)
        window.setHeight(height)
        settle(window)
        assert fingerprint(window)
        assert item.property("pixelHeight") >= 270
    assert not warnings, "\n".join(warnings)
    print("PASS thunder, current season, three aspect ratios; no QML warnings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
