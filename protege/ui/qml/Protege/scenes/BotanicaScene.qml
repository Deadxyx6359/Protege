import QtQuick
import "world.js" as World
import "coast.js" as Coast

PixelScene {
    id: root
    property date now: new Date()
    property string weather: "clear"
    property bool southernHemisphere: false
    readonly property string season: World.season(now, southernHemisphere)
    readonly property string phase: World.phase(now)
    readonly property var conditions: World.conditions(World.normaliseWeather(weather))
    property bool lightningPreview: false
    property bool _lightning: false
    backgroundColor: World.mix(World.sky(World.dayFraction(now)).top, "#465762", conditions.gloom * 0.85)
    revision: [season, Math.floor(World.dayFraction(now) * 1440), weather, _lightning, lightningPreview]
    frameDuration: conditions.precip > 0.5 ? 300 : conditions.wind > 0.6 ? 520 : 1100
    paintFrame: function(ctx, frame) {
        Coast.paint(ctx, { season: root.season, fraction: World.dayFraction(root.now),
                          weather: root.weather, frame: frame,
                          lightning: root._lightning || root.lightningPreview });
    }
    // Infrequent distant lightning, not a repeated whole-screen strobe.
    Timer {
        interval: Math.max(30000, root.conditions.lightning * 4000)
        running: root.playing && root.conditions.lightning > 0
        repeat: true
        onTriggered: lightningPulse.restart()
    }
    SequentialAnimation {
        id: lightningPulse
        PropertyAction { target: root; property: "_lightning"; value: true }
        PauseAnimation { duration: 180 }
        PropertyAction { target: root; property: "_lightning"; value: false }
    }
    onPlayingChanged: {
        if (!playing) { lightningPulse.stop(); _lightning = false; }
    }
}
