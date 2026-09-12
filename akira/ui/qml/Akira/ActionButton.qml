import QtQuick

/*!
    A button with words on it.

    \qml
    ActionButton { text: "Allow"; kind: "primary"; onClicked: ... }
    \endqml

    Three kinds. \c primary is the one action a panel is for, \c danger takes
    something away, and \c secondary is everything else, including every "no".
    Focus is drawn as a ring, since a keyboard is how a careful person answers a
    question they were not expecting.
*/
Item {
    id: root

    property string text: ""
    /*! \c primary, \c secondary or \c danger. */
    property string kind: "secondary"
    property bool enabled: true

    readonly property bool hovered: hover.hovered && root.enabled
    readonly property bool pressed: tap.pressed && root.enabled

    signal clicked()

    implicitWidth: Math.max(88, label.implicitWidth + Theme.space.lg * 2)
    implicitHeight: 34
    opacity: enabled ? 1.0 : 0.4
    activeFocusOnTab: true

    Accessible.role: Accessible.Button
    Accessible.name: root.text

    function _press() { if (root.enabled) root.clicked() }
    Keys.onReturnPressed: root._press()
    Keys.onEnterPressed: root._press()
    Keys.onSpacePressed: root._press()

    readonly property color _fill: {
        if (root.kind === "primary")
            return root.pressed ? Theme.accentPressed : (root.hovered ? Theme.accentHover : Theme.accent);
        if (root.kind === "danger")
            return root.pressed || root.hovered ? Qt.darker(Theme.danger, 1.12) : Theme.danger;
        return root.pressed ? Theme.surfaceActive : (root.hovered ? Theme.surfaceHover : Theme.surface);
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius.sm
        color: root._fill
        border.width: root.activeFocus ? 2 : 1
        border.color: root.activeFocus ? Theme.accent
                    : (root.kind === "secondary" ? Theme.separatorStrong : "transparent")

        Behavior on color { ColorAnimation { duration: Theme.duration.fast } }
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        textFormat: Text.PlainText
        font: Theme.type.bodyStrong
        color: root.kind === "secondary" ? Theme.textPrimary : Theme.textOnAccent
    }

    HoverHandler { id: hover; enabled: root.enabled; cursorShape: Qt.PointingHandCursor }
    TapHandler {
        id: tap
        enabled: root.enabled
        onTapped: { root.forceActiveFocus(); root.clicked() }
    }
}
