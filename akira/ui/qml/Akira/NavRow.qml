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
    property string subtitle: ""
    property string detailDescription: ""
    property color detailColor: Theme.textTertiary

    /*! Indents the row. Used for children of a project. */
    property int depth: 0

    /*! A small icon before the detail: \c pin for a pinned chat. */
    property string mark: ""
    /*! What \c mark means, for a screen reader: "pinned". */
    property string markDescription: ""

    /*! Offers a menu: by right-click, press and hold, the Menu key or Shift+F10. */
    property bool hasMenu: false

    readonly property bool hovered: hover.hovered

    signal clicked()
    /*! Where the menu was asked for, in the row's coordinates. */
    signal menuRequested(real x, real y)

    implicitWidth: 200
    implicitHeight: root.subtitle ? 72 : 34
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: root.label + (root.markDescription ? ", " + root.markDescription : "") + (root.detail ? ", " + (root.detailDescription || root.detail) : "") + (root.subtitle ? ", " + root.subtitle : "")
    Accessible.selected: root.selected
    Accessible.onPressAction: root.clicked()
    Keys.onReturnPressed: root.clicked()
    Keys.onEnterPressed: root.clicked()
    Keys.onSpacePressed: root.clicked()
    Keys.onPressed: function (event) {
        if (root.hasMenu && (event.key === Qt.Key_Menu
                             || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier)))) {
            event.accepted = true;
            root.menuRequested(Theme.space.lg, root.height);
        }
    }

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

        Column {
            width: parent.width - 20 - Theme.space.sm
                   - (detailText.visible ? detailText.width + Theme.space.sm : 0)
                   - (markIcon.visible ? markIcon.width + Theme.space.sm : 0)
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            Text {
                width: parent.width
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
                width: parent.width
                visible: root.subtitle !== ""
                text: root.subtitle
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textSecondary
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }

        Icon {
            id: markIcon
            anchors.verticalCenter: parent.verticalCenter
            visible: root.mark !== ""
            name: root.mark || "dot"
            size: 13
            color: Theme.textTertiary
            Accessible.ignored: true
        }

        Text {
            id: detailText
            anchors.verticalCenter: parent.verticalCenter
            visible: root.detail !== ""
            text: root.detail
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: root.detailColor
        }
    }

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }

    TapHandler {
        onTapped: { root.forceActiveFocus(); root.clicked() }
    }

    TapHandler {
        enabled: root.hasMenu
        acceptedButtons: Qt.RightButton
        onTapped: function (point) {
            root.forceActiveFocus();
            root.menuRequested(point.position.x, point.position.y);
        }
    }

    TapHandler {
        enabled: root.hasMenu
        acceptedDevices: PointerDevice.TouchScreen
        onLongPressed: root.menuRequested(point.position.x, point.position.y)
    }
}
