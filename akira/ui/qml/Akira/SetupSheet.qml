import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts

/*!
    The permissions most people want first, on one screen.

    Shown once, the first time Akira opens with nothing allowed, and again from
    Settings. Each line says in plain words what it allows; a folder line is
    the folder the person picks and no other. Nothing is allowed until "Allow
    these" is pressed, and everything here can be changed on the permission
    screen later.
*/
Sheet {
    id: root
    objectName: "setupSheet"
    title: "Set up Akira"
    subtitle: "Choose access. Change it anytime in Settings → Permissions."
    sheetWidth: 640

    /*! What is ticked, and the folder picked: id → { on, folder }. */
    property var picked: ({})
    property string notice: ""
    readonly property int chosen: Object.keys(picked).filter(function (id) { return picked[id].on; }).length

    signal done()

    function reset() {
        var fresh = {};
        // What is granted already is shown as on, not offered again.
        Permissions.starter.forEach(function (c) { fresh[c.id] = { on: c.on && !c.held, folder: "" }; });
        picked = fresh;
        notice = "";
    }

    function set(id, on, folder) {
        var next = Object.assign({}, picked);
        next[id] = { on: on, folder: folder === undefined ? picked[id].folder : folder };
        picked = next;
    }

    function allow() {
        var choices = Object.keys(picked).filter(function (id) { return picked[id].on; })
            .map(function (id) { return { id: id, folder: picked[id].folder }; });
        var why = Permissions.applyStarter(choices);
        notice = why;
        if (why === "") { close(); done(); }
    }

    function later() {
        Permissions.markSetupOffered();
        close();
        done();
    }

    function localPath(url) {
        var text = url.toString();
        if (text.indexOf("file:///") === 0)
            text = text.substring(8);
        return decodeURIComponent(text);
    }

    onOpenedChanged: if (opened) reset()

    FolderDialog {
        id: folderPicker
        property string target: ""
        title: "Choose a folder"
        onAccepted: root.set(target, true, root.localPath(selectedFolder))
    }

    ColumnLayout {
        width: parent.width
        spacing: 0

        Repeater {
            model: Permissions.starter

            ColumnLayout {
                id: line
                required property var modelData
                readonly property var now: root.picked[modelData.id] || ({ on: false, folder: "" })
                Layout.fillWidth: true
                spacing: 0

                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: Theme.space.md
                    Layout.bottomMargin: Theme.space.md
                    spacing: Theme.space.md

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Text {
                            text: line.modelData.title
                            textFormat: Text.PlainText
                            font: Theme.type.bodyStrong
                            color: Theme.textPrimary
                        }
                        Text {
                            Layout.fillWidth: true
                            text: line.modelData.detail
                            textFormat: Text.PlainText
                            font: Theme.type.caption
                            color: Theme.textSecondary
                            wrapMode: Text.Wrap
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: line.now.folder !== ""
                            text: line.now.folder
                            textFormat: Text.PlainText
                            font: Theme.type.monoSmall
                            color: Theme.textSecondary
                            wrapMode: Text.WrapAnywhere
                        }
                    }

                    ActionButton {
                        objectName: "setupFolder_" + line.modelData.id
                        visible: line.modelData.folder
                        text: line.now.folder ? "Change…" : "Choose folder…"
                        onClicked: { folderPicker.target = line.modelData.id; folderPicker.open(); }
                    }

                    Text {
                        objectName: "setupHeld_" + line.modelData.id
                        visible: line.modelData.held
                        text: "On"
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: Theme.textSecondary
                    }

                    Toggle {
                        objectName: "setupChoice_" + line.modelData.id
                        // Ticked whether it was granted or not, "Look things up on the
                        // web" looked on when only half of it was.
                        visible: !line.modelData.held
                        label: line.modelData.title
                        // A folder line is allowed once there is a folder to allow.
                        enabled: !line.modelData.folder || line.now.folder !== ""
                        checked: line.now.on
                        onToggled: function (value) {
                            root.set(line.modelData.id, value);
                            checked = Qt.binding(function () { return line.now.on; });
                        }
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.separator }
            }
        }

        Text {
            objectName: "setupNotice"
            Layout.fillWidth: true
            Layout.topMargin: Theme.space.sm
            visible: root.notice !== ""
            text: root.notice
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.danger
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space.lg
            spacing: Theme.space.sm
            ActionButton { objectName: "setupLater"; text: "Not now"; onClicked: root.later() }
            Item { Layout.fillWidth: true }
            ActionButton {
                objectName: "setupAllow"
                text: root.chosen ? "Allow these" : "Allow nothing"
                kind: "primary"
                enabled: root.chosen > 0
                onClicked: root.allow()
            }
        }
    }
}
