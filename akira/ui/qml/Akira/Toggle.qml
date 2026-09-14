import QtQuick

/*!
    An on/off switch.

    The knob travels and the track fills at the same time, so the control reads
    as one movement rather than two independent changes.
*/
Item {
    id: root

    property bool checked: false
    property string label: "Toggle option"
    signal toggled(bool value)
    activeFocusOnTab: enabled
    Accessible.role: Accessible.CheckBox
    Accessible.name: label
    Accessible.checkable: true
    Accessible.checked: checked
    Accessible.onToggleAction: root.activate()
    opacity: enabled ? 1 : 0.45
    function activate() { if (enabled) root.toggled(!root.checked); }
    Keys.onSpacePressed: root.activate()
    Keys.onReturnPressed: root.activate()
    Keys.onEnterPressed: root.activate()

    implicitWidth: 42
    implicitHeight: 24

    Rectangle {
        id: track
        anchors.fill: parent
        radius: height / 2
        color: root.checked ? Theme.accent : Theme.surfaceActive

        Behavior on color {
            ColorAnimation { duration: Theme.duration.fast }
        }
    }

    Rectangle {
        id: knob
        width: parent.height - 6
        height: width
        radius: width / 2
        y: 3
        x: root.checked ? parent.width - width - 3 : 3
        color: "#FFFFFF"

        Behavior on x {
            NumberAnimation {
                duration: Theme.duration.normal
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easing.standard
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: -3
        radius: height / 2
        color: "transparent"
        border.color: Theme.accent
        border.width: 2
        visible: root.activeFocus
    }

    HoverHandler { cursorShape: Qt.PointingHandCursor }
    TapHandler {
        onTapped: root.activate()
    }
}
