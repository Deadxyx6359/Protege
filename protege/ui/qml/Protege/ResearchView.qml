import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

/* Research shares the live Chat bridge. There is deliberately no simulated
   source list or agent trace: those require the backend research toolchain. */
Item {
    id: root
    property var model: null
    property bool busy: false
    property string busyStage: "Thinking"
    readonly property int count: model ? model.count : 0
    readonly property var starters: [
        { label: "Explore a topic", icon: "search",
          prompt: "Help me explore [topic]. Explain the core concepts, what is uncertain, and useful questions to investigate. Flag claims that need source verification." },
        { label: "Compare ideas", icon: "document",
          prompt: "Compare [idea A] and [idea B]. Explain their assumptions, trade-offs, and what evidence would distinguish them. Separate established facts from inference." },
        { label: "Plan an inquiry", icon: "sparkle",
          prompt: "Help me plan an investigation into [question]. Suggest a scope, the evidence I should gather, ways to check source quality, and a practical outline." }
    ]

    signal promptSelected(string prompt)
    signal newInquiryRequested()

    // Also useful to keyboard-driven callers; only prepares a draft.
    function chooseStarter(index) {
        if (index >= 0 && index < starters.length && !busy)
            promptSelected(starters[index].prompt);
    }

    RowLayout {
        id: heading
        anchors.top: parent.top
        anchors.topMargin: Theme.space.lg
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(720, parent.width - Theme.space.xxl * 2)
        height: 32
        visible: root.count > 0
        spacing: Theme.space.sm

        Icon { name: "search"; size: 17; color: Theme.accent }
        Text { text: "Research"; font: Theme.type.bodyStrong; color: Theme.textPrimary }
        Text {
            Layout.fillWidth: true
            text: "Local · Web search not connected"
            font: Theme.type.caption
            color: Theme.textTertiary
            elide: Text.ElideRight
        }
        C.AbstractButton {
            id: fresh
            objectName: "newResearchInquiry"
            text: "New inquiry"
            enabled: !root.busy
            implicitWidth: 108
            implicitHeight: 32
            hoverEnabled: true
            Accessible.name: text
            background: Rectangle {
                radius: Theme.radius.sm
                color: fresh.hovered ? Theme.surfaceHover : Theme.surface
                border.color: fresh.activeFocus ? Theme.accent : Theme.separator
            }
            contentItem: Text {
                text: fresh.text
                font: Theme.type.caption
                color: fresh.enabled ? Theme.textSecondary : Theme.textTertiary
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            onClicked: root.newInquiryRequested()
        }
    }

    ChatView {
        anchors.fill: parent
        anchors.topMargin: heading.height + Theme.space.xl
        model: root.model
        busy: root.busy
        busyStage: root.busyStage
        showGreeting: false
    }

    // Fixed reading width, with a shorter stack on the smallest supported
    // window. The landscape keeps its scale; the UI adapts independently.
    Squircle {
        id: welcome
        anchors.centerIn: parent
        anchors.verticalCenterOffset: parent.height > 560 ? -72 : -40
        width: Math.min(410, parent.width - 48)
        height: content.implicitHeight + 32
        radius: Theme.radius.lg
        visible: root.count === 0
        fillColor: Qt.rgba(Theme.canvas.r, Theme.canvas.g, Theme.canvas.b, 0.68)
        borderColor: Theme.separatorStrong

        ColumnLayout {
            id: content
            anchors.centerIn: parent
            width: parent.width - 36
            spacing: 10

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 7
                Icon { name: "search"; size: 14; color: Theme.accent }
                Text {
                    text: "RESEARCH"
                    font: Theme.type.caption
                    color: Theme.textSecondary
                }
            }
            Text {
                Layout.fillWidth: true
                text: "Go a little deeper."
                font: Theme.type.title1
                color: Theme.textPrimary
                horizontalAlignment: Text.AlignHCenter
            }
            Text {
                Layout.fillWidth: true
                text: "Find a useful question to follow."
                font: Theme.type.callout
                color: Theme.textSecondary
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                lineHeight: 1.3
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 5
                Repeater {
                    model: root.starters
                    C.AbstractButton {
                        id: starter
                        required property var modelData
                        required property int index
                        objectName: "researchStarter" + index
                        Layout.fillWidth: true
                        implicitHeight: 34
                        enabled: !root.busy
                        hoverEnabled: true
                        text: modelData.label
                        Accessible.name: text
                        background: Rectangle {
                            radius: Theme.radius.sm
                            color: starter.down ? Theme.surfaceActive
                                  : starter.hovered ? Theme.surfaceHover : Theme.surface
                            border.color: starter.activeFocus ? Theme.accent : Theme.separator
                            Behavior on color { ColorAnimation { duration: Theme.duration.fast } }
                        }
                        contentItem: RowLayout {
                            spacing: 10
                            Icon { Layout.leftMargin: 12; name: starter.modelData.icon; size: 15; color: Theme.textSecondary }
                            Text { Layout.fillWidth: true; text: starter.text; font: Theme.type.callout; color: Theme.textPrimary }
                            Text { Layout.rightMargin: 12; text: "↗"; font: Theme.type.callout; color: Theme.textTertiary }
                        }
                        onClicked: root.chooseStarter(index)
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                Layout.topMargin: 2
                text: "Your current conversation, using your local model.\nWeb search is not connected yet."
                font: Theme.type.caption
                color: Theme.textTertiary
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                lineHeight: 1.35
            }
        }
    }
}
