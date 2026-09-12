"""QML engine construction.

One place builds the engine, so the application, the component gallery and the
tests all run against identical registrations. A component that renders in the
gallery but not in the app is almost always a divergence here.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from akira.design import ThemeController
from akira.security import qtguard

QML_ROOT = Path(__file__).parent / "qml"
"""Import root. ``Akira/qmldir`` sits directly beneath it, which is what
makes ``import Akira`` resolve."""


class QmlError(RuntimeError):
    """Raised when QML fails to load — always fatal, never worked around."""


def configure_application(app: QGuiApplication) -> None:
    """Apply the process-wide settings that must precede any window."""
    app.setApplicationName("Akira")
    app.setOrganizationName("Akira")
    # Named so Qt's own dialogs and the window manager agree on the app's
    # identity; without it the taskbar groups us under "python".
    app.setDesktopFileName("akira")


def build_engine(
    *,
    theme: ThemeController | None = None,
    context: dict[str, QObject] | None = None,
    parent: QObject | None = None,
) -> tuple[QQmlApplicationEngine, ThemeController]:
    """Create an engine with Akira's QML module and bridges registered.

    ``context`` names extra objects to expose to QML. Callers must keep their
    own reference to each: a context property does not take ownership, and an
    object garbage-collected out from under a live binding takes the process
    with it.

    Returns the engine and the theme controller, for the same reason.
    """
    # "Basic" is Quick Controls' unstyled substrate: no platform look, every
    # visual detail delegated to us. The default on Windows is the native
    # style, which both refuses to be restyled and — since it is built on
    # QtQuick.Controls.NativeStyle — fails to instantiate in a QGuiApplication
    # at all. Must precede the creation of any Controls type.
    QQuickStyle.setStyle("Basic")

    engine = QQmlApplicationEngine(parent)
    # Before anything loads. Qt fetches web addresses in QML with its own
    # sockets, out of sight of the network guard, so the engine is given an
    # access manager that refuses them all. See akira/security/qtguard.py.
    qtguard.shut(engine)
    engine.addImportPath(str(QML_ROOT))

    controller = theme if theme is not None else ThemeController()

    # A context property, deliberately, rather than a registered QML type.
    # PySide6 registers Python QObject subclasses against the plain QObject
    # metatype; that registration then shadows QML's built-in QtObject, and
    # every grouped property in the design system fails to load with
    # "Cannot assign object of type QtObject to property of type QObject*".
    #
    # Context properties are invisible inside QML singletons, so Theme cannot
    # read this directly — ThemeLink bridges the gap. See ThemeLink.qml.
    engine.rootContext().setContextProperty("ThemeBridge", controller)

    for name, obj in (context or {}).items():
        engine.rootContext().setContextProperty(name, obj)

    return engine, controller


def load(engine: QQmlApplicationEngine, qml_file: Path | str) -> QObject:
    """Load a root QML file, failing loudly and with the actual errors.

    ``QQmlApplicationEngine`` reports errors through the Qt logging category
    and then carries on with no root object, which presents as an application
    that starts and shows nothing. Worse, whether those messages reach the
    terminal depends on logging rules the app does not control.

    So the errors are collected from the ``warnings`` signal and put in the
    exception, where they cannot be filtered away.
    """
    path = Path(qml_file).resolve()
    if not path.is_file():
        raise QmlError(f"QML file not found: {path}")

    collected: list[str] = []

    def capture(errors) -> None:
        for error in errors:
            collected.append(error.toString())

    engine.warnings.connect(capture)
    try:
        engine.load(QUrl.fromLocalFile(str(path)))
    finally:
        engine.warnings.disconnect(capture)

    roots = engine.rootObjects()
    if not roots:
        detail = "\n".join(f"  {line}" for line in collected) or "  (no detail reported)"
        raise QmlError(f"QML failed to load: {path}\n{detail}")

    # Warnings that did not prevent loading still matter — an unresolved
    # binding renders as a silently missing element.
    for line in collected:
        print(f"QML warning: {line}", file=sys.stderr)

    return roots[0]
