import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var run: ({})
    readonly property bool ownProject: (run.projectId || "") === Projects.currentId
    readonly property var artifacts: run.artifacts || []
    visible: artifacts.length > 0
    spacing: 12
    signal artifactRequested(var artifact)
    Text {
        Layout.fillWidth: true
        text: "Files changed by this task"
        font: Theme.type.headline
        color: Theme.textPrimary
    }
    Text {
        Layout.fillWidth: true
        text: root.ownProject ? "Open the current file. It may have changed since this run; reading it uses your current permissions."
                             : "Open this task’s original project to access its files."
        textFormat: Text.PlainText
        font: Theme.type.caption
        color: Theme.textSecondary
        wrapMode: Text.Wrap
    }
    Repeater {
        model: root.artifacts
        Rectangle {
            id: row
            required property var modelData
            required property int index
            Layout.fillWidth: true
            implicitHeight: 70
            radius: Theme.radius.sm
            color: Theme.surface
            border.color: Theme.separator
            RowLayout {
                anchors.fill: parent; anchors.margins: 12; spacing: 12
                Icon { name: "document"; size: 18; color: Theme.accent }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text { Layout.fillWidth: true; text: row.modelData.name; textFormat: Text.PlainText; font: Theme.type.callout; color: Theme.textPrimary; elide: Text.ElideRight }
                    Text { Layout.fillWidth: true; text: row.modelData.path; textFormat: Text.PlainText; font: Theme.type.caption; color: Theme.textSecondary; elide: Text.ElideMiddle }
                }
                ActionButton {
                    objectName: "runArtifact" + row.index
                    text: "Open"
                    enabled: root.ownProject
                    Accessible.name: "Open output file " + row.modelData.name
                    onClicked: root.artifactRequested(row.modelData)
                }
            }
        }
    }
}
