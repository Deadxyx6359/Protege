import QtQuick
// Explicit: a file in a module subdirectory does not implicitly see the
// module's own singletons the way one in the module root does.
import Protege
import "world.js" as World
import "terrain.js" as Terrain
import "sprites.js" as Sprites

/*!
    An 8-bit landscape that knows what time it is, what season it is, and what
    the weather is actually doing.

    Everything is drawn into a 384×216 buffer and scaled up with nearest-
    neighbour filtering, so the pixels are real pixels rather than a smooth
    picture of some.

    The static half — mountains, forest, river, meadow, seasonal props — is
    built by terrain.js and cached. The moving half lives here: clouds, the sun
    and moon, weather, and the foreground trees, which lean and spring back
    with the wind because they are the only things near enough for it to show
    on.
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
    readonly property var _wx: World.conditions(weather)

    readonly property int pixelWidth: 384
    readonly property int pixelHeight: 216

    /*  Where the meadow starts. terrain.js derives the same value; kept in
        step here so the weather and props know where the ground is.  */
    readonly property int _meadowTop: Math.round(pixelHeight * 0.66)

    /*! Live wind, 0..1 — the steady lean plus the current gust. */
    property real gust: 0
    readonly property real _wind: Math.min(1.4, _wx.wind + gust * _wx.gust)

    clip: true

    // -- gusting ---------------------------------------------------------

    /*  Wind is not a constant. Two out-of-phase oscillators give a lean that
        wanders instead of a metronome, which is the difference between trees
        moving and trees waving.  */
    SequentialAnimation on gust {
        running: root.motion > 0 && root._wx.wind > 0.12
        loops: Animation.Infinite
        NumberAnimation {
            to: 1.0
            duration: Math.round(2600 / Math.max(0.001, root.motion))
            easing.type: Easing.InOutSine
        }
        NumberAnimation {
            to: 0.15
            duration: Math.round(4100 / Math.max(0.001, root.motion))
            easing.type: Easing.InOutSine
        }
        NumberAnimation {
            to: 0.62
            duration: Math.round(1900 / Math.max(0.001, root.motion))
            easing.type: Easing.InOutSine
        }
        NumberAnimation {
            to: 0.05
            duration: Math.round(5200 / Math.max(0.001, root.motion))
            easing.type: Easing.InOutSine
        }
    }

    // -- the world, drawn small ------------------------------------------

    Item {
        id: world
        width: root.pixelWidth
        height: root.pixelHeight

        // ---- sky ----
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.00; color: root._sky.top }
                GradientStop { position: 0.48; color: root._sky.mid }
                GradientStop { position: 0.78; color: root._sky.bottom }
            }
        }

        // ---- stars ----
        Item {
            anchors.fill: parent
            opacity: root._night * (1 - root._wx.gloom)

            Behavior on opacity { NumberAnimation { duration: 1200 } }

            Repeater {
                model: 70

                Rectangle {
                    required property int index
                    width: 1
                    height: 1
                    color: "#ffffff"
                    x: Math.floor(World.rand(index * 3 + 1) * root.pixelWidth)
                    y: Math.floor(World.rand(index * 7 + 5) * (root.pixelHeight * 0.42))
                    opacity: 0.3 + World.rand(index * 11 + 3) * 0.7
                    antialiasing: false

                    SequentialAnimation on opacity {
                        running: root._night > 0.2 && root.motion > 0
                        loops: Animation.Infinite
                        NumberAnimation {
                            to: 0.18
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
        Item {
            id: sky
            anchors.fill: parent

            readonly property real _t: {
                var f = root._frac;
                if (f >= 0.24 && f <= 0.82)
                    return (f - 0.24) / 0.58;
                var n = f > 0.82 ? f - 0.82 : f + 0.18;
                return n / 0.42;
            }
            readonly property bool _isDay: root._frac >= 0.24 && root._frac <= 0.82

            // Hidden behind a heavy deck rather than shining through it.
            opacity: 1 - root._wx.gloom * 1.35

            Rectangle {
                width: sky._isDay ? 13 : 11
                height: width
                radius: width / 2
                antialiasing: false
                color: sky._isDay ? "#ffe9a8" : "#e8eef6"
                x: Math.round(30 + sky._t * (root.pixelWidth - 60) - width / 2)
                y: Math.round(root._meadowTop - 30
                              - Math.sin(sky._t * Math.PI) * (root._meadowTop - 52))

                // A corona drawn as a second larger disc rather than a blur: a
                // blur at this resolution smears across four pixels and stops
                // looking drawn.
                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width + 8
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
        //
        // Built from overlapping discs in three tones — lit top, body, shaded
        // underside — rather than one flat shape. A cloud with no underside is
        // a blob; the shading is what makes it sit *in* the sky.
        Repeater {
            model: root._wx.cover

            Item {
                id: cloud
                required property int index

                readonly property real _scale: 0.65 + World.rand(index * 5 + 2) * 1.15
                readonly property int _w: Math.round(46 * _scale)
                readonly property int _h: Math.round(13 * _scale)
                readonly property bool _heavy: root._wx.gloom > 0.3

                width: _w
                height: _h
                y: 8 + Math.floor(World.rand(index * 13 + 7) * (root.pixelHeight * 0.36))
                opacity: (0.62 + root._wx.gloom * 0.38) * (1 - root._night * 0.4)

                // Phase plus a per-cloud offset rather than the animation's
                // `from`, so a stilled scene still shows clouds spread across
                // the sky instead of stacked where they would start.
                property real phase: 0
                readonly property real _offset: World.rand(index * 19 + 3)
                x: ((phase + _offset) % 1.0) * (root.pixelWidth + _w) - _w

                NumberAnimation on phase {
                    running: root.motion > 0
                    loops: Animation.Infinite
                    from: 0
                    to: 1
                    // Wind drives the sky as well as the trees.
                    duration: Math.round(
                        (150000 - root._wind * 118000 + World.rand(cloud.index * 17) * 40000)
                        / Math.max(0.001, root.motion))
                }

                readonly property color _lit: cloud._heavy ? "#b9c2d0" : "#ffffff"
                readonly property color _body: cloud._heavy ? "#96a1b3" : "#eaf0f8"
                readonly property color _shade: cloud._heavy ? "#75808f" : "#c6d2e2"

                Repeater {
                    model: 5

                    Rectangle {
                        required property int index
                        readonly property real _r: 0.42 + World.rand(cloud.index * 31 + index * 3) * 0.58
                        width: Math.round(cloud._h * (1.5 + _r))
                        height: width
                        radius: width / 2
                        antialiasing: false
                        x: Math.round(index * (cloud._w - width) / 4)
                        y: Math.round((cloud._h - height) * (0.35 + World.rand(cloud.index * 7 + index) * 0.6))
                        color: cloud._body
                    }
                }

                // Lit crown along the top, shaded lip along the bottom.
                Rectangle {
                    x: Math.round(cloud._w * 0.18); y: 0
                    width: Math.round(cloud._w * 0.55)
                    height: Math.max(2, Math.round(cloud._h * 0.30))
                    radius: height / 2
                    antialiasing: false
                    color: cloud._lit
                }
                Rectangle {
                    x: Math.round(cloud._w * 0.10)
                    y: cloud._h - Math.max(2, Math.round(cloud._h * 0.26))
                    width: Math.round(cloud._w * 0.80)
                    height: Math.max(2, Math.round(cloud._h * 0.26))
                    radius: height / 2
                    antialiasing: false
                    color: cloud._shade
                }
            }
        }

        // ---- the land ----
        Item {
            id: land
            anchors.fill: parent

            readonly property var _built: Terrain.build(root.pixelWidth,
                                                        root.pixelHeight,
                                                        root._season,
                                                        root._pal)

            // Cached: rebuilt when the season turns, not per frame. Without
            // this the whole landscape is re-batched behind every cloud.
            layer.enabled: true
            layer.smooth: false

            Repeater {
                model: land._built.runs

                Rectangle {
                    required property var modelData
                    x: modelData.x
                    y: modelData.y
                    width: modelData.w
                    height: 1
                    color: modelData.c
                    antialiasing: false
                }
            }
        }

        // ---- foreground trees, which the wind moves ----
        //
        // Outside the cached layer because they animate. Each row is offset by
        // an amount that grows with height, so the tree bends rather than
        // sliding — a sprite translated as a block reads as a mistake.
        Repeater {
            model: land._built.sway

            Item {
                id: tree
                required property var modelData

                readonly property var _pixels: Terrain.swayTree(modelData.height,
                                                                root._pal,
                                                                modelData.dark)
                x: modelData.x
                y: modelData.base

                Repeater {
                    model: tree._pixels

                    Rectangle {
                        required property var modelData
                        readonly property real _up: Math.max(0, -modelData.y)
                                                    / Math.max(1, tree.modelData.height)
                        // Cubic: the crown swings, the trunk barely moves.
                        x: modelData.x + Math.round(root._wind * tree.modelData.lean
                                                    * 7 * _up * _up * _up)
                        y: modelData.y
                        width: 1
                        height: 1
                        color: modelData.c
                        antialiasing: false
                    }
                }
            }
        }

        // ---- butterflies, summer only ----
        Repeater {
            model: root._season === "summer" && root._wx.precip === 0
                   && root._night < 0.3 ? 4 : 0

            Item {
                id: fly
                required property int index

                property real phase: World.rand(index * 17 + 5)
                readonly property real _lane: World.rand(index * 9 + 2)

                x: ((phase) % 1.0) * (root.pixelWidth + 20) - 10
                y: root._meadowTop + 6
                   + _lane * (root.pixelHeight - root._meadowTop - 14)
                   + Math.sin(phase * 34) * 4

                NumberAnimation on phase {
                    running: root.motion > 0
                    loops: Animation.Infinite
                    from: 0
                    to: 1
                    duration: Math.round((26000 + World.rand(fly.index * 3) * 14000)
                                         / Math.max(0.001, root.motion))
                }

                // Two frames, alternating: the whole animation vocabulary of a
                // 3×3 sprite.
                Repeater {
                    model: 9

                    Rectangle {
                        required property int index
                        readonly property var _sprite: Math.floor(fly.phase * 60) % 2
                                                       ? Sprites.BUTTERFLY_A
                                                       : Sprites.BUTTERFLY_B
                        readonly property int _col: index % 3
                        readonly property int _row: Math.floor(index / 3)
                        readonly property string _ch: _sprite[_row].charAt(_col)
                        visible: _ch !== "."
                        x: _col
                        y: _row
                        width: 1
                        height: 1
                        antialiasing: false
                        color: _ch === "E" ? "#2b2b38" : "#f6d76b"
                    }
                }
            }
        }

        // ---- how much light the deck is taking out ----
        Rectangle {
            anchors.fill: parent
            color: "#2a3040"
            opacity: root._wx.gloom * 0.55
        }

        // ---- night ----
        //
        // Falls on the ground, not the sky: the sky is already the right
        // colour, and dimming it twice turns dusk to mud.
        Rectangle {
            x: 0
            y: root._meadowTop - 58
            width: parent.width
            height: parent.height - y
            color: "#141a2e"
            opacity: root._night * 0.68
            Behavior on opacity { NumberAnimation { duration: 1600 } }
        }

        // ---- precipitation ----
        //
        // Count, length, speed and slant all come from the condition, so a
        // drizzle is genuinely a drizzle and a downpour is genuinely one.
        Repeater {
            model: Math.round(root._wx.precip * (root._wx.precipKind === "snow" ? 90 : 150))

            Rectangle {
                id: drop
                required property int index

                readonly property bool _snow: root._wx.precipKind === "snow"
                property real phase: 0
                readonly property real _offset: World.rand(index * 5 + 1)
                readonly property real _t: (phase + _offset) % 1.0

                width: 1
                height: _snow ? 1 : Math.max(2, Math.round(2 + root._wx.precip * 5))
                color: _snow ? "#ffffff" : "#b6cde6"
                opacity: _snow ? 0.9 : 0.30 + root._wx.precip * 0.35
                antialiasing: false

                // Rain slants with the wind; the harder it blows, the further
                // a drop travels sideways before it lands.
                x: Math.floor(World.rand(index * 3 + 2) * (root.pixelWidth * 1.4))
                   - Math.round(_t * root._wind * (_snow ? 26 : 70))
                   + (_snow ? Math.round(Math.sin((_t + _offset) * 6.283) * 5) : 0)
                y: _t * (root.pixelHeight + 10) - 5

                NumberAnimation on phase {
                    running: root.motion > 0
                    loops: Animation.Infinite
                    from: 0
                    to: 1
                    duration: Math.round(
                        (drop._snow ? 5200 - root._wind * 2600 + World.rand(drop.index) * 2400
                                    : 1100 - root._wx.precip * 520 + World.rand(drop.index) * 320)
                        / Math.max(0.001, root.motion))
                }
            }
        }

        // ---- fog ----
        //
        // Sits on the horizon rather than over everything, which is where it
        // actually is.
        Rectangle {
            visible: root.weather === "fog"
            x: 0
            y: root._meadowTop - 56
            width: parent.width
            height: 86
            opacity: 0.55
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#00c9d4e0" }
                GradientStop { position: 0.45; color: "#c9d4e0" }
                GradientStop { position: 1.0; color: "#00c9d4e0" }
            }
        }

        // ---- lightning ----
        //
        // Two flashes close together, then a long wait — real lightning comes
        // in strokes, and a single even pulse reads as a fault in the display.
        Rectangle {
            id: flash
            anchors.fill: parent
            color: "#dfe8f8"
            opacity: 0

            SequentialAnimation {
                running: root._wx.lightning > 0 && root.motion > 0
                loops: Animation.Infinite

                PauseAnimation {
                    duration: Math.round((root._wx.lightning * 1000)
                                         * (0.55 + Math.random() * 0.9))
                }
                NumberAnimation { target: flash; property: "opacity"; to: 0.72; duration: 45 }
                NumberAnimation { target: flash; property: "opacity"; to: 0.05; duration: 90 }
                NumberAnimation { target: flash; property: "opacity"; to: 0.55; duration: 60 }
                NumberAnimation { target: flash; property: "opacity"; to: 0.0; duration: 380 }
            }
        }
    }

    /*  Cover, not stretch. Filling the item without preserving the aspect
        ratio turns the sun into an ellipse and the trees into topiary — the
        giveaway that it is a texture rather than a place. The overflow is
        cropped instead, biased upward so the sky is what gets lost.  */
    ShaderEffectSource {
        readonly property real _scale: Math.max(root.width / root.pixelWidth,
                                                root.height / root.pixelHeight)

        width: Math.ceil(root.pixelWidth * _scale)
        height: Math.ceil(root.pixelHeight * _scale)
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) * 0.35)

        sourceItem: world
        textureSize: Qt.size(root.pixelWidth, root.pixelHeight)
        hideSource: true
        smooth: false
        live: true
    }
}
