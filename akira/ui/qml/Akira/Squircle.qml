import QtQuick
import QtQuick.Shapes
import "squircle.js" as Sq

/*!
    A rectangle with continuous-curvature corners.

    Drop-in background for anything that would otherwise use a \c Rectangle
    with a large \c radius:

    \qml
    Squircle {
        anchors.fill: parent
        radius: Theme.radius.lg
        fillColor: Theme.surface
        borderColor: Theme.separator
    }
    \endqml

    A \c Shape costs more than a \c Rectangle — it re-tessellates whenever the
    geometry changes. Worth it for cards, sheets and panels; not worth it for
    list rows or badges, where the corner is too small for anyone to see the
    difference.
*/
Item {
    id: root

    /*! Corner radius, in pixels. */
    property real radius: 12

    /*! How much of the corner eases rather than arcs. 0.6 matches Apple. */
    property real smoothing: Sq.DEFAULT_SMOOTHING

    property color fillColor: "transparent"
    property color borderColor: "transparent"
    property real borderWidth: 1

    /*! Animates \c fillColor changes, so a palette swap cross-fades. */
    property int colorDuration: Theme.duration.normal

    Behavior on fillColor {
        ColorAnimation { duration: root.colorDuration }
    }
    Behavior on borderColor {
        ColorAnimation { duration: root.colorDuration }
    }

    Shape {
        anchors.fill: parent

        /*  The curve renderer antialiases on the GPU from the actual curve
            rather than from a multisampled tessellation, which is what keeps
            a large corner clean without a 4x layer.  */
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            fillColor: root.fillColor
            strokeColor: root.borderWidth > 0 ? root.borderColor : "transparent"
            strokeWidth: root.borderWidth
            joinStyle: ShapePath.RoundJoin

            PathSvg {
                path: Sq.path(root.width, root.height, root.radius, root.smoothing)
            }
        }
    }
}
