import QtQuick

/*!
    A square, icon-only control.

    \qml
    IconButton { icon: "settings"; onClicked: settings.open() }
    \endqml

    The press feedback is a small scale-down that springs back rather than a
    colour flash. It reads as the control physically yielding, which is what
    makes a pointer interface feel responsive at the moment of contact instead
    of only after the action completes.
*/
Item {
    id: root

    /*! Icon name from icons.js. */
    required property string icon

    /*! Hit area. Keep at or above 32 for anything a person aims at. */
    property real size: 32
    property real iconSize: 18

    property color color: Theme.textSecondary
    property color hoverColor: Theme.textPrimary

    /*! Draws no hover plate — for icons already sitting on a raised surface. */
    property bool flat: false

    property bool enabled: true

    readonly property bool hovered: hover.hovered && root.enabled
    readonly property bool pressed: tap.pressed && root.enabled

    signal clicked()

    implicitWidth: size
    implicitHeight: size
    opacity: enabled ? 1.0 : 0.35

    Behavior on opacity {
        NumberAnimation { duration: Theme.duration.fast }
    }

    scale: root.pressed ? 0.90 : 1.0
    Behavior on scale {
        NumberAnimation {
            duration: root.pressed ? Theme.duration.instant : Theme.duration.normal
            easing.type: Easing.Bezier
            // Springs on release, snaps on press: the yield should feel
            // immediate, the recovery should feel elastic.
            easing.bezierCurve: root.pressed ? Theme.easing.standard : Theme.easing.spring
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius.sm
        color: root.pressed ? Theme.surfaceActive : Theme.surfaceHover
        opacity: root.flat ? 0 : (root.hovered || root.pressed ? 1 : 0)

        Behavior on opacity {
            NumberAnimation { duration: Theme.duration.fast }
        }
        Behavior on color {
            ColorAnimation { duration: Theme.duration.instant }
        }
    }

    Icon {
        anchors.centerIn: parent
        name: root.icon
        size: root.iconSize
        color: root.hovered ? root.hoverColor : root.color
    }

    HoverHandler {
        id: hover
        enabled: root.enabled
        cursorShape: Qt.PointingHandCursor
    }

    TapHandler {
        id: tap
        enabled: root.enabled
        onTapped: root.clicked()
    }
}
