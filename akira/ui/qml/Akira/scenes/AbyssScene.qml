import QtQuick
import "abyss.js" as Abyss

PixelScene {
    frameDuration: 1700
    backgroundColor: "#030d19"
    revision: "drowned-archive-v1"
    paintFrame: function(ctx, frame) { Abyss.paint(ctx, frame); }
}
