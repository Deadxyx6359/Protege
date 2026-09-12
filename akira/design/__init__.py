"""Akira's design system.

Only the *decision* lives here — which appearance is active, and whether
motion is damped. The values themselves (colour, type, spacing, radii, motion
curves) live in ``akira/ui/qml/Akira/Theme.qml``, because QML is their only
consumer and a value with one consumer belongs next to it.
"""

from .theme import ThemeController

__all__ = ["ThemeController"]
