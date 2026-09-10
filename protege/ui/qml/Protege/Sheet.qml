import QtQuick
import QtQuick.Controls as C

/*!
    A modal panel over the window.

    \qml
    Sheet {
        id: settings
        title: "Settings"
        SettingsPanel { }
    }
    \endqml

    Enters by scaling up slightly and settling, rather than fading in place.
    The movement is what tells you something arrived *on top of* the window
    instead of replacing it — a cross-fade at the same size reads as navigation,
    and navigation implies a back button this has no need for.
*/
Item {
    id: root

    property string title: ""
    property string subtitle: ""

    property int sheetWidth: 640
    property int sheetMaxHeight: Math.round(parent ? parent.height * 0.82 : 600)

    readonly property bool opened: _open

    default property alias content: body.data

    property bool _open: false

    anchors.fill: parent
    visible: opacity > 0
    opacity: _open ? 1 : 0
    // Nothing behind a closed sheet should be unclickable.
    enabled: _open

    Behavior on opacity {
        NumberAnimation { duration: Theme.duration.fast }
    }

    function open() { root._open = true; panel.forceActiveFocus(); }
    function close() { root._open = false; }

    // -- scrim --------------------------------------------------------------

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim

        // Swallows every click that misses the panel, both to dismiss and to
        // stop presses landing on the window underneath.
        TapHandler { onTapped: root.close() }
    }

    // -- panel --------------------------------------------------------------

    FocusScope {
        id: panel
        anchors.centerIn: parent
        width: Math.min(root.sheetWidth, root.width - Theme.space.xxl * 2)
        height: Math.min(root.sheetMaxHeight,
                         header.height + body.implicitHeight + Theme.space.xl)

        scale: root._open ? 1.0 : 0.96
        y: root._open ? 0 : Theme.space.lg

        Behavior on scale {
            NumberAnimation {
                duration: Theme.duration.normal
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easing.enter
            }
        }

        Keys.onEscapePressed: root.close()

        Squircle {
            anchors.fill: parent
            radius: Theme.radius.lg
            fillColor: Theme.overlay
            borderColor: Theme.separatorStrong
        }

        // Presses inside the panel must not reach the scrim behind it.
        TapHandler {}

        // -- header ---------------------------------------------------------

        Item {
            id: header
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: root.subtitle === "" ? 56 : 68

            Column {
                anchors.left: parent.left
                anchors.leftMargin: Theme.space.xl
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2

                Text {
                    text: root.title
                    font: Theme.type.title3
                    color: Theme.textPrimary
                }
                Text {
                    visible: root.subtitle !== ""
                    text: root.subtitle
                    font: Theme.type.caption
                    color: Theme.textTertiary
                }
            }

            IconButton {
                anchors.right: parent.right
                anchors.rightMargin: Theme.space.md
                anchors.verticalCenter: parent.verticalCenter
                icon: "close"
                iconSize: 16
                onClicked: root.close()
            }

            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: 1
                color: Theme.separator
            }
        }

        // -- content ----------------------------------------------------------

        C.ScrollView {
            anchors.top: header.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: Theme.space.xl
            anchors.topMargin: Theme.space.lg
            contentWidth: availableWidth
            clip: true

            Column {
                id: body
                width: parent.width
                spacing: Theme.space.xl
            }
        }
    }
}
