import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

Sheet {
    id: root
    title: "Content drafts"
    subtitle: "Review what Akira prepared before anything is published"
    sheetWidth: 760
    property string selectedId: ""
    property string savedText: ""
    property string notice: ""
    property string pendingId: ""
    property bool discardArmed: false
    readonly property var selected: Drafts.drafts.find(function (d) { return d.id === root.selectedId; }) || null
    readonly property bool dirty: editor.text !== root.savedText
    readonly property bool waiting: !!selected && selected.status === "waiting"
    signal permissionsRequested()

    function choose(id) {
        if (root.dirty) { root.notice = "Save your changes or reset them before opening another draft."; return; }
        root.selectedId = id;
        root.savedText = Drafts.text(id);
        editor.text = root.savedText;
        root.notice = "";
        root.discardArmed = false;
        root.scrollToTop();
    }
    Connections {
        target: Drafts
        function onStateChanged() {
            if (root.pendingId && !Drafts.publishing) {
                root.notice = Drafts.note;
                root.pendingId = "";
            }
        }
    }
    Timer { running: root.discardArmed; interval: 5000; onTriggered: root.discardArmed = false }
    component Copy: Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font: Theme.type.callout
        color: Theme.textSecondary
    }
    ColumnLayout {
        width: parent.width
        spacing: 16
        ColumnLayout {
            visible: !root.selectedId
            Layout.fillWidth: true
            spacing: 12
            Copy { text: Drafts.waitingCount + " pending" }
            SearchField { id: search; Layout.fillWidth: true; placeholder: "Find a draft or destination"; maximumLength: 200 }
            Select {
                id: filter
                Layout.fillWidth: true
                label: "Draft status"
                current: "waiting"
                options: [{value: "waiting", label: "Waiting for review"}, {value: "all", label: "All drafts"}]
                onPicked: function (value) { current = value; }
            }
            Repeater {
                id: draftList
                model: Drafts.drafts.filter(function (d) {
                    const query = search.text.trim().toLowerCase();
                    return (filter.current === "all" || d.status === "waiting") &&
                        (!query || (d.title + " " + d.job + " " + d.target).toLowerCase().indexOf(query) !== -1);
                })
                Rectangle {
                    id: row
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: rowContent.implicitHeight + 28
                    radius: Theme.radius.md
                    color: Theme.inset
                    border.color: Theme.separator
                    ColumnLayout {
                        id: rowContent
                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                        spacing: 7
                        Copy { text: row.modelData.title; font: Theme.type.headline; color: Theme.textPrimary }
                        Copy { text: row.modelData.job + " · " + row.modelData.status; font: Theme.type.caption }
                        Copy { text: row.modelData.target }
                        Copy { text: row.modelData.excerpt; maximumLineCount: 2; elide: Text.ElideRight }
                        ActionButton { objectName: "reviewDraft_" + row.modelData.id; text: row.modelData.status === "waiting" ? "Review draft" : "View draft"; onClicked: root.choose(row.modelData.id) }
                    }
                }
            }
            Copy { visible: draftList.count === 0; text: search.text ? "No matching drafts." : "No drafts" }
        }
        ColumnLayout {
            visible: !!root.selectedId
            Layout.fillWidth: true
            spacing: 14
            ActionButton {
                objectName: "draftBack"
                text: "All drafts"
                enabled: !Drafts.publishing
                onClicked: root.choose("")
            }
            Copy { text: root.selected ? root.selected.title : "This draft is no longer available."; font: Theme.type.title3; color: Theme.textPrimary }
            Copy { text: root.selected ? root.selected.brief : "" }
            SectionLabel { text: root.waiting ? "Draft · edit before publishing" : "Draft" }
            C.TextArea {
                id: editor
                objectName: "draftEditor"
                Layout.fillWidth: true
                Layout.minimumHeight: 170
                textFormat: TextEdit.PlainText
                wrapMode: TextEdit.Wrap
                selectByMouse: true
                readOnly: !root.waiting || !!Drafts.publishing
                font: Theme.type.body
                color: Theme.textPrimary
                selectionColor: Theme.accentSubtle
                selectedTextColor: Theme.textPrimary
                padding: 14
                Accessible.name: "Draft text"
                background: Rectangle { color: Theme.inset; radius: Theme.radius.sm; border.color: editor.activeFocus ? Theme.accent : Theme.separator }
            }
            Copy { visible: editor.length > 60000; text: "Keep the draft within 60,000 characters before saving or publishing."; color: Theme.danger }
            RowLayout {
                visible: root.waiting
                Layout.fillWidth: true
                ActionButton {
                    objectName: "draftSave"
                    text: "Save changes"
                    enabled: root.dirty && !!editor.text.trim() && editor.length <= 60000 && !Drafts.publishing
                    onClicked: { root.notice = Drafts.edit(root.selectedId, editor.text); if (!root.notice) { root.savedText = editor.text; root.notice = "Changes saved."; } }
                }
                ActionButton {
                    objectName: "draftReset"
                    text: "Reset edits"
                    enabled: root.dirty && !Drafts.publishing
                    onClicked: { editor.text = root.savedText; root.notice = ""; }
                }
                Copy { text: root.dirty ? "Unsaved changes" : "Saved"; font: Theme.type.caption }
            }
            SectionLabel { text: "Critic’s review of the first draft" }
            TextEdit {
                Layout.fillWidth: true
                text: root.selectedId ? (Drafts.review(root.selectedId) || "No review was recorded.") : ""
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                font: Theme.type.callout
                color: Theme.textSecondary
            }
            Rectangle {
                visible: !!root.selected
                Layout.fillWidth: true
                implicitHeight: publishContent.implicitHeight + 28
                radius: Theme.radius.md
                color: Theme.inset
                border.color: Theme.separator
                ColumnLayout {
                    id: publishContent
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                    spacing: 10
                    Copy { text: root.waiting ? "Publishing destination" : "Destination"; font: Theme.type.headline; color: Theme.textPrimary }
                    Copy { objectName: "draftTarget"; text: root.selected ? root.selected.target : ""; color: Theme.textPrimary; wrapMode: Text.WrapAnywhere }
                    ActionButton {
                        objectName: "draftPublish"
                        visible: root.waiting
                        text: Drafts.publishing === root.selectedId ? "Publishing…" : root.selected && root.selected.kind === "mail" ? "Publish · send email" : "Publish · create file"
                        kind: "primary"
                        enabled: !Drafts.publishing && !!editor.text.trim() && editor.length <= 60000
                        onClicked: {
                            root.pendingId = root.selectedId;
                            root.notice = Drafts.publish(root.selectedId, editor.text);
                            if (root.notice) root.pendingId = "";
                            else root.savedText = editor.text;
                        }
                    }
                    Copy { visible: !root.waiting; text: root.selected ? root.selected.status + " · " + root.selected.outcome : "" }
                }
            }
            ActionButton {
                objectName: "draftDiscard"
                visible: root.waiting
                enabled: !Drafts.publishing
                text: root.discardArmed ? "Confirm discard" : "Discard draft"
                kind: root.discardArmed ? "danger" : "secondary"
                onClicked: {
                    if (!root.discardArmed) { root.discardArmed = true; return; }
                    root.notice = Drafts.discard(root.selectedId);
                    if (!root.notice) { editor.text = root.savedText; root.choose(""); }
                }
            }
        }
        Copy { objectName: "draftNotice"; visible: !!root.notice; text: root.notice; color: Theme.textPrimary }
        ActionButton { visible: !!root.notice && root.waiting; text: "Review permissions"; onClicked: root.permissionsRequested() }
    }
}
