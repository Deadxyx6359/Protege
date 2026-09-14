import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property var model: null
    property bool busy: false
    property string busyStage: "Thinking"
    property var sources: []
    property string contextNote: ""
    readonly property var project: Projects.projects.find(function (p) { return p.current; }) || ({})
    readonly property string folder: project.folder || ""
    signal teamRequested()
    signal reviewRequested()
    signal projectRequested()

    RowLayout {
        id: toolbar
        anchors.top: parent.top
        anchors.topMargin: 14
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(900, parent.width - 40)
        height: 42
        spacing: 8
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 80
            spacing: 3
            Text {
                Layout.fillWidth: true
                text: root.folder ? "Project files" : "Connect a project folder"
                textFormat: Text.PlainText
                font: Theme.type.captionStrong
                color: Theme.textPrimary
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: root.folder || "For Git review and VS Code"
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textSecondary
                elide: Text.ElideMiddle
            }
        }
        ActionButton {
            objectName: "codeProjectSetup"
            visible: !root.folder
            text: root.project.id ? "Set folder" : "Create project"
            onClicked: root.projectRequested()
        }
        ActionButton {
            objectName: "codeReviewButton"
            visible: !!root.folder
            enabled: !Coding.busy
            text: "Review changes"
            onClicked: root.reviewRequested()
        }
        ActionButton {
            objectName: "codeEditorButton"
            visible: !!root.folder
            text: Coding.busy && Coding.operation === "editor" ? "Opening…" : "VS Code"
            enabled: !Coding.busy
            Accessible.name: "Open project folder in VS Code"
            onClicked: Coding.openEditor(root.folder)
        }
        IconButton {
            visible: root.model && root.model.count > 0
            icon: "team"
            label: "Work with the software team"
            enabled: !root.busy && !Agents.busy
            onClicked: root.teamRequested()
        }
    }

    Text {
        id: feedback
        objectName: "codeFeedback"
        anchors.top: toolbar.bottom
        anchors.topMargin: 5
        anchors.horizontalCenter: parent.horizontalCenter
        width: toolbar.width
        visible: text !== ""
        text: Coding.error || Coding.notice
        textFormat: Text.PlainText
        font: Theme.type.caption
        color: Coding.error ? Theme.danger : Theme.textSecondary
        wrapMode: Text.Wrap
        maximumLineCount: 3
        elide: Text.ElideRight
    }

    ChatView {
        anchors.top: feedback.visible ? feedback.bottom : toolbar.bottom
        anchors.topMargin: 10
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        model: root.model
        busy: root.busy
        busyStage: root.busyStage
        sources: root.sources
        contextNote: root.contextNote
        onScene: true
        greetingTitle: "Make something useful."
        greetingSubtitle: "Plan here. Build with the software team."
        actionLabel: "Work with the software team"
        onPrimaryActionRequested: root.teamRequested()
    }
}
