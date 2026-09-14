import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

/* Local discussion and explicitly started investigations share one workspace. */
Item {
    id: root
    property var model: null
    property bool busy: false
    property string busyStage: "Thinking"
    property var sources: []
    property string contextNote: ""
    property bool investigating: false
    property alias investigation: investigations
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
    signal researchTeamRequested()
    signal sourceRequested(string error)
    signal permissionsRequested()

    function prepareInvestigation(text) {
        investigating = true;
        investigations.prepare(text);
    }

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
        width: Math.min(900, parent.width - 48)
        height: 32
        spacing: Theme.space.sm

        Segmented {
            objectName: "researchModes"
            Layout.preferredWidth: 280
            Layout.preferredHeight: 32
            options: [{id: "conversation", label: "Conversation"}, {id: "investigations", label: "Investigations"}]
            current: root.investigating ? "investigations" : "conversation"
            onSelected: function (id) { root.investigating = id === "investigations"; }
        }
        Item { Layout.fillWidth: true }
        ActionButton {
            visible: root.count > 0 && !root.investigating && root.width > 700
            text: "Research team"
            enabled: !root.busy
            onClicked: root.researchTeamRequested()
        }
        C.AbstractButton {
            id: fresh
            visible: root.count > 0 && !root.investigating
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
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: fresh.enabled ? Theme.textSecondary : Theme.textTertiary
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            onClicked: root.newInquiryRequested()
        }
    }

    ChatView {
        visible: !root.investigating
        anchors.fill: parent
        anchors.topMargin: heading.height + Theme.space.xl
        model: root.model
        busy: root.busy
        busyStage: root.busyStage
        sources: root.sources
        contextNote: root.contextNote
        showGreeting: false
    }

    InvestigationsView {
        id: investigations
        objectName: "researchInvestigations"
        anchors.fill: parent
        anchors.topMargin: heading.height + Theme.space.xl + Theme.space.md
        visible: root.investigating
        onSourceRequested: function (error) { root.sourceRequested(error); }
        onPermissionsRequested: root.permissionsRequested()
    }

    // Fixed reading width, with a shorter stack on the smallest supported
    // window. The landscape keeps its scale; the UI adapts independently.
    Squircle {
        id: welcome
        anchors.centerIn: parent
        anchors.verticalCenterOffset: parent.height > 560 ? -72 : -20
        width: Math.min(410, parent.width - 48)
        height: content.implicitHeight + 32
        radius: Theme.radius.lg
        visible: root.count === 0 && !root.investigating
        // Light text surfaces need more opacity over the near-black abyss;
        // otherwise the small supporting copy becomes grey on grey.
        fillColor: Qt.rgba(Theme.canvas.r, Theme.canvas.g, Theme.canvas.b, Theme.isDark ? 0.88 : 0.94)
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
                            Text { Layout.fillWidth: true; text: starter.text; textFormat: Text.PlainText; font: Theme.type.callout; color: Theme.textPrimary }
                            Text { Layout.rightMargin: 12; text: "↗"; font: Theme.type.callout; color: Theme.textTertiary }
                        }
                        onClicked: root.chooseStarter(index)
                    }
                }
            }
            ActionButton {
                objectName: "prepareResearchTeam"
                Layout.fillWidth: true
                text: "Research with a team"
                enabled: !root.busy
                onClicked: root.researchTeamRequested()
            }
            Text {
                Layout.fillWidth: true
                Layout.topMargin: 2
                text: "Explore in local chat, or prepare a research task.\nYour permissions decide which sources the team can reach."
                font: Theme.type.caption
                color: Theme.textTertiary
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                lineHeight: 1.35
            }
        }
    }
}
