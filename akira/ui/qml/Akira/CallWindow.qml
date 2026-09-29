import QtQuick
import QtQuick.Layouts

Window {
    id: root
    title: "Akira · Voice call"
    width: 370; height: 280
    minimumWidth: 370; minimumHeight: 280
    maximumWidth: 370; maximumHeight: 280
    transientParent: null
    flags: Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
    color: Theme.canvas
    visible: Voice.inCall
    signal endRequested()
    signal returnRequested()
    property int elapsed: 0
    readonly property string stateLabel: Voice.muted ? "Microphone muted" : ({listening: "Listening", hearing: "Hearing you", thinking: "Thinking", speaking: "Speaking", muted: "Microphone muted"})[Voice.callState] || "Connecting"
    onClosing: function (close) { close.accepted = false; root.endRequested(); }
    // The microphone is never open behind a window nobody can see: hidden by
    // anything but the call ending, the call ends.
    onVisibleChanged: if (!visible && Voice.inCall) root.endRequested()
    Connections { target: Voice; function onCallChanged() { if (!Voice.inCall) root.elapsed = 0; } }
    Timer { interval: 1000; repeat: true; running: Voice.inCall; onTriggered: root.elapsed += 1 }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 14
        RowLayout {
            Layout.fillWidth: true
            BrandMark { size: 44 }
            ColumnLayout {
                Layout.fillWidth: true
                Text { text: "Akira"; font: Theme.type.headline; color: Theme.textPrimary }
                Text { text: "Call active · " + Math.floor(root.elapsed / 60) + ":" + String(root.elapsed % 60).padStart(2, "0"); textFormat: Text.PlainText; font: Theme.type.caption; color: Theme.textSecondary }
            }
            ActionButton { objectName: "callReturn"; text: "Open chat"; onClicked: root.returnRequested() }
        }
        Text {
            objectName: "callStateLabel"
            Layout.fillWidth: true
            text: root.stateLabel
            textFormat: Text.PlainText
            font: Theme.type.title2
            color: Voice.muted ? Theme.danger : Theme.textPrimary
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 6
            radius: 3
            color: Theme.inset
            Rectangle { width: parent.width * (Voice.muted ? 0 : Math.max(0, Math.min(1, Voice.level))); height: parent.height; radius: 3; color: Theme.accent }
            Accessible.role: Accessible.ProgressBar
            Accessible.name: "Microphone level"
        }
        Item { Layout.fillHeight: true }
        RowLayout {
            Layout.fillWidth: true
            ActionButton { objectName: "callMute"; Layout.fillWidth: true; text: Voice.muted ? "Unmute" : "Mute mic"; onClicked: Voice.setMuted(!Voice.muted) }
            ActionButton { objectName: "callInterrupt"; Layout.fillWidth: true; text: "Interrupt"; enabled: Voice.speaking || Chat.busy; onClicked: { Voice.stopSpeaking(); Chat.stop(); } }
        }
        ActionButton { objectName: "callEnd"; Layout.fillWidth: true; text: "End call"; kind: "danger"; onClicked: root.endRequested() }
    }
}
