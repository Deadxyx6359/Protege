import QtQuick

/*!
    Connects the \c Theme singleton to Python.

    Instantiate once, near the root of a window:

    \qml
    ApplicationWindow {
        ThemeLink {}
        color: Theme.color
    }
    \endqml

    This exists because a QML singleton cannot see context properties — only
    ordinary components can — so the singleton cannot reach \c ThemeBridge on
    its own. Rather than registering the Python controller as a QML type
    (which collides with QML's built-in \c QtObject and breaks every grouped
    property in the design system), the wiring is inverted: an ordinary
    component reads the context property and writes into the singleton.

    Isolating it here means exactly one file in the QML tree knows Python is
    involved, and the design system stays loadable on its own.
*/
Item {
    visible: false
    width: 0
    height: 0

    Binding {
        target: Theme
        property: "mode"
        value: ThemeBridge.resolvedMode
    }

    Binding {
        target: Theme
        property: "motionScale"
        value: ThemeBridge.motionScale
    }
}
