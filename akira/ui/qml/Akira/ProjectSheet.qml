import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import QtQuick.Layouts

/*!
    A project: making one, or the one that is open.

    A project gathers conversations and the grants that belong together. Its
    folder is where its notes live, which tells agents where to look and grants
    nothing. What is allowed only in the project applies while it is open, on
    top of what is allowed everywhere; scheduled jobs never use it.

    Forgetting a project asks twice, and says what it does not touch: the notes.
*/
Sheet {
    id: root

    /*! "" while making a new project; otherwise the project shown. */
    property string projectId: ""
    readonly property var project: {
        var all = Projects.projects;
        for (var i = 0; i < all.length; i++)
            if (all[i].id === root.projectId)
                return all[i];
        return null;
    }
    readonly property bool isOpen: project !== null && Projects.currentId === root.projectId

    property string name: ""
    property string folder: ""
    property string notice: ""
    property bool armed: false
    property bool canSwitch: true

    title: project !== null ? project.name : "New project"
    subtitle: project === null ? "Conversations and permissions that belong together"
            : isOpen ? "Open now" : "Not open"
    sheetWidth: 600

    function openNew() {
        root.projectId = "";
        root.name = "";
        root.folder = "";
        root.notice = "";
        root.armed = false;
        root.open();
    }

    function manage(id) {
        root.projectId = id;
        root.name = root.project !== null ? root.project.name : "";
        root.folder = root.project !== null ? root.project.folder : "";
        root.notice = "";
        root.armed = false;
        root.open();
    }

    /*! Make the project and open it. Returns "" or why not. */
    function makeProject() {
        if (!root.canSwitch) return root.notice = "Finish or stop the current work before switching projects.";
        var why = Projects.create(root.name.trim(), root.folder);
        root.notice = why;
        if (why === "")
            root.close();
        return why;
    }

    function rename() {
        root.notice = Projects.rename(root.projectId, root.name.trim());
        return root.notice;
    }

    function chooseFolder(path) {
        if (root.projectId === "") {
            root.folder = path;
            return "";
        }
        root.notice = Projects.setFolder(root.projectId, path);
        if (root.notice === "")
            root.folder = path;
        return root.notice;
    }

    function revoke(capability) {
        root.notice = Projects.revoke(capability);
        return root.notice;
    }

    function leave() {
        if (!root.canSwitch) return root.notice = "Finish or stop the current work before switching projects.";
        var why = Projects.openProject("");
        root.notice = why;
        if (why === "")
            root.close();
        return why;
    }

    /*! The first press arms; the second forgets. */
    function forget() {
        if (!root.canSwitch) return root.notice = "Finish or stop the current work before changing projects.";
        if (!root.armed) {
            root.armed = true;
            return "";
        }
        root.armed = false;
        var why = Projects.remove(root.projectId);
        root.notice = why;
        if (why === "")
            root.close();
        return why;
    }

    Timer { running: root.armed; interval: 5000; onTriggered: root.armed = false }

    FolderDialog {
        id: folderPicker
        title: "Where the project's notes live"
        onAccepted: {
            var text = selectedFolder.toString();
            root.chooseFolder(decodeURIComponent(text.indexOf("file:///") === 0 ? text.substring(8) : text));
        }
    }

    component Field: Rectangle {
        id: field
        property string text: ""
        property alias placeholder: input.placeholderText
        signal edited(string value)
        signal accepted()
        radius: Theme.radius.sm
        color: Theme.inset
        border.width: 1
        border.color: input.activeFocus ? Theme.accent : Theme.separator
        implicitHeight: 32
        C.TextField {
            id: input
            anchors.fill: parent
            anchors.leftMargin: Theme.space.sm
            anchors.rightMargin: Theme.space.sm
            text: field.text
            font: Theme.type.callout
            color: Theme.textPrimary
            placeholderTextColor: Theme.textTertiary
            selectionColor: Theme.accentSubtle
            selectedTextColor: Theme.textPrimary
            selectByMouse: true
            background: null
            padding: 0
            verticalAlignment: TextInput.AlignVCenter
            onTextEdited: field.edited(text)
            onAccepted: field.accepted()
        }
    }

    // -- name and folder ----------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "Name" }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.sm
            Field {
                objectName: "projectName"
                Layout.fillWidth: true
                text: root.name
                placeholder: "Such as Thesis, or Kitchen renovation"
                onEdited: function (value) { root.name = value }
                onAccepted: {
                    if (root.projectId === "")
                        root.makeProject();
                    else
                        root.rename();
                }
            }
            ActionButton {
                visible: root.project !== null
                text: "Rename"
                enabled: root.project !== null && root.name.trim() !== "" && root.name.trim() !== root.project.name
                onClicked: root.rename()
            }
        }

        SectionLabel { text: "Notes folder" }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.sm
            ActionButton {
                text: root.folder === "" ? "Choose a folder…" : "Change folder…"
                onClicked: folderPicker.open()
            }
            Text {
                Layout.fillWidth: true
                text: root.folder === "" ? "None. It can be chosen later." : root.folder
                textFormat: Text.PlainText
                font: root.folder === "" ? Theme.type.caption : Theme.type.monoSmall
                color: Theme.textTertiary
                elide: Text.ElideMiddle
            }
        }
        Text {
            Layout.fillWidth: true
            text: "Where the project's notes live. It tells agents where to look; it allows nothing by itself."
            font: Theme.type.caption
            color: Theme.textTertiary
            wrapMode: Text.Wrap
        }
    }

    // -- what is allowed only here -------------------------------------------------

    ColumnLayout {
        width: parent.width
        visible: root.project !== null
        spacing: Theme.space.md

        SectionLabel { text: "Allowed only in this project" }
        Text {
            Layout.fillWidth: true
            text: "While it is open, agents started from the window may use these as well as what is allowed everywhere. Scheduled jobs never do."
            font: Theme.type.caption
            color: Theme.textTertiary
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            visible: !root.isOpen
            text: "Open the project to see and change what is allowed in it."
            font: Theme.type.callout
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            visible: root.isOpen && Projects.grants.length === 0
            text: "Nothing yet."
            font: Theme.type.callout
            color: Theme.textSecondary
        }
        Repeater {
            model: root.isOpen ? Projects.grants : []
            RowLayout {
                id: held
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.space.sm
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: Permissions.describe(held.modelData.id).title || held.modelData.id
                        textFormat: Text.PlainText
                        font: Theme.type.body
                        color: Theme.textPrimary
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: held.modelData.scopes.length > 0
                        text: held.modelData.scopes.join(", ")
                        textFormat: Text.PlainText
                        font: Theme.type.monoSmall
                        color: Theme.textTertiary
                        elide: Text.ElideMiddle
                    }
                }
                ActionButton {
                    text: "Take away"
                    onClicked: root.revoke(held.modelData.id)
                }
            }
        }
    }

    // -- the end -------------------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.sm

        Text {
            Layout.fillWidth: true
            visible: root.notice !== ""
            text: root.notice
            textFormat: Text.PlainText
            font: Theme.type.callout
            color: Theme.danger
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            visible: root.armed
            text: "This forgets the project and what is allowed only in it. Its notes are not touched. Press again to forget it."
            textFormat: Text.PlainText
            font: Theme.type.callout
            color: Theme.danger
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            visible: !root.canSwitch
            text: "Finish or stop the current work to switch, create or forget a project."
            font: Theme.type.caption
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.sm
            ActionButton {
                visible: root.project !== null
                text: root.armed ? "Forget it" : "Forget project"
                kind: "danger"
                enabled: root.canSwitch
                onClicked: root.forget()
            }
            Item { Layout.fillWidth: true }
            ActionButton {
                visible: root.isOpen
                text: "Leave project"
                enabled: root.canSwitch
                onClicked: root.leave()
            }
            ActionButton {
                visible: root.project !== null && !root.isOpen
                text: "Open it"
                enabled: root.canSwitch
                kind: "primary"
                onClicked: {
                    root.notice = Projects.openProject(root.projectId);
                    if (root.notice === "")
                        root.close();
                }
            }
            ActionButton {
                visible: root.project === null
                objectName: "projectCreate"
                text: "Create"
                kind: "primary"
                enabled: root.canSwitch && root.name.trim() !== ""
                onClicked: root.makeProject()
            }
        }
    }
}
