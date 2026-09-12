import QtQuick

// The approved portrait, unchanged. Keep it at least 32px in the interface;
// below that its eyes and jewelry disappear. No extra ring or color overlay.
Item {
    id: root
    property int size: 32
    implicitWidth: size
    implicitHeight: size
    Accessible.role: Accessible.Graphic
    Accessible.name: "Akira"
    readonly property bool ready: portrait.status === Image.Ready

    Image {
        id: portrait
        anchors.fill: parent
        source: Qt.resolvedUrl("../../assets/akira-logo.png")
        // Bound decoding before the final display scale; sampling a 1024px
        // portrait directly at 32px loses its face on the software renderer.
        sourceSize: Qt.size(root.size * 2, root.size * 2)
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        Accessible.ignored: true
    }
}
