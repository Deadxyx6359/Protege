import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import QtQuick.Layouts

// Each agent's current run state stays visible; detailed activity is optional.
Item {
    id: root

    /*! "team:<name>" or "agent:<name>". */
    property string chosen: Agents.teams.length > 0 ? "team:" + Agents.teams[0].name : ""
    readonly property bool isTeam: chosen.indexOf("team:") === 0
    readonly property string chosenName: chosen.substring(chosen.indexOf(":") + 1)

    readonly property var team: {
        for (var i = 0; i < Agents.teams.length; i++)
            if (Agents.teams[i].name === root.chosenName)
                return Agents.teams[i];
        return null;
    }
    readonly property var members: isTeam ? (team ? team.members : []) : [chosenName]

    property string notice: ""
    property string folder: ""
    property bool showTeamDetails: false
    property bool showRecord: false
    property string lastRunName: "Previous task"
    property string lastRunProject: ""
    property alias taskDraft: taskInput.text
    signal historyRequested()

    function prepareTeam(name, task, folder) {
        if (Agents.busy) return "An agent run is already in progress. Finish or stop it before preparing another.";
        if (!Agents.teams.some(function (team) { return team.name === name; })) return "That team is unavailable.";
        root.chosen = "team:" + name;
        taskInput.text = task;
        root.folder = folder || "";
        root.notice = "";
        Qt.callLater(function () { taskInput.forceActiveFocus(); scroller.contentItem.contentY = 0; });
        return "";
    }

    function role(name) {
        return Agents.roles.find(function (r) { return r.name === name; }) || null;
    }
    function titled(name) { return name.charAt(0).toUpperCase() + name.slice(1); }

    function start() {
        var task = taskInput.text.trim();
        if (Agents.busy || !task || task.length > 4000) return;
        AgentTrace.clear();
        root.notice = root.isTeam ? Agents.runTeam(root.chosenName, task, root.folder)
                                  : Agents.runAgent(root.chosenName, task, root.folder);
    }

    Connections {
        target: Agents
        function onBusyChanged() {
            if (Agents.busy) {
                root.lastRunName = Agents.running;
                root.lastRunProject = Projects.currentName || "Personal workspace";
            }
        }
    }

    FolderDialog {
        id: folderPicker
        title: "Where the agents should work"
        onAccepted: {
            var text = selectedFolder.toString();
            root.folder = decodeURIComponent(text.indexOf("file:///") === 0 ? text.substring(8) : text);
        }
    }

    // -- pieces ------------------------------------------------------------------

    component Card: Squircle {
        default property alias content: inner.data
        property int pad: Theme.space.lg
        Layout.fillWidth: true
        implicitHeight: inner.implicitHeight + pad * 2
        radius: Theme.radius.md
        fillColor: Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.94)
        borderColor: Theme.separator
        ColumnLayout {
            id: inner
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: parent.pad
            spacing: Theme.space.md
        }
    }

    // -- the page --------------------------------------------------------------------

    C.ScrollView {
        id: scroller
        anchors.fill: parent
        anchors.topMargin: Theme.space.lg
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: Math.min(820, scroller.availableWidth - Theme.space.xxl * 2)
            x: (scroller.availableWidth - width) / 2
            spacing: Theme.space.lg

            // -- who ---------------------------------------------------------------
            Card {
                RowLayout {
                    Layout.fillWidth: true
                    Icon { name: "team"; size: 18; color: Theme.accent }
                    Text {
                        Layout.fillWidth: true
                        text: "Agents"
                        font: Theme.type.title3
                        color: Theme.textPrimary
                    }
                    ActionButton { visible: Agents.busy; text: "Stop"; onClicked: Agents.stop() }
                    ActionButton { objectName: "agentHistoryButton"; text: "Task history"; onClicked: root.historyRequested() }
                }


                Text {
                    Layout.fillWidth: true
                    visible: Agents.busy
                    text: Agents.currentRun.task || ""
                    textFormat: Text.PlainText
                    font: Theme.type.callout
                    color: Theme.textSecondary
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }

                RowLayout {
                    Layout.fillWidth: true
                    Select {
                        objectName: "agentTeamPicker"
                        Layout.fillWidth: true
                        enabled: !Agents.busy
                        label: "Team or agent"
                        current: root.chosen
                        options: Agents.teams.map(function (t) {
                            return {value: "team:" + t.name, label: root.titled(t.name) + " team", detail: t.members.length + " agents"};
                        }).concat(Agents.roles.map(function (a) {
                            return {value: "agent:" + a.name, label: root.titled(a.name), detail: "Individual"};
                        }))
                        onPicked: function (value) { root.chosen = value }
                    }
                    ActionButton {
                        text: root.showTeamDetails ? "Hide details" : "Team details"
                        onClicked: root.showTeamDetails = !root.showTeamDetails
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: root.isTeam ? (root.team ? root.team.purpose : "") : (root.role(root.chosenName) || {}).summary || ""
                    visible: root.showTeamDetails && text !== ""
                    textFormat: Text.PlainText
                    font: Theme.type.callout
                    color: Theme.textPrimary
                    wrapMode: Text.Wrap
                }
            }

            // -- the task ------------------------------------------------------------
            Card {
                visible: !Agents.busy
                id: taskCard
                objectName: "agentTaskCard"
                RowLayout {
                    Layout.fillWidth: true
                    Text { Layout.fillWidth: true; text: "The task"; font: Theme.type.headline; color: Theme.textPrimary }
                    Text {
                        text: taskInput.text.length + " / 4000"
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: taskInput.text.length > 4000 ? Theme.danger : Theme.textTertiary
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 96
                    radius: Theme.radius.sm
                    color: Theme.inset
                    border.width: 1
                    border.color: taskInput.activeFocus ? Theme.accent : Theme.separator
                    C.ScrollView {
                        anchors.fill: parent
                        anchors.margins: Theme.space.sm
                        C.TextArea {
                            id: taskInput
                            objectName: "agentTask"
                            placeholderText: root.isTeam ? "What should the team work on?"
                                                         : "What should this agent do?"
                            placeholderTextColor: Theme.textTertiary
                            font: Theme.type.body
                            color: Theme.textPrimary
                            wrapMode: TextEdit.Wrap
                            textFormat: TextEdit.PlainText
                            readOnly: Agents.busy
                            Accessible.name: "Agent task"
                            selectByMouse: true
                            background: null
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space.sm
                    ActionButton {
                        text: root.folder === "" ? "Choose a folder…" : "Change folder…"
                        enabled: !Agents.busy
                        onClicked: folderPicker.open()
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.folder
                        textFormat: Text.PlainText
                        font: root.folder === "" ? Theme.type.caption : Theme.type.monoSmall
                        color: Theme.textTertiary
                        elide: Text.ElideMiddle
                    }
                    ActionButton {
                        visible: Agents.busy
                        text: "Stop"
                        onClicked: Agents.stop()
                    }
                    ActionButton {
                        objectName: "agentStart"
                        visible: !Agents.busy
                        text: "Start task"
                        kind: "primary"
                        enabled: taskInput.text.trim() !== "" && taskInput.text.length <= 4000
                        onClicked: root.start()
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: root.notice !== "" || Agents.busy
                    text: Agents.busy ? Agents.running + " is working." : root.notice
                    textFormat: Text.PlainText
                    font: Theme.type.callout
                    color: Agents.busy ? Theme.textSecondary : Theme.danger
                    wrapMode: Text.Wrap
                }
            }

            AgentRoster {
                objectName: "agentPipeline"
                Layout.fillWidth: true
            }

            // -- the answer ----------------------------------------------------------
            Card {
                visible: !Agents.busy && Agents.answer !== ""
                Text {
                    text: Agents.ok ? "Result" : ({cancelled: "Stopped", budget: "Budget reached", failed: "Couldn’t finish"})[Agents.stopped] || "Stopped"
                    textFormat: Text.PlainText
                    font: Theme.type.headline
                    color: Agents.ok ? Theme.textPrimary : Theme.danger
                }
                Text {
                    Layout.fillWidth: true
                    text: root.lastRunName + (root.lastRunProject ? " · " + root.lastRunProject : "")
                    textFormat: Text.PlainText
                    font: Theme.type.caption
                    color: Theme.textSecondary
                    wrapMode: Text.Wrap
                }
                MessageBody {
                    onLinkActivated: function (url) { Links.ask(url); }
                    Layout.fillWidth: true
                    content: Agents.answer
                    isError: !Agents.ok
                }
            }

            // -- the record ----------------------------------------------------------
            Card {
                objectName: "agentRecord"
                visible: AgentTrace.events.count > 0
                RowLayout {
                    Layout.fillWidth: true
                    SectionLabel { Layout.fillWidth: true; text: "Activity · " + AgentTrace.events.count }
                    ActionButton { text: root.showRecord ? "Hide" : "Show"; onClicked: root.showRecord = !root.showRecord }
                    ActionButton {
                        visible: AgentTrace.events.count > 0 && !Agents.busy
                        text: "Clear"
                        onClicked: { AgentTrace.clear() }
                    }
                }
                Text {
                    visible: root.showRecord && AgentTrace.events.count === 0
                    text: "No activity"
                    font: Theme.type.caption
                    color: Theme.textTertiary
                }
                Repeater {
                    model: root.showRecord ? AgentTrace.events : null
                    RowLayout {
                        id: step
                        required property var model
                        Layout.fillWidth: true
                        spacing: Theme.space.sm
                        Text {
                            Layout.alignment: Qt.AlignTop
                            text: Qt.formatTime(new Date(step.model.at * 1000), "hh:mm:ss")
                            textFormat: Text.PlainText
                            font: Theme.type.monoSmall
                            color: Theme.textTertiary
                        }
                        Text {
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredWidth: 84
                            text: step.model.agent
                            textFormat: Text.PlainText
                            font: Theme.type.captionStrong
                            color: Theme.textPrimary
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: {
                                var m = step.model;
                                var head = m.kind === "tool_call" ? "uses " + m.tool
                                         : m.kind === "tool_result" ? (m.ok ? "got " : "was refused ") + (m.tool || "")
                                         : m.kind === "message" ? "hands over to " + m.recipient
                                         : m.kind;
                                return head + (m.text ? ": " + m.text : "");
                            }
                            textFormat: Text.PlainText
                            font: Theme.type.caption
                            color: step.model.ok === false ? Theme.danger : Theme.textSecondary
                            wrapMode: Text.Wrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: Theme.space.xxl }
        }
    }
}
