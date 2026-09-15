import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

Sheet {
    id: root
    property var artifact: ({})
    property string action: ""
    readonly property bool document: /\.(md|txt|docx|xlsx|pptx|pdf|doc|xls|ppt)$/i.test(artifact.path || "")
    title: artifact.name || "Task output"
    subtitle: "Current file on this device"
    sheetWidth: 850
    sheetMaxHeight: Math.round(parent.height * 0.9)
    signal permissionsRequested()
    function present(file) {
        artifact = file; action = "";
        // Merely opening a reference does not read or launch its file.
        open();
    }
    onOpenedChanged: if (!opened) {
        if (action === "preview") Documents.clearPreview();
        else if (action === "editor" && Coding.operation === "editor") Coding.cancel();
        action = "";
    }
    Connections { target: Projects; function onCurrentChanged() { if (root.opened) root.close(); } }
    ColumnLayout {
        width: parent.width
        spacing: 14
        Text {
            Layout.fillWidth: true
            text: root.artifact.path || ""
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textSecondary
            wrapMode: Text.WrapAnywhere
        }
        Text {
            Layout.fillWidth: true
            text: root.document ? "Preview the file as text, including document headings, cells or slide text."
                                : "Open this file in VS Code to inspect or continue working on it."
            textFormat: Text.PlainText
            font: Theme.type.callout
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            ActionButton {
                objectName: "artifactPreview"
                visible: root.document
                text: root.action === "preview" && Documents.busy ? "Reading…" : "Preview file"
                kind: "primary"
                enabled: !Documents.busy && !Coding.busy
                onClicked: { root.action = "preview"; Documents.previewFile(root.artifact.path); }
            }
            ActionButton {
                objectName: "artifactEditor"
                visible: !root.document
                text: root.action === "editor" && Coding.busy ? "Opening…" : "Open in VS Code"
                kind: "primary"
                enabled: !Coding.busy
                onClicked: { root.action = "editor"; Coding.openEditor(root.artifact.path); }
            }
            Item { Layout.fillWidth: true }
        }
        Text {
            objectName: "artifactFeedback"
            Layout.fillWidth: true
            text: root.action === "preview" ? Documents.error : root.action === "editor" ? Coding.error || Coding.notice : ""
            textFormat: Text.PlainText
            visible: !!text
            font: Theme.type.callout
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }
        ActionButton {
            visible: (root.action === "preview" && !!Documents.error) || (root.action === "editor" && !!Coding.error)
            text: "Review permissions"
            onClicked: root.permissionsRequested()
        }
        C.ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(160, root.sheetMaxHeight - 260)
            visible: root.action === "preview" && !!Documents.preview
            clip: true
            contentWidth: availableWidth
            C.TextArea {
                objectName: "artifactPreviewText"
                text: Documents.preview
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                font: Theme.type.body
                color: Theme.textPrimary
                background: null
                Accessible.name: "Current output file text"
            }
        }
    }
}
