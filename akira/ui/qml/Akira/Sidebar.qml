import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

/*!
    The navigation rail.

    Deliberately shallow: a handful of destinations, your projects, and what
    you were last working on. Everything else is reachable from where it is
    used rather than from a list of every feature the application has — the
    old sidebar listed thirteen rows, which is a menu bar wearing a sidebar's
    clothes.

    Models arrive as plain arrays so this file has no idea where the data comes
    from; Python replaces them later without touching the layout.
*/
Item {
    id: root

    /*! [{ id, icon, label }] — the fixed destinations. */
    property var navModel: []
    /*! [{ id, name, color }] */
    property var projectModel: []
    /*! [{ id, title, when }] */
    property var recentModel: []

    property string currentNav: ""
    property string currentProject: ""
    property string currentRecent: ""

    signal navSelected(string id)
    signal projectSelected(string id)
    signal recentSelected(string id)
    signal newChatRequested()
    signal newProjectRequested()
    signal settingsRequested()
    signal collapseRequested()

    implicitWidth: 264

    Rectangle {
        anchors.fill: parent
        color: Theme.surface

        Behavior on color {
            ColorAnimation { duration: Theme.duration.slow }
        }
    }

    // A hairline rather than a border: the sidebar and the content area differ
    // in tone already, and a full-strength divider on top of that reads as two
    // applications side by side.
    Rectangle {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 1
        color: Theme.separator
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // -- brand ----------------------------------------------------------

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 64
            Layout.leftMargin: Theme.space.md
            Layout.rightMargin: Theme.space.sm
            spacing: Theme.space.sm

            BrandMark {
                size: 36
                Accessible.ignored: true // The adjacent wordmark supplies the name.
            }

            Text {
                Layout.fillWidth: true
                text: "Akira"
                font: Theme.type.title3
                color: Theme.textPrimary
            }

            IconButton {
                icon: "sidebar"
                label: "Hide sidebar"
                iconSize: 17
                onClicked: root.collapseRequested()
            }
        }

        // -- search ---------------------------------------------------------

        SearchField {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space.md
            Layout.rightMargin: Theme.space.md
            Layout.bottomMargin: Theme.space.sm
        }

        // -- new chat -------------------------------------------------------

        ActionButton {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space.sm
            Layout.rightMargin: Theme.space.sm
            Layout.preferredHeight: 36
            text: "New chat"
            icon: "plus"
            kind: "primary"
            onClicked: root.newChatRequested()
        }

        // -- scrolling body -------------------------------------------------

        C.ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.topMargin: Theme.space.md
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: root.width
                spacing: 0

                SectionLabel {
                    Layout.leftMargin: Theme.space.md
                    Layout.bottomMargin: Theme.space.xs
                    text: "Workspace"
                }

                Repeater {
                    model: root.navModel

                    NavRow {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.space.sm
                        Layout.rightMargin: Theme.space.sm
                        icon: modelData.icon
                        label: modelData.label
                        selected: root.currentNav === modelData.id
                        onClicked: root.navSelected(modelData.id)
                    }
                }

                SectionLabel {
                    Layout.leftMargin: Theme.space.md
                    Layout.topMargin: Theme.space.lg
                    Layout.bottomMargin: Theme.space.xs
                    text: "Projects"
                }

                Repeater {
                    model: root.projectModel

                    NavRow {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.space.sm
                        Layout.rightMargin: Theme.space.sm
                        label: modelData.name
                        dotColor: modelData.color
                        selected: root.currentProject === modelData.id
                        onClicked: root.projectSelected(modelData.id)
                    }
                }

                NavRow {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.space.sm
                    Layout.rightMargin: Theme.space.sm
                    icon: "plus"
                    label: "New project"
                    onClicked: root.newProjectRequested()
                }

                SectionLabel {
                    Layout.leftMargin: Theme.space.md
                    Layout.topMargin: Theme.space.lg
                    Layout.bottomMargin: Theme.space.xs
                    text: "Recent"
                    visible: root.recentModel.length > 0
                }

                Repeater {
                    model: root.recentModel

                    NavRow {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.space.sm
                        Layout.rightMargin: Theme.space.sm
                        icon: "chat"
                        label: modelData.title
                        detail: modelData.when
                        selected: root.currentRecent === modelData.id
                        onClicked: root.recentSelected(modelData.id)
                    }
                }

                Item { Layout.preferredHeight: Theme.space.lg }
            }
        }

        // -- footer ---------------------------------------------------------

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.separator
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            Layout.leftMargin: Theme.space.md
            Layout.rightMargin: Theme.space.sm
            spacing: Theme.space.sm

            Rectangle {
                Layout.preferredWidth: 26
                Layout.preferredHeight: 26
                radius: 13
                color: Theme.accentSubtle

                Icon {
                    anchors.centerIn: parent
                    name: "user"
                    size: 15
                    color: Theme.accent
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Text {
                    text: "Local"
                    font: Theme.type.captionStrong
                    color: Theme.textPrimary
                }
                Text {
                    text: "On this machine"
                    font: Theme.type.caption
                    color: Theme.textTertiary
                }
            }

            IconButton {
                icon: "settings"
                iconSize: 17
                onClicked: root.settingsRequested()
            }
        }
    }
}
