import QtQuick
import QtQuick.Layouts

Sheet {
    id: root
    title: "Voice & calls"
    subtitle: "Talk with Akira on this device"
    sheetWidth: 680
    property bool workBusy: false
    property string notice: ""
    property int permissionRevision: 0
    signal startRequested()
    signal showCallRequested()
    Connections { target: Permissions; function onGrantsChanged() { root.permissionRevision += 1; } }
    function granted(capability) {
        void root.permissionRevision;
        return Permissions.describe(capability).granted === true;
    }
    component Copy: Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        font: Theme.type.callout
        color: Theme.textSecondary
        wrapMode: Text.Wrap
    }
    ColumnLayout {
        width: parent.width
        spacing: 16
        Copy { visible: !Voice.available; text: Voice.unavailableReason; color: Theme.danger }
        SectionLabel { text: "Permissions" }
        Repeater {
            model: [{capability: "audio.record", title: "Microphone", description: "Allow Akira to listen when you start a call or recording."},
                    {capability: "audio.play", title: "Voice playback", description: "Allow spoken replies and voice samples."}]
            FormRow {
                id: access
                required property var modelData
                Layout.fillWidth: true
                title: modelData.title
                description: modelData.description
                ActionButton {
                    objectName: "voicePermission_" + access.modelData.capability
                    text: root.granted(access.modelData.capability) ? "Remove access" : "Allow"
                    onClicked: {
                        root.notice = "";
                        if (root.granted(access.modelData.capability)) Permissions.revoke(access.modelData.capability);
                        else root.notice = Permissions.grant(access.modelData.capability, []);
                    }
                }
            }
        }
        SectionLabel { text: "Voice" }
        Select {
            objectName: "voiceChoice"
            Layout.fillWidth: true
            label: "Voice"
            current: Voice.voice
            stackedDetails: true
            options: Voice.voices.map(function (v) { return {value: v.id, label: v.name, detail: v.description}; })
            onPicked: function (id) { Voice.setVoice(id); }
        }
        RowLayout {
            Layout.fillWidth: true
            Select {
                objectName: "voiceSpeed"
                Layout.fillWidth: true
                label: "Speaking speed"
                current: String(Voice.speed)
                options: [0.6, 0.8, 1, 1.2, 1.4, 1.6, Voice.speed].filter(function (x, i, all) { return all.indexOf(x) === i; }).sort(function (a, b) { return a - b; }).map(function (x) { return {value: String(x), label: x + "× speed"}; })
                onPicked: function (value) { Voice.setSpeed(Number(value)); }
            }
            ActionButton {
                objectName: "voicePreview"
                text: Voice.speaking ? "Stop playback" : "Hear sample"
                enabled: Voice.canSpeak && !Voice.inCall && !root.workBusy
                onClicked: { if (Voice.speaking) Voice.stopSpeaking(); else Voice.previewVoice(Voice.voice); }
            }
        }
        FormRow {
            Layout.fillWidth: true
            title: "Read chat replies aloud"
            description: "Also speak replies outside a call."
            Toggle { label: "Read chat replies aloud"; checked: Voice.readAloud; onToggled: function (on) { Voice.setReadAloud(on); } }
        }
        FormRow {
            Layout.fillWidth: true
            title: "Voice interruption · headphones"
            description: "For headphones. With speakers, leave this off and use the Interrupt button."
            Toggle { label: "Interrupt by speaking, for headphones"; checked: Voice.interruptByVoice; onToggled: function (on) { Voice.setInterruptByVoice(on); } }
        }
        Copy { visible: !!root.notice || !!Voice.note; text: root.notice || Voice.note; color: Theme.danger }
        Copy {
            visible: !Voice.inCall && (!!Voice.callBlocked || root.workBusy)
            text: Voice.callBlocked || "Finish the current chat or agent task before starting a call."
        }
        RowLayout {
            Layout.fillWidth: true
            ActionButton {
                objectName: "voiceStartCall"
                text: Voice.inCall ? "Show call" : "Start call"
                kind: "primary"
                enabled: Voice.inCall || (!Voice.callBlocked && !root.workBusy)
                onClicked: { if (Voice.inCall) root.showCallRequested(); else root.startRequested(); }
            }
        }
    }
}
