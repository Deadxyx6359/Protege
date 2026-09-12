import QtQuick
import QtQuick.Layouts
import Akira

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
    title: "Akira"

    ThemeLink {}

    // -- sample state -------------------------------------------------------

    property string currentNav: "chats"
    property string currentProject: "thesis"
    readonly property string currentTab: ({ chats: "chat-1", code: "code-1", research: "research-1" })[currentNav] || ""
    property bool sidebarOpen: true

    function selectWorkspace(id) {
        const views = { "chat-1": "chats", "code-1": "code", "research-1": "research" };
        currentNav = views[id] || id;
    }

    // -- layout -------------------------------------------------------------

    // Declared before the layout but lifted above it: QML paints later
    // siblings on top, and a modal that renders under the window it is
    // modal over is not a modal.
    SettingsSheet {
        id: settingsSheet
        z: 10
        onPermissionsRequested: {
            settingsSheet.close();
            permissionsSheet.open();
        }
    }

    PermissionsSheet {
        id: permissionsSheet
        objectName: "permissionsSheet"
        z: 11
    }

    // Above everything, sheets included: an irreversible action waits on it.
    ConfirmDialog {
        objectName: "confirmDialog"
        z: 100
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Sidebar {
            id: sidebar
            objectName: "workspaceSidebar"
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
                { id: "research", icon: "search", label: "Research" },
                { id: "agents", icon: "team", label: "Agents" },
                { id: "documents", icon: "document", label: "Documents" },
                { id: "memory", icon: "clock", label: "Memory" }
            ]

            projectModel: [
                { id: "thesis", name: "Thesis", color: Theme.accent },
                { id: "akira", name: "Akira", color: Theme.success },
                { id: "coursework", name: "Coursework", color: Theme.warning }
            ]

            recentModel: Chat.recents

            onNavSelected: function (id) { win.selectWorkspace(id) }
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
                    objectName: "workspaceTabs"
                    anchors.fill: parent
                    currentId: win.currentTab
                    model: [
                        { id: "chat-1", title: "Everyday", icon: "chat", closable: false },
                        { id: "code-1", title: "Code", icon: "code", closable: false },
                        { id: "research-1", title: "Research", icon: "search", closable: false }
                    ]
                    onSelected: function (id) { win.selectWorkspace(id) }
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
                        objectName: "openPermissions"
                        icon: "shield"
                        iconSize: 17
                        onClicked: permissionsSheet.open()
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
                    objectName: "workspaceScene"
                    anchors.fill: parent
                    // Agents work in the coding world; their cards keep it quiet.
                    view: win.currentNav === "agents" ? "code" : win.currentNav
                    quiet: win.currentNav === "agents" || Chat.messages.count > 0
                    motion: ThemeBridge.motionScale
                }

                AgentsView {
                    objectName: "agentsView"
                    anchors.fill: parent
                    visible: win.currentNav === "agents"
                }

                ChatView {
                    visible: win.currentNav !== "research" && win.currentNav !== "agents"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: composer.top
                    model: Chat.messages
                    busy: Chat.busy
                    busyStage: Chat.stage
                    onScene: win.currentNav === "chats" || win.currentNav === "code"
                }

                ResearchView {
                    objectName: "researchView"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: composer.top
                    visible: win.currentNav === "research"
                    model: Chat.messages
                    busy: Chat.busy
                    busyStage: Chat.stage
                    onPromptSelected: function (prompt) {
                        // A starter prepares an editable draft; it never sends.
                        composer.text = composer.hasText ? composer.text + "\n\n" + prompt : prompt;
                        composer.focusInput();
                    }
                    onNewInquiryRequested: {
                        Chat.newChat();
                        composer.focusInput();
                    }
                }

                Composer {
                    id: composer
                    objectName: "workspaceComposer"
                    visible: win.currentNav !== "agents"
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: Theme.space.lg
                    width: Math.min(720, parent.width - Theme.space.xxl * 2)

                    busy: Chat.busy
                    placeholder: win.currentNav === "research" ? "What would you like to investigate?" : "Ask anything"
                    footnote: Chat.routeLabel

                    onSubmitted: function (text) { Chat.send(text) }
                    onStopped: Chat.stop()
                }
            }
        }
    }
}
