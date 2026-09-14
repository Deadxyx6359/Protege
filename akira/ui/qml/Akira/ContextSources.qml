import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

// These are retrieval labels from the actual turn, not a bibliography inferred
// from the answer. No path or URL is guessed from a citation's display text.
Rectangle {
    id: root
    property var sources: []
    property string note: ""
    property bool expanded: false
    property real maximumHeight: 190
    readonly property bool available: sources.length > 0 || note.length > 0
    implicitHeight: available ? 38 + (expanded ? Math.min(maximumHeight, detail.implicitHeight + 20) : 0) : 0
    visible: available
    color: Theme.surface
    border.color: Theme.separator
    radius: Theme.radius.md
    onSourcesChanged: expanded = false

    C.AbstractButton {
        id: disclosure
        objectName: "contextSourcesToggle"
        width: parent.width
        height: 38
        text: root.sources.length ? "Retrieved context · " + root.sources.length : "Context note"
        Accessible.name: (root.expanded ? "Hide " : "Show ") + text
        hoverEnabled: true
        background: Rectangle {
            radius: Theme.radius.md
            color: disclosure.hovered ? Theme.surfaceHover : "transparent"
            border.color: disclosure.activeFocus ? Theme.accent : "transparent"
        }
        contentItem: RowLayout {
            spacing: 8
            Icon { Layout.leftMargin: 12; name: "document"; size: 14; color: Theme.accent }
            Text {
                Layout.fillWidth: true
                text: disclosure.text; textFormat: Text.PlainText
                font: Theme.type.captionStrong; color: Theme.textSecondary
            }
            Icon {
                Layout.rightMargin: 12
                name: "chevronRight"; size: 14; color: Theme.textSecondary
                rotation: root.expanded ? 90 : 0
                Behavior on rotation { NumberAnimation { duration: Theme.duration.fast } }
            }
        }
        onClicked: root.expanded = !root.expanded
    }
    C.ScrollView {
        id: scroll
        objectName: "contextSourcesScroll"
        anchors.top: disclosure.bottom
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.margins: 10
        visible: root.expanded
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            id: detail
            width: scroll.availableWidth
            spacing: 10
            Text {
                Layout.fillWidth: true
                text: "Retrieved for the latest turn. These labels identify context supplied to the model."
                textFormat: Text.PlainText
                font: Theme.type.caption; color: Theme.textTertiary; wrapMode: Text.Wrap
            }
            Repeater {
                model: root.sources
                ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        text: ({notes: "Note", documents: "Document", conversations: "Conversation"})[parent.modelData.source] || "Source"
                        textFormat: Text.PlainText
                        font: Theme.type.captionStrong; color: Theme.accent
                    }
                    Text {
                        Layout.fillWidth: true
                        text: parent.modelData.cite || ""
                        textFormat: Text.PlainText
                        font: Theme.type.callout; color: Theme.textPrimary; wrapMode: Text.Wrap
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: !!root.note
                text: root.note; textFormat: Text.PlainText
                font: Theme.type.caption; color: Theme.textSecondary; wrapMode: Text.Wrap
            }
        }
    }
}
