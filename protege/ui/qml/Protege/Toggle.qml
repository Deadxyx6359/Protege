import QtQuick

/*!
    An on/off switch.

    The knob travels and the track fills at the same time, so the control reads
    as one movement rather than two independent changes.
*/
Item {
    id: root

    property bool checked: false
    signal toggled(bool value)

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

    HoverHandler { cursorShape: Qt.PointingHandCursor }
    TapHandler {
        onTapped: {
            root.checked = !root.checked;
            root.toggled(root.checked);
        }
    }
}
