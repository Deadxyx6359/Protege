import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import QtQuick.Layouts

Sheet {
    id: root
    title: "Create a picture"
    subtitle: "Made locally on your graphics card"
    sheetWidth: 820
    property string notice: ""
    property bool saved: false
    readonly property bool working: !!Images.busy
    readonly property bool blocked: Chat.busy || Agents.busy || Voice.inCall || Training.running
    function saveTo(url) {
        const why = Images.save(url);
        root.notice = why || "Picture saved.";
        if (!why) root.saved = true;
    }
    Connections { target: Images; function onPictureChanged() { root.saved = false; } }
    FileDialog {
        id: saveDialog
        objectName: "pictureSaveDialog"
        title: "Save picture"
        fileMode: FileDialog.SaveFile
        nameFilters: ["PNG image (*.png)"]
        defaultSuffix: "png"
        onAccepted: root.saveTo(selectedFile.toString())
    }
    component Copy: Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font: Theme.type.callout
        color: Theme.textSecondary
    }
    ColumnLayout {
        width: parent.width
        spacing: 14
        C.TextArea {
            id: prompt
            objectName: "picturePrompt"
            Layout.fillWidth: true
            Layout.minimumHeight: 110
            placeholderText: "Describe a picture…"
            textFormat: TextEdit.PlainText
            wrapMode: TextEdit.Wrap
            selectByMouse: true
            readOnly: root.working
            font: Theme.type.body
            color: Theme.textPrimary
            placeholderTextColor: Theme.textTertiary
            selectionColor: Theme.accentSubtle
            selectedTextColor: Theme.textPrimary
            padding: 14
            Accessible.name: "Picture description"
            background: Rectangle { radius: Theme.radius.sm; color: Theme.inset; border.color: prompt.activeFocus ? Theme.accent : Theme.separator }
        }
        Copy { visible: prompt.length > 1000; text: "Keep the description within 1,000 characters."; color: Theme.danger }
        RowLayout {
            Layout.fillWidth: true
            Select {
                id: shape
                objectName: "pictureShape"
                Layout.fillWidth: true
                label: "Image shape"
                current: "square"
                enabled: !root.working
                options: [{value: "square", label: "Square · 512 × 512"}, {value: "portrait", label: "Portrait · 512 × 768"}, {value: "landscape", label: "Landscape · 768 × 512"}]
                onPicked: function (value) { current = value; }
            }
            Select {
                id: steps
                Layout.fillWidth: true
                label: "Generation steps"
                current: "4"
                enabled: !root.working
                options: [{value: "2", label: "Quick · 2 steps"}, {value: "4", label: "Standard · 4 steps"}]
                onPicked: function (value) { current = value; }
            }
        }
        Copy { visible: !Images.available; text: Images.unavailableReason; color: Theme.danger }
        Copy { visible: root.blocked; text: Training.running ? "Finish or stop model training before making a picture." : "Finish the current reply, agent task or call before making a picture." }
        RowLayout {
            Layout.fillWidth: true
            ActionButton {
                objectName: "pictureMake"
                text: Images.busy === "preparing" ? "Preparing model…" : root.working ? "Making picture…" : Images.picture ? "Make another" : "Make picture"
                kind: "primary"
                enabled: Images.available && !root.working && !root.blocked && !saveDialog.visible && !!prompt.text.trim() && prompt.length <= 1000
                onClicked: {
                    root.notice = Images.make(prompt.text, "", shape.current === "landscape" ? 768 : 512,
                                              shape.current === "portrait" ? 768 : 512, Number(steps.current), -1);
                }
            }
            C.BusyIndicator { running: root.working; visible: root.working; implicitWidth: 28; implicitHeight: 28; Accessible.name: "Image generation in progress" }
        }
        Copy { objectName: "pictureNotice"; visible: !!root.notice || !!Images.note; text: root.notice || Images.note }
        ColumnLayout {
            visible: !!Images.picture
            Layout.fillWidth: true
            spacing: 12
            SectionLabel { text: root.working ? "Previous picture" : "Your picture" }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: Math.min(360, width)
                radius: Theme.radius.md
                color: Theme.inset
                border.color: Theme.separator
                Image {
                    objectName: "generatedPicture"
                    anchors.fill: parent
                    anchors.margins: 10
                    source: Images.picture
                    fillMode: Image.PreserveAspectFit
                    Accessible.role: Accessible.Graphic
                    Accessible.name: "Generated picture: " + (Images.details.prompt || "")
                }
            }
            RowLayout {
                Layout.fillWidth: true
                ActionButton { objectName: "pictureSave"; text: "Save PNG…"; kind: "primary"; enabled: !root.working; onClicked: saveDialog.open() }
            }
        }
    }
}
