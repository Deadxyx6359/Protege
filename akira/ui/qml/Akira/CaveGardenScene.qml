import QtQuick

// A single garden painting. Light pools stay registered to the stone torches;
// no independent sprites, clocks, weather, or per-frame canvas drawing.
Item {
    id: root
    clip: true
    property bool active: true
    readonly property bool moving: visible && active && Theme.motionScale > 0
    readonly property bool ready: garden.status === Image.Ready

    Item {
        id: painting
        width: Math.max(root.width, root.height * 1.5)
        height: width / 1.5
        anchors.centerIn: parent

        Image {
            id: garden
            objectName: "caveGardenArtwork"
            anchors.fill: parent
            source: "../../assets/scenes/cave-garden-v1.png"
            sourceSize: Qt.size(768, 512)
            smooth: false
            mipmap: false
            asynchronous: true
        }

        Canvas {
            id: torchlight
            objectName: "caveTorchlight"
            anchors.fill: parent
            opacity: 0.15
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                // Normalized original-art coordinates, not window coordinates.
                var lamps = [[128,310,48], [310,537,48], [1255,403,45],
                             [1433,373,48], [1205,533,32], [1372,451,22]];
                for (var i = 0; i < lamps.length; ++i) {
                    var lamp = lamps[i];
                    var x = lamp[0] / 1536 * width;
                    var y = lamp[1] / 1024 * height;
                    var r = lamp[2] / 1536 * width;
                    var glow = ctx.createRadialGradient(x, y, 0, x, y, r);
                    glow.addColorStop(0, "#F04432");
                    glow.addColorStop(1, "transparent");
                    ctx.fillStyle = glow;
                    ctx.fillRect(x-r, y-r, r*2, r*2);
                }
            }
            SequentialAnimation on opacity {
                running: root.moving
                loops: Animation.Infinite
                NumberAnimation { from: 0.10; to: 0.26; duration: 1700; easing.type: Easing.InOutSine }
                NumberAnimation { from: 0.26; to: 0.16; duration: 1100; easing.type: Easing.InOutSine }
                NumberAnimation { from: 0.16; to: 0.22; duration: 1300; easing.type: Easing.InOutSine }
                NumberAnimation { from: 0.22; to: 0.10; duration: 2100; easing.type: Easing.InOutSine }
            }
        }
    }
}
