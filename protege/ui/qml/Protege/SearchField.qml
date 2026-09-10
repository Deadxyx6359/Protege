import QtQuick
import QtQuick.Controls as C

/*!
    The sidebar's search box.

    Recessed rather than raised — it is a place to put something *into*, and
    the inset surface says that before the placeholder does.
*/
Item {
    id: root

    property string placeholder: "Search"
    property alias text: field.text

    signal accepted(string text)

    implicitWidth: 220
    implicitHeight: 32

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius.sm
        color: Theme.inset
        border.width: 1
        border.color: field.activeFocus ? Theme.accent : Theme.separator

        Behavior on border.color {
            ColorAnimation { duration: Theme.duration.fast }
        }
    }

    Icon {
        id: glass
        anchors.left: parent.left
        anchors.leftMargin: Theme.space.sm
        anchors.verticalCenter: parent.verticalCenter
        name: "search"
        size: 15
        color: field.activeFocus ? Theme.accent : Theme.textTertiary
    }

    C.TextField {
        id: field
        anchors.left: glass.right
        anchors.leftMargin: Theme.space.xs + 2
        anchors.right: clear.left
        anchors.rightMargin: Theme.space.xs
        anchors.verticalCenter: parent.verticalCenter

        font: Theme.type.callout
        color: Theme.textPrimary
        selectionColor: Theme.accentSubtle
        selectedTextColor: Theme.textPrimary
        placeholderText: root.placeholder
        placeholderTextColor: Theme.textTertiary
        verticalAlignment: TextInput.AlignVCenter

        // The Basic style still paints a background and a frame; both have to
        // go, or they sit inside the rounded plate above.
        background: null
        padding: 0

        onAccepted: root.accepted(text)
    }

    IconButton {
        id: clear
        anchors.right: parent.right
        anchors.rightMargin: Theme.space.xxs
        anchors.verticalCenter: parent.verticalCenter
        visible: field.text !== ""
        icon: "close"
        size: 22
        iconSize: 13
        flat: true
        onClicked: { field.text = ""; field.forceActiveFocus() }
    }
}
