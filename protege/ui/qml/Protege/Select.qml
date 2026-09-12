import QtQuick
import QtQuick.Controls as C

/*!
    A dropdown, restyled from Quick Controls' Basic ComboBox.

    Wrapped rather than used directly because ComboBox's default popup is a
    plain rectangle with a system-coloured highlight, which is visible from
    across the room in a window built this carefully.
*/
Item {
    id: root

    /*! [{ value, label, detail }] */
    property var options: []
    property string current: ""
    property string placeholder: "Not set"

    signal picked(string value)

    implicitWidth: 260
    implicitHeight: 32

    readonly property int _index: {
        for (var i = 0; i < options.length; i++)
            if (options[i].value === current)
                return i;
        return -1;
    }

    C.ComboBox {
        id: box
        anchors.fill: parent
        model: root.options
        textRole: "label"
        valueRole: "value"
        currentIndex: root._index
        font: Theme.type.callout

        onActivated: function (index) {
            root.picked(root.options[index].value);
        }

        background: Rectangle {
            radius: Theme.radius.sm
            color: box.hovered ? Theme.surfaceHover : Theme.surface
            border.width: 1
            border.color: box.activeFocus ? Theme.accent : Theme.separatorStrong

            Behavior on color { ColorAnimation { duration: Theme.duration.fast } }
        }

        contentItem: Text {
            leftPadding: Theme.space.md
            rightPadding: Theme.space.xl
            verticalAlignment: Text.AlignVCenter
            text: root._index >= 0 ? root.options[root._index].label : root.placeholder
            textFormat: Text.PlainText
            font: Theme.type.callout
            color: root._index >= 0 ? Theme.textPrimary : Theme.textTertiary
            elide: Text.ElideRight
        }

        indicator: Icon {
            x: box.width - width - Theme.space.sm
            y: (box.height - height) / 2
            name: "chevronUpDown"
            size: 15
            color: Theme.textTertiary
        }

        popup: C.Popup {
            y: box.height + Theme.space.xxs
            width: box.width
            implicitHeight: Math.min(contentItem.implicitHeight + 8, 280)
            padding: 4

            background: Squircle {
                radius: Theme.radius.sm
                fillColor: Theme.overlay
                borderColor: Theme.separatorStrong
            }

            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: box.popup.visible ? box.delegateModel : null
                currentIndex: box.highlightedIndex
                C.ScrollBar.vertical: C.ScrollBar {}
            }
        }

        // `option` rather than a chain of `parent.parent`: contentItem and
        // background are reparented by the control, so relative lookups here
        // silently resolve to the wrong object when the style changes.
        delegate: C.ItemDelegate {
            id: option
            required property var modelData
            required property int index

            width: box.width - 8
            height: 32

            background: Rectangle {
                radius: Theme.radius.xs
                color: box.highlightedIndex === option.index ? Theme.accentSubtle
                                                             : "transparent"
            }

            contentItem: Row {
                spacing: Theme.space.sm

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, box.width - 110)
                    text: option.modelData.label
                    textFormat: Text.PlainText
                    font: Theme.type.callout
                    color: Theme.textPrimary
                    elide: Text.ElideRight
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: text !== ""
                    text: option.modelData.detail || ""
                    textFormat: Text.PlainText
                    font: Theme.type.caption
                    color: Theme.textTertiary
                }
            }
        }
    }
}
