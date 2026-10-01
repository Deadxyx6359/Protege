import QtQuick

// One authored painting; all lighting stays registered to its architecture.
// No clock, weather, randomness, camera movement, or per-frame canvas repaint.
Item {
    id: root
    clip: true
    property bool active: true
    readonly property bool moving: visible && active && Theme.motionScale > 0
    readonly property bool ready: architecture.status === Image.Ready

    Item {
        id: painting
        width: Math.max(root.width, root.height * 1.5)
        height: width / 1.5
        anchors.centerIn: parent

        Image {
            id: architecture
            objectName: "megastructureArtwork"
            anchors.fill: parent
            source: "../../assets/scenes/megastructure-v1.png"
            // Decode to a fixed pixel grid, then keep its hard edges at any DPI.
            sourceSize: Qt.size(768, 512)
            smooth: false
            mipmap: false
            asynchronous: true
        }

        // A quiet, slow change in light deep inside the shaft. This texture is
        // painted once on resize; only its opacity is animated by the renderer.
        Canvas {
            id: mist
            anchors.fill: parent
            opacity: 0.10
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                var glow = ctx.createRadialGradient(width * .51, height * .63, 0,
                                                    width * .51, height * .63, width * .28);
                glow.addColorStop(0, "#F2F5DE");
                glow.addColorStop(1, "transparent");
                ctx.fillStyle = glow;
                ctx.fillRect(0, 0, width, height);
            }
            SequentialAnimation on opacity {
                running: root.moving
                loops: Animation.Infinite
                NumberAnimation { from: 0.06; to: 0.22; duration: 9000; easing.type: Easing.InOutSine }
                NumberAnimation { from: 0.22; to: 0.06; duration: 11000; easing.type: Easing.InOutSine }
            }
        }

        Item {
            id: beacons
            objectName: "megastructureBeacons"
            anchors.fill: parent
            opacity: 0.45
            // Coordinates are in the original 1536 x 1024 artwork. Resizing
            // and cropping transform the whole painting, never individual lights.
            Repeater {
                model: [{x: 474, y: 773, h: 8}, {x: 773, y: 833, h: 6},
                        {x: 1430, y: 551, h: 17}, {x: 72, y: 317, h: 14}]
                Rectangle {
                    required property var modelData
                    x: Math.round((modelData.x - 1) / 1536 * painting.width)
                    y: Math.round((modelData.y - modelData.h / 2) / 1024 * painting.height)
                    width: Math.max(1, Math.round(2 / 1536 * painting.width))
                    height: Math.max(2, Math.round(modelData.h / 1024 * painting.height))
                    color: "#FF6048"
                }
            }
            SequentialAnimation on opacity {
                running: root.moving
                loops: Animation.Infinite
                NumberAnimation { from: 0.15; to: 0.85; duration: 3100; easing.type: Easing.InOutSine }
                NumberAnimation { from: 0.85; to: 0.15; duration: 4700; easing.type: Easing.InOutSine }
            }
        }
    }
}
