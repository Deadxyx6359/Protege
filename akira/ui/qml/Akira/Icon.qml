import QtQuick
import QtQuick.Shapes
import "icons.js" as Icons

/*!
    A vector icon from the Akira set.

    \qml
    Icon { name: "search"; size: 18; color: Theme.textSecondary }
    \endqml

    Drawn rather than loaded: paths scale to any size and recolour instantly,
    where a bitmap set would need one asset per size and per appearance, and
    would still be soft at 1.25 DPI.
*/
Item {
    id: root

    /*! A key from icons.js. An unknown name draws nothing. */
    required property string name

    /*! Rendered edge length. The path grid is 24×24 and scales to fit. */
    property real size: 20

    property color color: Theme.textPrimary

    /*! Stroke weight on the 24-unit grid. Scaled along with the icon, so a
        14px and a 28px icon carry the same optical weight. 1.7 sits alongside
        Segoe UI Variable at body and headline sizes. */
    property real weight: 1.7

    implicitWidth: size
    implicitHeight: size

    readonly property var _icon: Icons.lookup(name)

    Behavior on color {
        ColorAnimation { duration: Theme.duration.fast }
    }

    Shape {
        // Laid out on the icon grid and scaled as a whole, so the stroke
        // scales with the geometry instead of staying a fixed pixel width.
        width: 24
        height: 24
        scale: root.size / 24
        transformOrigin: Item.TopLeft

        preferredRendererType: Shape.CurveRenderer
        visible: root._icon !== null

        ShapePath {
            // A stroked icon must not be filled, or every open path closes
            // itself with a straight edge across the gap.
            fillColor: root._icon && root._icon.filled ? root.color : "transparent"
            strokeColor: root._icon && root._icon.filled ? "transparent" : root.color
            strokeWidth: root.weight
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            PathSvg { path: root._icon ? root._icon.path : "" }
        }
    }
}
