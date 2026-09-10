import QtQuick
import "orbit.js" as Orbit

PixelScene {
    frameDuration: 1400
    revision: "orbital-observatory-v1"
    paintFrame: function(ctx, frame) { Orbit.paint(ctx, frame); }
}
