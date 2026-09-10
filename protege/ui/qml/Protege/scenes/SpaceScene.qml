import QtQuick
// Explicit: a file in a module subdirectory does not implicitly see the
// module's own singletons the way one in the module root does.
import Protege
import "world.js" as World

/*!
    An 8-bit star field, for the code view.

    Deliberately quiet. The botanica scene is meant to be looked at; this one
    is meant to be worked in front of, and anything that catches the eye while
    you are reading a stack trace is a bug in the design. Near-monochrome, slow
    drift, nothing that flashes.

    Same construction as the landscape: drawn into a small buffer, scaled up
    with nearest-neighbour filtering, laid out from fixed seeds so it is the
    same sky every time.
*/
Item {
    id: root

    /*! Scales all motion, so reduce-motion stills the sky too. */
    property real motion: 1.0

    /*! Faint colour cast. Bound to the accent so the scene follows the theme
        without ever becoming colourful. */
    property color tint: Theme.accent

    readonly property int pixelWidth: 256
    readonly property int pixelHeight: 144

    clip: true

    Item {
        id: world
        width: root.pixelWidth
        height: root.pixelHeight

        // ---- deep space ----
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#05060d" }
                GradientStop { position: 0.55; color: "#080a14" }
                GradientStop { position: 1.0; color: "#0c0e1a" }
            }
        }

        // ---- nebula ----
        //
        // Two very faint tinted clouds, drifting in opposite directions. At
        // this opacity they are barely a colour — they exist to stop the
        // background reading as flat black, not to be noticed.
        Repeater {
            model: 2

            Rectangle {
                required property int index

                readonly property real _drift: index === 0 ? 1 : -1

                width: root.pixelWidth * 0.45
                height: root.pixelHeight * 0.28
                radius: height / 2
                antialiasing: false
                y: index === 0 ? root.pixelHeight * 0.12 : root.pixelHeight * 0.52
                color: index === 0 ? root.tint : "#3a6ea5"
                opacity: 0.075

                property real phase: index * 0.5
                x: ((phase % 1.0) * 2 - 0.5) * root.pixelWidth * _drift

                NumberAnimation on phase {
                    running: root.motion > 0
                    loops: Animation.Infinite
                    from: 0
                    to: 1
                    duration: Math.round(240000 / Math.max(0.001, root.motion))
                }
            }
        }

        // ---- star field ----
        //
        // Three layers at different speeds. Parallax is the only depth cue
        // available in a flat star field, and it is enough.
        Repeater {
            model: 3

            Item {
                id: band
                required property int index
                anchors.fill: parent

                /*  `band`, not `layer`: every Item already has a `layer` grouped
                    property, so an id of that name shadows it and every
                    `layer.something` below resolves to the attached property.
                    The star field rendered nothing at all.  */
                readonly property int _count: [54, 34, 18][index]
                readonly property real _size: [1, 1, 2][index]
                readonly property real _bright: [0.35, 0.6, 0.95][index]
                readonly property int _period: [420000, 260000, 170000][index]

                property real phase: 0

                NumberAnimation on phase {
                    running: root.motion > 0
                    loops: Animation.Infinite
                    from: 0
                    to: 1
                    duration: Math.round(band._period / Math.max(0.001, root.motion))
                }

                Repeater {
                    model: band._count

                    Rectangle {
                        required property int index

                        readonly property int _seed: band.index * 200 + index * 7 + 1
                        readonly property real _base: World.rand(_seed)

                        width: band._size
                        height: band._size
                        color: "#ffffff"
                        opacity: band._bright * (0.5 + World.rand(_seed + 91) * 0.5)

                        // Wraps horizontally. Vertical position is fixed —
                        // stars that drift diagonally read as snow.
                        x: ((_base + band.phase) % 1.0) * (root.pixelWidth + 4) - 2
                        y: Math.floor(World.rand(_seed + 37) * root.pixelHeight)

                        // Only the nearest layer twinkles, and slowly. A sky
                        // where everything blinks is a sky you cannot work in
                        // front of.
                        SequentialAnimation on opacity {
                            running: band.index === 2 && root.motion > 0
                            loops: Animation.Infinite
                            NumberAnimation {
                                to: 0.28
                                duration: 2400 + Math.floor(World.rand(_seed) * 3200)
                                easing.type: Easing.InOutSine
                            }
                            NumberAnimation {
                                to: 0.95
                                duration: 2400 + Math.floor(World.rand(_seed + 5) * 3200)
                                easing.type: Easing.InOutSine
                            }
                        }
                    }
                }
            }
        }

        // ---- a planet, low and mostly out of frame ----
        //
        // Anchored to a corner rather than floating: something with an edge
        // gives the field a sense of scale, and keeping it cropped stops it
        // becoming the subject.
        Item {
            width: 54
            height: 54
            x: root.pixelWidth - 30
            y: root.pixelHeight - 22

            Rectangle {
                anchors.fill: parent
                radius: width / 2
                antialiasing: false
                color: "#141a2b"
            }
            // Terminator: a lit crescent along the upper-left limb.
            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: width / 2
                antialiasing: false
                color: "transparent"
                border.width: 2
                border.color: root.tint
                opacity: 0.30
            }
        }

        // ---- the occasional passing satellite ----
        //
        // One slow mover, far apart in time. Something that changes rarely is
        // worth more than something that changes constantly: you notice it
        // once, and it never asks for attention again.
        Rectangle {
            id: satellite
            width: 1
            height: 1
            color: "#dfe6f2"
            opacity: 0.9
            y: 26

            property real phase: 0
            x: phase * (root.pixelWidth + 20) - 10
            visible: root.motion > 0 && phase > 0 && phase < 1

            SequentialAnimation on phase {
                running: root.motion > 0
                loops: Animation.Infinite
                NumberAnimation { from: 0; to: 1; duration: 22000 }
                PauseAnimation { duration: 95000 }
            }
        }
    }

    ShaderEffectSource {
        readonly property real _scale: Math.max(root.width / root.pixelWidth,
                                                root.height / root.pixelHeight)

        width: Math.ceil(root.pixelWidth * _scale)
        height: Math.ceil(root.pixelHeight * _scale)
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)

        sourceItem: world
        textureSize: Qt.size(root.pixelWidth, root.pixelHeight)
        hideSource: true
        smooth: false
        live: true
    }
}
