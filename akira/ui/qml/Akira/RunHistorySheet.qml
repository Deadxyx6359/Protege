import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts
import "modelnames.js" as ModelNames

Sheet {
    id: root
    title: root.teamFilter === "software" ? "Software task history" : "Task history"
    subtitle: root.allProjects ? "All projects" : Projects.currentName || "Personal workspace"
    sheetWidth: 900
    sheetMaxHeight: Math.round(parent.height * 0.9)
    property string teamFilter: ""
    property bool allProjects: false
    property string selectedId: ""
    property var selectedRun: ({})
    property string notice: ""
    property bool confirmingDelete: false
    signal artifactRequested(var artifact)
    readonly property var saved: Agents.runs.filter(function (r) {
        return (root.allProjects || r.projectId === Projects.currentId)
            && (!root.teamFilter || r.name === root.teamFilter || (root.teamFilter === "software" && ["architect", "implementer", "reviewer"].indexOf(r.name) >= 0));
    })
    function refresh() {
        if (!saved.some(function (r) { return r.id === root.selectedId; }))
            selectedId = saved.length ? saved[0].id : "";
        selectedRun = selectedId ? Agents.record(selectedId) : ({});
    }
    function present(team) {
        teamFilter = team; allProjects = false; selectedId = ""; notice = ""; confirmingDelete = false;
        refresh(); open();
    }
    function choose(id) { selectedId = id; confirmingDelete = false; notice = ""; refresh(); }
    Connections { target: Agents; function onRunsChanged() { if (root.opened) root.refresh(); } }
    Connections { target: Projects; function onCurrentChanged() { if (root.opened) root.close(); } }
    component Copy: Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font: Theme.type.callout
        color: Theme.textSecondary
    }
    ColumnLayout {
        width: parent.width
        spacing: 14
        RowLayout {
            Layout.fillWidth: true
            Copy { text: root.saved.length + (root.saved.length === 1 ? " saved run" : " saved runs"); font: Theme.type.caption }
            ActionButton {
                text: root.allProjects ? "This project" : "All projects"
                onClicked: { root.allProjects = !root.allProjects; root.confirmingDelete = false; root.refresh(); }
            }
        }
        Copy { visible: !!Agents.historyError || !!root.notice; text: root.notice || Agents.historyError; color: Theme.danger }
        Select {
            objectName: "taskHistoryPicker"
            Layout.fillWidth: true
            visible: root.saved.length > 0
            current: root.selectedId
            label: "Saved task"
            options: root.saved.map(function (r) {
                return {value: r.id, label: r.task.replace(/\s+/g, " ").slice(0, 100),
                        detail: r.name + " · " + r.status + " · " + Qt.formatDateTime(new Date(r.started * 1000), "MMM d, h:mm AP")};
            })
            onPicked: function (id) { root.choose(id); }
        }
        Copy {
            visible: !root.saved.length
            text: "No saved tasks here yet. Team and individual-agent results will appear after you start work."
        }
        Copy { visible: !!root.selectedRun.id; text: root.selectedRun.task || ""; font: Theme.type.headline; color: Theme.textPrimary }
        Copy {
            visible: !!root.selectedRun.id
            text: (root.selectedRun.name || "") + " · " + (root.selectedRun.projectName || "") + " · " + (root.selectedRun.status || "")
            font: Theme.type.caption
        }
        Copy {
            visible: !!root.selectedRun.folder
            text: root.selectedRun.folder || ""
            font: Theme.type.caption
        }
        GridLayout {
            Layout.fillWidth: true
            columns: width > 650 ? 3 : 2
            columnSpacing: 10; rowSpacing: 10
            Repeater {
                model: root.selectedRun.members || []
                Rectangle {
                    id: member
                    required property var modelData
                    readonly property var assigned: (root.selectedRun.models || ({}))[modelData] || ({})
                    Layout.fillWidth: true
                    implicitHeight: 82
                    radius: Theme.radius.sm
                    color: Theme.surface
                    border.color: Theme.separator
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 12; spacing: 3
                        Text { text: member.modelData; textFormat: Text.PlainText; font: Theme.type.captionStrong; color: Theme.textPrimary }
                        Text { text: (root.selectedRun.states || ({}))[member.modelData] || "Waiting"; textFormat: Text.PlainText; font: Theme.type.caption; color: text === "Done" ? Theme.accent : Theme.textSecondary }
                        Text { Layout.fillWidth: true; text: ModelNames.display(member.assigned.label); textFormat: Text.PlainText; font: Theme.type.caption; color: Theme.textSecondary; elide: Text.ElideRight }
                    }
                }
            }
        }
        Copy {
            visible: !!root.selectedRun.id
            text: "Model labels reflect the assignments when this task started."
            font: Theme.type.caption
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.separator; visible: !!root.selectedRun.id }
        MessageBody {
            objectName: "taskHistoryAnswer"
            Layout.fillWidth: true
            content: root.selectedRun.answer || ""
            isError: root.selectedRun.status !== "complete"
        }
        Copy {
            visible: !!root.selectedRun.id && !root.selectedRun.answer
            text: root.selectedRun.status === "running" ? "This task is still working. Its result will appear here." : "This task ended without a final answer. Start another task to try again."
        }
        RowLayout {
            Layout.fillWidth: true
            visible: !!root.selectedRun.id && !root.confirmingDelete
            Item { Layout.fillWidth: true }
            ActionButton { visible: root.selectedRun.status === "running"; text: "Stop task"; onClicked: Agents.stop() }
            ActionButton { visible: root.selectedRun.status !== "running"; text: "Remove result"; enabled: !Agents.archiveBusy; onClicked: root.confirmingDelete = true }
        }
        RunArtifacts {
            Layout.fillWidth: true
            run: root.selectedRun
            onArtifactRequested: function (artifact) { root.artifactRequested(artifact); }
        }
        Copy {
            visible: root.confirmingDelete
            text: "Remove this saved task and result? Project files and the audit log will remain."
        }
        RowLayout {
            visible: root.confirmingDelete
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ActionButton { text: "Keep"; onClicked: root.confirmingDelete = false }
            ActionButton { objectName: "taskHistoryDelete"; text: "Remove result"; kind: "danger"; enabled: !Agents.archiveBusy; onClicked: { root.notice = Agents.deleteRun(root.selectedId); root.confirmingDelete = false; } }
        }
        Copy { text: "Stored on this device. The latest 60 interactive runs are kept across teams. Scheduled jobs remain in Schedule."; font: Theme.type.caption }
    }
}
