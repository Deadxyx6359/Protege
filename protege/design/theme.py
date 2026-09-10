"""The appearance decision, and nothing else.

Which palette is active is a platform question — it depends on the OS
light/dark setting — so it belongs in Python. What the palettes actually
contain is a design question with exactly one consumer, so it lives in
``ui/qml/Protege/Theme.qml`` instead. This class is the seam between the two.

Reaches QML as the ``ThemeBridge`` context property; ``ThemeLink.qml`` copies
it into the ``Theme`` singleton.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication, Qt

VALID_MODES = ("auto", "dark", "light")


class ThemeController(QObject):
    """Owns appearance: which palette is live, and whether motion is damped."""

    modeChanged = Signal()
    """Emitted when the *preference* changes."""

    resolvedModeChanged = Signal()
    """Emitted when the *effective* appearance changes — including when the OS
    flips while the preference is still ``auto``."""

    reduceMotionChanged = Signal()

    def __init__(
        self,
        mode: str = "auto",
        reduce_motion: bool = False,
        on_change: Callable[[str, bool], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._mode = mode if mode in VALID_MODES else "auto"
        self._reduce_motion = reduce_motion
        self._on_change = on_change

        # Qt tracks the OS appearance and re-emits when the user flips Windows
        # between light and dark, so "auto" keeps working while the app is
        # open rather than only being read once at startup.
        hints = QGuiApplication.styleHints()
        if hints is not None:
            hints.colorSchemeChanged.connect(self._system_scheme_changed)

    # -- resolution ---------------------------------------------------------

    @staticmethod
    def _system_scheme() -> str:
        hints = QGuiApplication.styleHints()
        if hints is None:
            return "dark"
        # Unknown is a real answer on some platforms; dark is the app's default
        # so it is also the right fallback.
        return "light" if hints.colorScheme() == Qt.ColorScheme.Light else "dark"

    def _system_scheme_changed(self) -> None:
        if self._mode == "auto":
            self.resolvedModeChanged.emit()

    # -- properties ---------------------------------------------------------

    @Property(str, notify=resolvedModeChanged)
    def resolvedMode(self) -> str:
        """``"dark"`` or ``"light"`` — never ``"auto"``. What QML actually uses."""
        if self._mode in ("dark", "light"):
            return self._mode
        return self._system_scheme()

    def _get_mode(self) -> str:
        return self._mode

    def _set_mode(self, value: str) -> None:
        if value not in VALID_MODES or value == self._mode:
            return
        self._mode = value
        self.modeChanged.emit()
        self.resolvedModeChanged.emit()
        self._notify()

    mode = Property(str, _get_mode, _set_mode, notify=modeChanged)
    """``auto`` | ``dark`` | ``light`` — the user's preference, as chosen."""

    def _get_reduce_motion(self) -> bool:
        return self._reduce_motion

    def _set_reduce_motion(self, value: bool) -> None:
        if value == self._reduce_motion:
            return
        self._reduce_motion = value
        self.reduceMotionChanged.emit()
        self._notify()

    reduceMotion = Property(
        bool, _get_reduce_motion, _set_reduce_motion, notify=reduceMotionChanged
    )
    """When set, QML scales every duration to zero.

    Animation here is load-bearing — it is how the interface explains where
    things went — so this damps motion rather than removing the transitions
    themselves.
    """

    @Property(float, notify=reduceMotionChanged)
    def motionScale(self) -> float:
        """Multiplier every animation duration in QML is expressed against."""
        return 0.0 if self._reduce_motion else 1.0

    # -- convenience for QML ------------------------------------------------

    @Slot()
    def toggle(self) -> None:
        """Flip between light and dark, resolving ``auto`` to its opposite."""
        self._set_mode("light" if self.resolvedMode == "dark" else "dark")

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change(self._mode, self._reduce_motion)
