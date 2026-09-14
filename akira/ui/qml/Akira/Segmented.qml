import QtQuick

/*!
    A segmented control — one choice from a small, fixed set.

    The selected pill *slides* between segments rather than appearing under the
    new one. In a single flat row that motion carries meaning: it shows which
    option you moved from, which a cross-fade throws away.
*/
Item {
    id: root

    /*! [{ id, label }] */
    property var options: []
    property string current: ""

    signal selected(string id)
    function pick(index) {
        if (!root.enabled || !root.options.length) return;
        const next = (index + root.options.length) % root.options.length;
        root.selected(root.options[next].id);
        segments.itemAt(next).forceActiveFocus();
    }
    opacity: enabled ? 1 : 0.45

    implicitWidth: 240
    implicitHeight: 30

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius.sm
        color: Theme.inset
    }

    readonly property int _count: Math.max(1, options.length)
    readonly property real _slot: width / _count
    readonly property int _index: {
        for (var i = 0; i < options.length; i++)
            if (options[i].id === current)
                return i;
        return 0;
    }

    Rectangle {
        width: root._slot - 4
        height: parent.height - 4
        y: 2
        x: root._index * root._slot + 2
        radius: Theme.radius.xs
        color: Theme.surfaceActive

        Behavior on x {
            NumberAnimation {
                duration: Theme.duration.normal
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easing.standard
            }
        }
    }

    Row {
        anchors.fill: parent

        Repeater {
            id: segments
            model: root.options

            Item {
                required property var modelData
                required property int index
                width: root._slot
                height: root.height
                activeFocusOnTab: root.enabled && root._index === index
                Accessible.role: Accessible.RadioButton
                Accessible.name: modelData.label
                Accessible.checkable: true
                Accessible.checked: root._index === index
                Accessible.onPressAction: root.pick(index)
                Keys.onSpacePressed: root.pick(index)
                Keys.onReturnPressed: root.pick(index)
                Keys.onEnterPressed: root.pick(index)
                Keys.onLeftPressed: root.pick(index - 1)
                Keys.onRightPressed: root.pick(index + 1)
                Keys.onPressed: function (event) {
                    if (event.key === Qt.Key_Home || event.key === Qt.Key_End) {
                        root.pick(event.key === Qt.Key_Home ? 0 : root.options.length - 1);
                        event.accepted = true;
                    }
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 1
                    radius: Theme.radius.sm
                    color: "transparent"
                    border.color: Theme.accent
                    border.width: 2
                    visible: parent.activeFocus
                }

                Text {
                    anchors.centerIn: parent
                    width: parent.width - 12
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: parent.modelData.label
                    textFormat: Text.PlainText
                    font: root._index === parent.index ? Theme.type.captionStrong
                                                       : Theme.type.caption
                    color: root._index === parent.index ? Theme.textPrimary
                                                        : Theme.textSecondary

                    Behavior on color {
                        ColorAnimation { duration: Theme.duration.fast }
                    }
                }

                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.pick(parent.index) }
            }
        }
    }
}
