import QtQuick
import QtQuick.Layouts

/*!
    Open workspaces, across the top of the content area.

    The active tab is filled with the *content* colour and the strip behind it
    with the *chrome* colour, so the tab reads as continuous with what it
    contains rather than as a button that happens to be highlighted. That one
    relationship is what makes tabs legible without a border around everything.
*/
Item {
    id: root

    /*! [{ id, title, icon, closable }] */
    property var model: []
    property string currentId: ""

    signal selected(string id)
    signal closed(string id)
    signal newTabRequested()

    implicitHeight: 44

    Rectangle {
        anchors.fill: parent
        color: Theme.surface

        Behavior on color {
            ColorAnimation { duration: Theme.duration.slow }
        }
    }

    Rectangle {
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: 1
        color: Theme.separator
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.space.sm
        anchors.rightMargin: Theme.space.sm
        anchors.topMargin: Theme.space.xs + 2
        spacing: Theme.space.xxs

        Repeater {
            model: root.model

            Item {
                id: tab
                required property var modelData

                readonly property bool active: root.currentId === modelData.id
                readonly property bool hovered: tabHover.hovered

                Layout.preferredWidth: Math.min(196, Math.max(120, label.implicitWidth + 74))
                Layout.fillHeight: true

                Rectangle {
                    anchors.fill: parent
                    anchors.bottomMargin: 0
                    // Only the top corners are rounded: the bottom edge has to
                    // meet the content area flush for the tab to read as
                    // attached to it.
                    radius: Theme.radius.sm
                    color: tab.active ? Theme.canvas
                                      : (tab.hovered ? Theme.surfaceHover : "transparent")

                    Behavior on color {
                        ColorAnimation { duration: Theme.duration.fast }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: parent.radius
                        color: parent.color
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space.sm + 2
                    anchors.rightMargin: Theme.space.xs
                    spacing: Theme.space.xs + 2

                    Icon {
                        name: tab.modelData.icon
                        size: 15
                        color: tab.active ? Theme.accent : Theme.textTertiary
                    }

                    Text {
                        id: label
                        Layout.fillWidth: true
                        text: tab.modelData.title
                        textFormat: Text.PlainText
                        font: tab.active ? Theme.type.captionStrong : Theme.type.caption
                        color: tab.active ? Theme.textPrimary : Theme.textSecondary
                        elide: Text.ElideRight

                        Behavior on color {
                            ColorAnimation { duration: Theme.duration.fast }
                        }
                    }

                    IconButton {
                        icon: "close"
                        size: 20
                        iconSize: 12
                        flat: true
                        // Revealing close only on hover or when active keeps a
                        // row of tabs from looking like a row of dismissals.
                        opacity: (tab.hovered || tab.active) && tab.modelData.closable ? 1 : 0
                        enabled: opacity > 0
                        onClicked: root.closed(tab.modelData.id)

                        Behavior on opacity {
                            NumberAnimation { duration: Theme.duration.fast }
                        }
                    }
                }

                HoverHandler { id: tabHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.selected(tab.modelData.id) }
            }
        }

        IconButton {
            Layout.alignment: Qt.AlignVCenter
            icon: "plus"
            size: 28
            iconSize: 15
            onClicked: root.newTabRequested()
        }

        Item { Layout.fillWidth: true }
    }
}
