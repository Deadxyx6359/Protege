import QtQuick
import QtQuick.Layouts

// A labelled setting: its name, a line on what it does, and its control on the right.
Item {
    id: root
    property string title: ""
    property string description: ""
    property bool divider: true
    default property alias controls: actions.data
    implicitHeight: Math.max(labels.implicitHeight, actions.implicitHeight) + 24
    implicitWidth: 480

    ColumnLayout {
        id: labels
        anchors.left: parent.left
        anchors.right: actions.left
        anchors.rightMargin: 20
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4
        Text {
            Layout.fillWidth: true
            text: root.title
            textFormat: Text.PlainText
            font: Theme.type.bodyStrong
            color: Theme.textPrimary
            wrapMode: Text.Wrap
        }
        // One short line on what the setting does, in plain words.
        Text {
            Layout.fillWidth: true
            visible: root.description !== ""
            text: root.description
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }
    }
    RowLayout {
        id: actions
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8
    }
    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.separator
        visible: root.divider
    }
}
