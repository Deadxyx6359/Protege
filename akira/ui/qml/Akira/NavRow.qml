import QtQuick

/*!
    One row in the sidebar.

    \qml
    NavRow { icon: "chat"; label: "Chats"; selected: true; onClicked: ... }
    \endqml

    Selection is a filled rounded rect, the way macOS sidebars do it, rather
    than a highlight that slides between rows. A sliding highlight looks good
    in a single flat list and falls apart across sections — and the rows here
    are grouped.
*/
Item {
    id: root

    required property string label

    /*! Icon name. Empty draws a colour dot instead — used for projects. */
    property string icon: ""

    /*! Fallback mark when \c icon is empty. */
    property color dotColor: Theme.accent

    property bool selected: false

    /*! Trailing text: a count, a shortcut, a timestamp. */
    property string detail: ""

    /*! Indents the row. Used for children of a project. */
    property int depth: 0

    readonly property bool hovered: hover.hovered

    signal clicked()

    implicitWidth: 200
    implicitHeight: 34
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: root.label
    Accessible.selected: root.selected
    Accessible.onPressAction: root.clicked()
    Keys.onReturnPressed: root.clicked()
    Keys.onEnterPressed: root.clicked()
    Keys.onSpacePressed: root.clicked()

    Rectangle {
        id: plate
        anchors.fill: parent
        radius: Theme.radius.sm
        color: root.selected ? Theme.accentSubtle
                             : (root.hovered ? Theme.surfaceHover : "transparent")
        border.width: root.activeFocus ? 2 : 0
        border.color: Theme.accent

        Behavior on color {
            ColorAnimation { duration: Theme.duration.fast }
        }
    }

    Row {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: Theme.space.sm + root.depth * Theme.space.md
        anchors.rightMargin: Theme.space.sm
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.space.sm

        Item {
            width: 20
            height: 20
            anchors.verticalCenter: parent.verticalCenter

            Icon {
                anchors.centerIn: parent
                visible: root.icon !== ""
                name: root.icon === "" ? "dot" : root.icon
                size: 18
                color: root.selected ? Theme.accent
                                     : (root.hovered ? Theme.textPrimary : Theme.textSecondary)
            }

            Rectangle {
                anchors.centerIn: parent
                visible: root.icon === ""
                width: 8
                height: 8
                radius: 4
                color: root.dotColor
            }
        }

        Text {
            width: parent.width - 20 - Theme.space.sm
                   - (detailText.visible ? detailText.width + Theme.space.sm : 0)
            anchors.verticalCenter: parent.verticalCenter
            text: root.label
            // Conversation titles and project names: never rich text.
            textFormat: Text.PlainText
            font: root.selected ? Theme.type.bodyStrong : Theme.type.body
            color: root.selected ? Theme.textPrimary
                                 : (root.hovered ? Theme.textPrimary : Theme.textSecondary)
            elide: Text.ElideRight

            Behavior on color {
                ColorAnimation { duration: Theme.duration.fast }
            }
        }

        Text {
            id: detailText
            anchors.verticalCenter: parent.verticalCenter
            visible: root.detail !== ""
            text: root.detail
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textTertiary
        }
    }

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }

    TapHandler {
        onTapped: { root.forceActiveFocus(); root.clicked() }
    }
}
