import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

Sheet {
    id: root
    title: "Project review"
    subtitle: Projects.currentName || "Code workspace"
    sheetWidth: 1000
    sheetMaxHeight: Math.round(parent.height * 0.9)
    readonly property var project: Projects.projects.find(function (p) { return p.current; }) || ({})
    readonly property string folder: project.folder || ""
    property string reviewMode: "working"
    property bool showStatus: false
    signal permissionsRequested()

    function inspect() {
        if (root.folder) Coding.inspect(root.folder, root.reviewMode);
    }
    function present() {
        root.open();
        root.inspect();
    }
    onOpenedChanged: { if (!opened && Coding.operation === "review") Coding.cancel(); }

    ColumnLayout {
        width: parent.width
        spacing: 14
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Text {
                    Layout.fillWidth: true
                    objectName: "codeReviewSummary"
                    text: Coding.busy ? (Coding.operation === "editor" ? "Opening VS Code…" : "Reading repository…")
                        : Coding.checked ? (Coding.changes === 0 ? "Working tree is clean" : Coding.changes + " changed entr" + (Coding.changes === 1 ? "y" : "ies"))
                        : "Review your project"
                    textFormat: Text.PlainText
                    font: Theme.type.headline
                    color: Theme.textPrimary
                    wrapMode: Text.Wrap
                }
                Text {
                    Layout.fillWidth: true
                    text: root.folder
                    textFormat: Text.PlainText
                    font: Theme.type.caption
                    color: Theme.textSecondary
                    elide: Text.ElideMiddle
                }
            }
            IconButton {
                objectName: "codeReviewRefresh"
                icon: "refresh"; label: "Refresh repository review"
                enabled: !!root.folder && !Coding.busy
                onClicked: root.inspect()
            }
            ActionButton {
                text: "VS Code"
                enabled: !!root.folder && !Coding.busy
                Accessible.name: "Open project folder in VS Code"
                onClicked: Coding.openEditor(root.folder)
            }
        }
        Segmented {
            objectName: "codeReviewModes"
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            options: [{id: "working", label: "Working changes"}, {id: "staged", label: "Staged changes"}, {id: "history", label: "History"}]
            current: root.reviewMode
            enabled: !Coding.busy
            onSelected: function (id) { root.reviewMode = id; root.inspect(); }
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: "Read-only snapshot" + (Coding.checked ? " · " + Coding.checked : "")
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
            ActionButton {
                text: root.showStatus ? "Hide file status" : "File status"
                enabled: !!Coding.status
                onClicked: root.showStatus = !root.showStatus
            }
        }
        Text {
            Layout.fillWidth: true
            visible: root.reviewMode !== "history"
            text: "Patches show tracked files. File status includes untracked entries; folder counts may be grouped."
            font: Theme.type.caption
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }
        ColumnLayout {
            Layout.fillWidth: true
            visible: Coding.error !== ""
            Text {
                objectName: "codeReviewError"
                Layout.fillWidth: true
                text: Coding.error
                textFormat: Text.PlainText
                font: Theme.type.callout
                color: Theme.danger
                wrapMode: Text.Wrap
            }
            ActionButton { text: "Review permissions"; onClicked: root.permissionsRequested() }
        }
        Text {
            Layout.fillWidth: true
            visible: Coding.notice !== ""
            text: Coding.notice
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }
        CodeBlock {
            Layout.fillWidth: true
            visible: root.showStatus && Coding.status !== ""
            code: Coding.status
            lang: "text"
        }
        Squircle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(160, Math.min(440, root.sheetMaxHeight - 300))
            visible: Coding.preview !== "" || Coding.busy
            fillColor: Theme.inset
            borderColor: Theme.separator
            radius: Theme.radius.sm
            C.ScrollView {
                anchors.fill: parent
                anchors.margins: 10
                clip: true
                TextEdit {
                    objectName: "codeReviewText"
                    text: Coding.preview
                    readOnly: true
                    selectByMouse: true
                    activeFocusOnTab: true
                    Accessible.name: root.reviewMode === "history" ? "Recent Git history" : "Git patch preview"
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.NoWrap
                    font: Theme.type.mono
                    color: Theme.textPrimary
                    selectionColor: Theme.accentSubtle
                    selectedTextColor: Theme.textPrimary
                }
            }
        }
    }
}
