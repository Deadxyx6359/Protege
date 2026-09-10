import QtQuick
import QtQuick.Layouts
import Protege

/*!
    The application window.

    The conversation is live: \c Chat is the Python bridge, and the transcript,
    busy state, model label and saved conversations all come from it. Projects
    are still a sample array — they are the next thing to be wired.
*/
Window {
    id: win

    width: 1440
    height: 900
    minimumWidth: 900
    minimumHeight: 600
    visible: true
    color: Theme.canvas
    title: "Protégé"

    ThemeLink {}

    // -- sample state -------------------------------------------------------

    property string currentNav: "chats"
    property string currentProject: "thesis"
    property string currentTab: "chat-1"
    property bool sidebarOpen: true

    // -- layout -------------------------------------------------------------

    // Declared before the layout but lifted above it: QML paints later
    // siblings on top, and a modal that renders under the window it is
    // modal over is not a modal.
    SettingsSheet {
        id: settingsSheet
        z: 10
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Sidebar {
            id: sidebar
            Layout.fillHeight: true
            Layout.preferredWidth: win.sidebarOpen ? 264 : 0
            visible: Layout.preferredWidth > 0
            clip: true

            Behavior on Layout.preferredWidth {
                NumberAnimation {
                    duration: Theme.duration.normal
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easing.standard
                }
            }

            currentNav: win.currentNav
            currentProject: win.currentProject
            currentRecent: Chat.conversationId

            navModel: [
                { id: "chats", icon: "chat", label: "Chats" },
                { id: "code", icon: "code", label: "Code" },
                { id: "documents", icon: "document", label: "Documents" },
                { id: "memory", icon: "clock", label: "Memory" }
            ]

            projectModel: [
                { id: "thesis", name: "Thesis", color: Theme.accent },
                { id: "protege", name: "Protégé", color: Theme.success },
                { id: "coursework", name: "Coursework", color: Theme.warning }
            ]

            recentModel: Chat.recents

            onNavSelected: function (id) { win.currentNav = id }
            onRecentSelected: function (id) { Chat.openConversation(id) }
            onProjectSelected: function (id) { win.currentProject = id }
            onCollapseRequested: win.sidebarOpen = false
            onNewChatRequested: Chat.newChat()
            onSettingsRequested: settingsSheet.open()
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // -- tabs -------------------------------------------------------

            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: 44

                TabStrip {
                    anchors.fill: parent
                    currentId: win.currentTab
                    model: [
                        { id: "chat-1", title: Chat.title, icon: "chat", closable: true },
                        { id: "code-1", title: "protege/ui", icon: "code", closable: true },
                        { id: "doc-1", title: "Q3-report.docx", icon: "document", closable: true }
                    ]
                    onSelected: function (id) { win.currentTab = id }
                }

                RowLayout {
                    anchors.right: parent.right
                    anchors.rightMargin: Theme.space.sm
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.space.xxs

                    IconButton {
                        visible: !win.sidebarOpen
                        icon: "sidebar"
                        iconSize: 17
                        onClicked: win.sidebarOpen = true
                    }

                    IconButton {
                        icon: Theme.isDark ? "sun" : "moon"
                        iconSize: 17
                        onClicked: ThemeBridge.toggle()
                    }

                    IconButton {
                        icon: "settings"
                        iconSize: 17
                        onClicked: settingsSheet.open()
                    }
                }
            }

            // -- content ----------------------------------------------------

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                // Behind everything: the world for whichever view this is.
                // It retreats to nothing the moment there is text to read.
                SceneHost {
                    anchors.fill: parent
                    view: win.currentNav
                    quiet: Chat.messages.count > 0
                    motion: ThemeBridge.motionScale
                }

                ChatView {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: composer.top
                    model: Chat.messages
                    busy: Chat.busy
                    busyStage: Chat.stage
                    onScene: win.currentNav === "chats" || win.currentNav === "code"
                }

                Composer {
                    id: composer
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: Theme.space.lg
                    width: Math.min(720, parent.width - Theme.space.xxl * 2)

                    busy: Chat.busy
                    footnote: Chat.routeLabel

                    onSubmitted: function (text) { Chat.send(text) }
                    onStopped: Chat.stop()
                }
            }
        }
    }
}
