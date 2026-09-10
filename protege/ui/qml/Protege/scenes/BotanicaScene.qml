import QtQuick
// Explicit: a file in a module subdirectory does not implicitly see the
// module's own singletons the way one in the module root does.
import Protege
import "world.js" as World
import "terrain.js" as Terrain

/*!
    An 8-bit landscape that knows what time it is, what season it is, and what
    the weather is doing.

    Everything is drawn into a 320×180 buffer and scaled up with nearest-
    neighbour filtering, so the pixels are real pixels rather than a smooth
    picture of some. Anything drawn at final resolution and merely styled to
    look chunky gives itself away at the edges.

    Layout is deterministic — seeded from fixed integers, never from the clock
    or Math.random — because a landscape whose trees move when you reopen the
    window stops being a place.
*/
Item {
    id: root

    /*! Drives everything. Advanced by a timer; settable for previews. */
    property date now: new Date()

    /*! One of world.js WEATHER. Defaults to a sky that needs no network. */
    property string weather: "clear"

    property bool southernHemisphere: false

    /*! Scales all motion, so reduce-motion stills the landscape too. */
    property real motion: 1.0

    // -- derived ---------------------------------------------------------

    readonly property real _frac: World.dayFraction(now)
    readonly property string _season: World.season(now, southernHemisphere)
    readonly property var _pal: World.palette(_season)
    readonly property var _sky: World.sky(_frac)
    readonly property real _night: World.nightness(_frac)
    readonly property bool _wet: weather === "rain"
    readonly property bool _snowing: weather === "snow"

    /*  256×144 rather than 320×180: bigger pixels, and the sprites take up
        proportionally more of the frame. At 320 the trees read as shrubs.  */
    readonly property int pixelWidth: 256
    readonly property int pixelHeight: 144

    /*! Horizon, in virtual pixels. Low, so the sky carries the scene. */
    readonly property int _horizon: 94

    // -- the world, drawn small -------------------------------------------

    Item {
        id: world
        width: root.pixelWidth
        height: root.pixelHeight

        // ---- sky ----
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: root._sky.top }
                GradientStop { position: 1.0; color: root._sky.bottom }
            }
        }

        // ---- stars ----
        Item {
            anchors.fill: parent
            opacity: root._night

            Behavior on opacity {
                NumberAnimation { duration: 1200 }
            }

            Repeater {
                model: 46

                Rectangle {
                    required property int index
                    width: 1
                    height: 1
                    color: "#ffffff"
                    x: Math.floor(World.rand(index * 3 + 1) * root.pixelWidth)
                    y: Math.floor(World.rand(index * 7 + 5) * (root._horizon - 30))
                    opacity: 0.35 + World.rand(index * 11 + 3) * 0.65

                    SequentialAnimation on opacity {
                        running: root._night > 0.2 && root.motion > 0
                        loops: Animation.Infinite
                        NumberAnimation {
                            to: 0.2
                            duration: 900 + Math.floor(World.rand(index) * 2600)
                        }
                        NumberAnimation {
                            to: 1.0
                            duration: 900 + Math.floor(World.rand(index + 40) * 2600)
                        }
                    }
                }
            }
        }

        // ---- sun and moon ----
        //
        // Both ride the same arc; which one is up is decided by the hour. The
        // arc is deliberately shallow — a body that climbs to the top of the
        // frame reads as a lamp, not a sun.
        Item {
            id: sky
            anchors.fill: parent

            readonly property real _t: {
                var f = root._frac;
                // Day runs 0.26 → 0.82; night wraps around the other way.
                if (f >= 0.26 && f <= 0.82)
                    return (f - 0.26) / 0.56;
                var n = f > 0.82 ? f - 0.82 : f + 0.18;
                return n / 0.44;
            }
            readonly property bool _isDay: root._frac >= 0.26 && root._frac <= 0.82

            Rectangle {
                width: sky._isDay ? 11 : 9
                height: width
                radius: width / 2
                antialiasing: false
                color: sky._isDay ? "#ffe9a8" : "#e8eef6"
                x: Math.round(24 + sky._t * (root.pixelWidth - 48) - width / 2)
                y: Math.round(root._horizon - 26
                              - Math.sin(sky._t * Math.PI) * (root._horizon - 44))

                // A soft corona, drawn as a second larger disc rather than a
                // blur: a blur at this resolution smears across four pixels
                // and stops looking drawn.
                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width + 6
                    height: width
                    radius: width / 2
                    antialiasing: false
                    color: parent.color
                    opacity: 0.20
                    z: -1
                }
            }
        }

        // ---- clouds ----
        Repeater {
            model: World.cloudCount(root.weather)

            Item {
                id: cloud
                required property int index

                readonly property real _scale: 0.7 + World.rand(index * 5 + 2) * 0.9
                readonly property int _w: Math.round(26 * _scale)
                readonly property int _h: Math.round(7 * _scale)

                width: _w
                height: _h
                y: 12 + Math.floor(World.rand(index * 13 + 7) * 52)
                opacity: (root.weather === "overcast" ? 0.9 : 0.72)
                         * (1 - root._night * 0.45)

                Rectangle {
                    anchors.fill: parent
                    radius: parent.height / 2
                    antialiasing: false
                    color: root.weather === "overcast" || root._wet
                           ? "#9aa6b8" : "#f2f6fb"
                }
                Rectangle {
                    width: parent.width * 0.55
                    height: parent.height * 1.5
                    radius: height / 2
                    antialiasing: false
                    x: parent.width * 0.2
                    y: -parent.height * 0.45
                    color: root.weather === "overcast" || root._wet
                           ? "#9aa6b8" : "#f2f6fb"
                }

                /*  Drift, wrapping off one edge and back on the other, driven
                    by a phase plus a per-cloud offset rather than by the
                    animation's `from`. Same reason as the weather: a stilled
                    scene must still show clouds spread across the sky instead
                    of stacked at the left edge where they would start.  */
                property real phase: 0
                readonly property real _offset: World.rand(index * 19 + 3)

                x: ((phase + _offset) % 1.0) * (root.pixelWidth + _w) - _w

                NumberAnimation on phase {
                    running: root.motion > 0
                    loops: Animation.Infinite
                    from: 0
                    to: 1
                    duration: Math.round((70000 + World.rand(cloud.index * 17) * 90000)
                                         / Math.max(0.001, root.motion))
                }
            }
        }

        // ---- terrain ----
        //
        // Rectangles, not a Canvas. A Canvas rasterises at the device pixel
        // ratio and is then resampled into this scene's texture, which turns
        // every sprite pixel into an average of its neighbours — hard-edged
        // but muddy. Geometry goes straight into the scene graph at the
        // texture's own resolution. See terrain.js.
        Item {
            anchors.fill: parent

            readonly property var _built: Terrain.build(root.pixelWidth,
                                                        root.pixelHeight,
                                                        root._horizon,
                                                        root._season,
                                                        root._pal)

            // Cached to a texture: rebuilt when the season turns, not per
            // frame. Without this the whole landscape is re-batched behind
            // every drifting cloud.
            layer.enabled: true
            layer.smooth: false

            Repeater {
                model: parent._built.columns

                Rectangle {
                    required property var modelData
                    x: modelData.x
                    y: modelData.y
                    width: modelData.w !== undefined ? modelData.w : 1
                    height: modelData.h
                    color: modelData.c
                    antialiasing: false
                }
            }

            Repeater {
                model: parent._built.pixels

                Rectangle {
                    required property var modelData
                    x: modelData.x
                    y: modelData.y
                    width: 1
                    height: 1
                    color: modelData.c
                    antialiasing: false
                }
            }
        }

        // Night falls on the ground, not on the sky — the sky is already the
        // right colour, and dimming it twice turns dusk to mud.
        Rectangle {
            x: 0
            y: root._horizon - 34
            width: parent.width
            height: parent.height - y
            color: "#141a2e"
            opacity: root._night * 0.66

            Behavior on opacity {
                NumberAnimation { duration: 1600 }
            }
        }

        // ---- weather ----
        Repeater {
            model: root._wet ? 70 : (root._snowing ? 54 : 0)

            Rectangle {
                id: drop
                required property int index

                /*  Position comes from a phase plus a per-drop offset rather
                    than from an animation's `from`. A frozen frame — a preview,
                    or reduce-motion — then still shows weather spread down the
                    sky instead of a row of marks along the top edge.  */
                property real phase: 0
                readonly property real _offset: World.rand(index * 5 + 1)

                width: 1
                height: root._wet ? 3 : 1
                color: root._wet ? "#a8c6e8" : "#ffffff"
                opacity: root._wet ? 0.55 : 0.85

                x: Math.floor(World.rand(index * 3 + 2) * root.pixelWidth)
                   + (root._snowing ? Math.round(Math.sin((phase + _offset) * 6.283) * 4) : 0)
                y: ((phase + _offset) % 1.0) * (root.pixelHeight + 8) - 4

                NumberAnimation on phase {
                    running: root.motion > 0
                    loops: Animation.Infinite
                    from: 0
                    to: 1
                    duration: Math.round(
                        (root._wet ? 900 + World.rand(drop.index) * 500
                                   : 4200 + World.rand(drop.index) * 2600)
                        / Math.max(0.001, root.motion))
                }
            }
        }

        // Fog sits on the horizon rather than over everything, which is where
        // it actually is.
        Rectangle {
            visible: root.weather === "fog"
            x: 0
            y: root._horizon - 40
            width: parent.width
            height: 60
            opacity: 0.5
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#00c9d4e0" }
                GradientStop { position: 0.45; color: "#c9d4e0" }
                GradientStop { position: 1.0; color: "#00c9d4e0" }
            }
        }
    }

    // -- scaled up, unsmoothed -------------------------------------------

    /*  Cover, not stretch. Filling the item without preserving the aspect
        ratio turns the sun into an ellipse and the trees into topiary — the
        giveaway that it is a texture rather than a place. The overflow is
        cropped instead.  */
    clip: true

    ShaderEffectSource {
        readonly property real _scale: Math.max(root.width / root.pixelWidth,
                                                root.height / root.pixelHeight)

        width: Math.ceil(root.pixelWidth * _scale)
        height: Math.ceil(root.pixelHeight * _scale)
        x: Math.round((root.width - width) / 2)
        // Biased upward: when the frame is taller than 16:9 the sky is what
        // should be lost, not the ground the whole scene is standing on.
        y: Math.round((root.height - height) * 0.35)

        sourceItem: world
        textureSize: Qt.size(root.pixelWidth, root.pixelHeight)
        hideSource: true
        smooth: false
        live: true
    }
}
