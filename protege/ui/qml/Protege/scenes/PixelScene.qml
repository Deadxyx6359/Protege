import QtQuick
import QtQuick.Window

// Four completed paintings in one texture. Playback only changes the crop;
// terrain is never rebuilt and there are no individual sprite animations.
Item {
    id: root
    property real motion: 1
    property bool active: true
    property int frameOverride: -1
    property int frameDuration: 900
    property var paintFrame
    property var revision
    readonly property int pixelWidth: 480
    // Taller app panes gain sky above the painting instead of cropping away
    // both foreground trees (and the black hole in the coding view).
    readonly property int pixelHeight: Math.max(270, Math.round(480 * height / Math.max(1, width)))
    property color backgroundColor: "#060c18"
    property int _frame: 0
    readonly property int displayedFrame: frameOverride >= 0 ? frameOverride % 4 : (motion > 0 ? _frame : 0)
    readonly property bool playing: active && visible && opacity > 0 && motion > 0 && frameOverride < 0
        && (!Window.window || (Window.window.visibility !== Window.Minimized && Window.window.visibility !== Window.Hidden))
    clip: true

    onRevisionChanged: strip.requestPaint()
    onPaintFrameChanged: strip.requestPaint()
    onPixelHeightChanged: strip.requestPaint()
    onBackgroundColorChanged: strip.requestPaint()
    Timer {
        interval: Math.max(180, root.frameDuration / Math.max(0.01, root.motion))
        running: root.playing
        repeat: true
        onTriggered: root._frame = (root._frame + 1) % 4
    }
    Canvas {
        id: strip
        width: root.pixelWidth * 4
        height: root.pixelHeight
        antialiasing: false
        smooth: false
        canvasSize: Qt.size(width, height)
        renderTarget: Canvas.Image
        onPaint: {
            if (!root.paintFrame) return;
            var ctx = getContext("2d");
            ctx.reset();
            for (var f = 0; f < 4; f++) {
                ctx.save();
                ctx.translate(f * root.pixelWidth, 0);
                ctx.beginPath(); ctx.rect(0, 0, root.pixelWidth, root.pixelHeight); ctx.clip();
                ctx.fillStyle = root.backgroundColor;
                ctx.fillRect(0, 0, root.pixelWidth, root.pixelHeight);
                ctx.translate(0, root.pixelHeight - 270);
                root.paintFrame(ctx, f);
                ctx.restore();
            }
        }
    }
    ShaderEffectSource {
        readonly property real factor: Math.max(root.width / root.pixelWidth, root.height / root.pixelHeight)
        width: Math.ceil(root.pixelWidth * factor)
        height: Math.ceil(root.pixelHeight * factor)
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        sourceItem: strip
        sourceRect: Qt.rect(root.displayedFrame * root.pixelWidth, 0, root.pixelWidth, root.pixelHeight)
        textureSize: Qt.size(root.pixelWidth, root.pixelHeight)
        hideSource: true
        smooth: false
        live: true
    }
}
