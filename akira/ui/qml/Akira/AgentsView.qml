import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import QtQuick.Layouts

/*!
    Agents at work: who is on each team, what each may touch, and a run as it
    happens.

    A team runs its members in order, each handing its work to the next, so it
    is drawn as a line of members with the hand-offs between them. The one
    working now is lit, a finished one is ticked, and every tool call, result
    and hand-off appears in the record beneath as it happens (\c AgentTrace).

    Nothing here grants anything. An agent reaches only what the permission
    screen allows, and an irreversible step still stops at the confirmation
    dialog, whoever started it.
*/
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

    // What the record says, redrawn whenever it grows.
    property var status: ({})
    property var doing: ({})
    property var passed: ({})

    function role(name) {
        for (var i = 0; i < Agents.roles.length; i++)
            if (Agents.roles[i].name === name)
                return Agents.roles[i];
        return null;
    }

    function titled(name) { return name.charAt(0).toUpperCase() + name.slice(1); }

    function refresh() {
        var events = AgentTrace.recent(300);
        var status = {}, doing = {}, passed = {};
        for (var i = 0; i < events.length; i++) {
            var e = events[i];
            if (e.kind === "started") { status[e.agent] = "working"; doing[e.agent] = "Starting"; }
            else if (e.kind === "answer") { status[e.agent] = "done"; doing[e.agent] = ""; }
            else if (e.kind === "failed") { status[e.agent] = "failed"; doing[e.agent] = ""; }
            else if (e.kind === "tool_call") doing[e.agent] = "Using " + e.tool;
            else if (e.kind === "thinking") doing[e.agent] = "Thinking";
            if (e.kind === "message" && e.recipient)
                passed[e.agent + ">" + e.recipient] = true;
        }
        root.status = status;
        root.doing = doing;
        root.passed = passed;
    }

    function start() {
        var task = taskInput.text.trim();
        if (Agents.busy || !task || task.length > 4000) return;
        AgentTrace.clear();
        root.refresh();
        root.notice = root.isTeam ? Agents.runTeam(root.chosenName, task, root.folder)
                                  : Agents.runAgent(root.chosenName, task, root.folder);
    }

    Connections {
        target: AgentTrace.events
        function onCountChanged() { root.refresh() }
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
    Component.onCompleted: refresh()

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
                    ActionButton { objectName: "agentHistoryButton"; text: "Task history"; onClicked: root.historyRequested() }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Give the work a clear goal. Choose a team to collaborate, or one agent to focus."
                    font: Theme.type.caption
                    color: Theme.textSecondary
                    wrapMode: Text.Wrap
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
                    visible: text !== ""
                    textFormat: Text.PlainText
                    font: Theme.type.callout
                    color: Theme.textPrimary
                    wrapMode: Text.Wrap
                }
            }

            // -- the task ------------------------------------------------------------
            Card {
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
                        text: root.folder === "" ? "No folder: they work where the task points them."
                                                 : root.folder
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
                    Layout.fillWidth: true
                    content: Agents.answer
                    isError: !Agents.ok
                }
            }

            // -- the line of members -------------------------------------------------
            Card {
                objectName: "agentPipeline"
                visible: root.showTeamDetails || Agents.busy

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 150

                    Row {
                        anchors.centerIn: parent
                        spacing: 0

                        Repeater {
                            model: root.members

                            Row {
                                id: stage
                                required property var modelData
                                required property int index
                                readonly property string name: modelData
                                readonly property string phase: root.status[name] || "waiting"
                                spacing: 0

                                // The hand-off from the one before.
                                Item {
                                    id: link
                                    visible: stage.index > 0
                                    width: 64
                                    height: 60
                                    readonly property bool handed: stage.index > 0
                                        && root.passed[root.members[stage.index - 1] + ">" + stage.name] === true
                                    Rectangle {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: parent.width - 10
                                        height: 2
                                        radius: 1
                                        color: link.handed ? Theme.accent : Theme.separatorStrong
                                        Behavior on color { ColorAnimation { duration: Theme.duration.normal } }
                                    }
                                    Icon {
                                        anchors.right: parent.right
                                        anchors.verticalCenter: parent.verticalCenter
                                        name: "chevronRight"
                                        size: 14
                                        color: link.handed ? Theme.accent : Theme.textTertiary
                                    }
                                }

                                Column {
                                    width: 118
                                    spacing: Theme.space.xs

                                    Item {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        width: 60
                                        height: 60

                                        // A glow behind the one working now.
                                        Rectangle {
                                            anchors.centerIn: parent
                                            width: 60; height: 60; radius: 30
                                            color: Theme.accent
                                            opacity: stage.phase === "working" ? 0.22 : 0
                                            SequentialAnimation on scale {
                                                running: stage.phase === "working" && Theme.motionScale > 0
                                                loops: Animation.Infinite
                                                NumberAnimation { from: 0.9; to: 1.15; duration: 900; easing.type: Easing.InOutSine }
                                                NumberAnimation { from: 1.15; to: 0.9; duration: 900; easing.type: Easing.InOutSine }
                                            }
                                        }
                                        Rectangle {
                                            anchors.centerIn: parent
                                            width: 46; height: 46; radius: 23
                                            color: stage.phase === "done" ? Theme.success
                                                 : stage.phase === "failed" ? Theme.danger
                                                 : stage.phase === "working" ? Theme.accent : Theme.surfaceActive
                                            border.width: 1
                                            border.color: Theme.separatorStrong
                                            Behavior on color { ColorAnimation { duration: Theme.duration.normal } }
                                            Icon {
                                                anchors.centerIn: parent
                                                name: stage.phase === "done" ? "check"
                                                    : stage.phase === "failed" ? "close" : "user"
                                                size: 18
                                                color: stage.phase === "waiting" ? Theme.textSecondary : Theme.textOnAccent
                                            }
                                        }
                                    }

                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: root.titled(stage.name)
                                        textFormat: Text.PlainText
                                        font: Theme.type.captionStrong
                                        color: Theme.textPrimary
                                    }
                                    Text {
                                        width: parent.width
                                        horizontalAlignment: Text.AlignHCenter
                                        text: root.doing[stage.name] || (stage.phase === "done" ? "Done"
                                              : stage.phase === "failed" ? "Stopped" : "Waiting")
                                        textFormat: Text.PlainText
                                        font: Theme.type.caption
                                        color: Theme.textTertiary
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                }

                // What each member may touch, at most: the permissions decide.
                Repeater {
                    model: root.members
                    RowLayout {
                        id: member
                        required property var modelData
                        readonly property var spec: root.role(modelData)
                        Layout.fillWidth: true
                        spacing: Theme.space.sm
                        Text {
                            Layout.preferredWidth: 100
                            Layout.alignment: Qt.AlignTop
                            text: root.titled(member.modelData)
                            textFormat: Text.PlainText
                            font: Theme.type.captionStrong
                            color: Theme.textPrimary
                        }
                        Text {
                            Layout.fillWidth: true
                            text: member.spec ? member.spec.summary + (member.spec.tools.length
                                  ? " May use: " + member.spec.tools.join(", ") + "."
                                  : " Uses no tools.") : ""
                            textFormat: Text.PlainText
                            font: Theme.type.caption
                            color: Theme.textSecondary
                            wrapMode: Text.Wrap
                        }
                    }
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
                        onClicked: { AgentTrace.clear(); root.refresh() }
                    }
                }
                Text {
                    visible: root.showRecord && AgentTrace.events.count === 0
                    text: "Nothing yet. Every step of a run appears here as it happens."
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
