import QtQuick
// Explicit: a file in a module subdirectory does not implicitly see the
// module's own singletons the way one in the module root does.
import Akira
import "world.js" as World

/*!
    The animated backdrop, and the thing that keeps it from eating the text.

    Each view gets its own world. The scene is the hero on an empty canvas and
    retreats to texture the moment there is something to read — because a
    landscape behind a paragraph is a landscape you will end up turning off.

    \qml
    SceneHost {
        anchors.fill: parent
        view: "chats"
        quiet: Chat.messages.count > 0
    }
    \endqml
*/
Item {
    id: root

    /*! Which world: chats, code, research. Anything else draws nothing. */
    property string view: "chats"

    /*! True when there is content in front of the scene. Pulls it back. */
    property bool quiet: false

    /*! One of world.js WEATHER. Set by a connector when one is permitted. */
    property string weather: "clear"

    property bool southernHemisphere: false

    /*! Scales all motion. Wired to the reduce-motion setting. */
    property real motion: 1.0

    /*! Advanced by the timer; the scenes read it. */
    property date now: new Date()

    /*  Once a minute is plenty. The sky moves through a keyframe in tens of
        minutes, and a scene that repaints on a one-second tick is a scene that
        keeps the GPU awake for no visible gain.  */
    Timer {
        interval: 60000
        running: root.visible
        repeat: true
        triggeredOnStart: true
        onTriggered: root.now = new Date()
    }

    Loader {
        id: scene
        anchors.fill: parent
        active: root.view === "chats" || root.view === "code" || root.view === "research"
        sourceComponent: root.view === "research" ? abyssScene : root.view === "code" ? spaceScene : botanicaScene

        // Worlds cross-fade rather than cutting, so switching views feels like
        // moving between rooms rather than a channel change.
        opacity: root.quiet ? 0.0 : 1.0

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.duration.slower
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easing.standard
            }
        }
    }

    Component {
        id: botanicaScene

        BotanicaScene {
            now: root.now
            weather: root.weather
            southernHemisphere: root.southernHemisphere
            motion: root.motion
            active: !root.quiet && root.visible
        }
    }

    Component {
        id: abyssScene

        AbyssScene {
            motion: root.motion
            active: !root.quiet && root.visible
        }
    }

    Component {
        id: spaceScene

        SpaceScene {
            motion: root.motion
            active: !root.quiet && root.visible
        }
    }

    /*  The scene is faded out entirely rather than dimmed behind a scrim when
        there is content. A scrim over a bright summer sky still leaves a
        gradient behind the text, and body copy over any gradient is worse than
        body copy over a flat ground — this is the same reason the reading
        column exists at all.

        Fading rather than unloading keeps the return instant, and an invisible
        Loader costs nothing per frame: the ShaderEffectSource inside stops
        rendering when opacity reaches zero.  */
    Rectangle {
        anchors.fill: parent
        color: Theme.canvas
        opacity: root.quiet ? 1.0 : 0.0
        visible: opacity > 0

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.duration.slower
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easing.standard
            }
        }
    }

    /*  A floor under the composer, so a bright meadow never sits directly
        behind it. Present even when the scene is the hero.

        Three stops rather than two, and reaching the canvas colour well before
        the bottom edge: the model name sits below the composer, at caption
        size, and a two-stop fade left it washed out against a summer field.  */
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Math.min(160, parent.height * 0.23)
        visible: !root.quiet
        gradient: Gradient {
            GradientStop { position: 0.00; color: "transparent" }
            GradientStop { position: 0.55; color: Qt.rgba(Theme.canvas.r, Theme.canvas.g,
                                                          Theme.canvas.b, 0.72) }
            GradientStop { position: 1.00; color: Theme.canvas }
        }
    }
}
