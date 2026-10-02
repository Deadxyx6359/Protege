import QtQuick
import QtQuick.Layouts

Sheet {
    id: root
    title: "Voice & calls"
    subtitle: "Talk with Akira on this device"
    sheetWidth: 680
    property alias workBusy: pane.workBusy
    signal startRequested()
    signal showCallRequested()

    VoicePane {
        id: pane
        width: parent.width
        onStartRequested: root.startRequested()
        onShowCallRequested: root.showCallRequested()
    }
}
