import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts
import QtQuick.Window
import "modelnames.js" as ModelNames

Item {
    id: root
    property string selectedId: ""
    property var selectedRun: ({})
    property string notice: ""
    property bool showActivity: false
    property bool confirmingDelete: false
    property alias taskDraft: taskInput.text
    property var drafts: ({})
    property string draftProject: Projects.currentId
    readonly property var project: Projects.projects.find(function (p) { return p.current; }) || ({})
    readonly property string folder: project.folder || ""
    readonly property var saved: Agents.runs.filter(function (r) {
        return r.kind === "team" && r.name === "research" && r.projectId === Projects.currentId;
    })
    readonly property bool hasRun: !!selectedRun.id
    readonly property bool running: hasRun && selectedRun.status === "running"
    readonly property var stages: [
        {name: "gatherer", label: "Gather", detail: "Find material", icon: "search"},
        {name: "analyst", label: "Analyze", detail: "Connect evidence", icon: "document"},
        {name: "critic", label: "Challenge", detail: "Check reasoning", icon: "eye"},
        {name: "writer", label: "Synthesize", detail: "Write findings", icon: "sparkle"}
    ]
    signal sourceRequested(string error)
    signal permissionsRequested()
    signal artifactRequested(var artifact)

    function refresh() {
        selectedRun = selectedId ? Agents.record(selectedId) : ({});
        if (selectedId && !selectedRun.id) selectedId = "";
    }
    function choose(id) {
        selectedId = id; refresh(); showActivity = false; confirmingDelete = false; notice = "";
        Qt.callLater(function () { scroller.contentItem.contentY = 0; });
    }
    function prepare(text) {
        choose("");
        if (text.trim()) taskInput.text = text;
        Qt.callLater(function () { taskInput.forceActiveFocus(); });
    }
    function start() {
        if (Agents.busy || Chat.busy) return;
        notice = Agents.runTeam("research", taskInput.text, root.folder);
        if (!notice) { choose(Agents.currentRun.id); taskInput.text = ""; }
    }
    function statusLabel(status) {
        return ({running: "In progress", complete: "Complete", stopped: "Stopped", incomplete: "Incomplete", interrupted: "Interrupted"})[status] || status;
    }
    function revealFocus() {
        const item = root.Window.window ? root.Window.window.activeFocusItem : null;
        if (!item || !root.visible) return;
        var ancestor = item;
        while (ancestor && ancestor !== scroller) ancestor = ancestor.parent;
        if (!ancestor) return;
        const viewport = scroller.contentItem;
        const y = item.mapToItem(viewport.contentItem, 0, 0).y;
        if (y < viewport.contentY) viewport.contentY = Math.max(0, y - 12);
        else if (y + item.height > viewport.contentY + viewport.height)
            viewport.contentY = Math.max(0, Math.min(viewport.contentHeight - viewport.height, y + item.height - viewport.height + 12));
    }
    Connections { target: root.Window.window; function onActiveFocusItemChanged() { root.revealFocus(); } }
    Connections { target: Agents; function onRunsChanged() { root.refresh(); } }
    Connections {
        target: Projects
        function onCurrentChanged() {
            const saved = Object.assign({}, root.drafts);
            saved[root.draftProject] = taskInput.text;
            root.drafts = saved; root.draftProject = Projects.currentId;
            taskInput.text = root.drafts[root.draftProject] || "";
            root.choose("");
        }
    }

    component Copy: Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font: Theme.type.callout
        color: Theme.textSecondary
    }
    // Rectangle respects the software renderer's nested scroll clipping.
    component Card: Rectangle {
        default property alias content: inner.data
        Layout.fillWidth: true
        implicitHeight: inner.implicitHeight + 36
        radius: Theme.radius.lg
        color: Theme.canvas
        border.color: Theme.separatorStrong
        ColumnLayout {
            id: inner
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 18 }
            spacing: 14
        }
    }

    C.ScrollView {
        id: scroller
        objectName: "investigationScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: Math.min(900, scroller.availableWidth - 48)
            x: (scroller.availableWidth - width) / 2
            spacing: 16

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 8
                Text { text: "Investigations"; font: Theme.type.title2; color: Theme.textPrimary }
                Item { Layout.fillWidth: true }
                Text { text: root.saved.length + " saved"; textFormat: Text.PlainText; font: Theme.type.caption; color: Theme.textSecondary }
            }
            Select {
                objectName: "investigationHistory"
                Layout.fillWidth: true
                visible: root.saved.length > 0
                label: "Saved research investigations in this project"
                current: root.selectedId
                options: [{value: "", label: "New investigation", detail: "Prepare an editable question"}].concat(root.saved.map(function (r) {
                    return {value: r.id, label: r.task.replace(/\s+/g, " ").slice(0, 100),
                            detail: root.statusLabel(r.status) + " · " + Qt.formatDateTime(new Date(r.started * 1000), "MMM d, h:mm AP")};
                }))
                onPicked: function (id) { root.choose(id); }
            }
            Copy {
                visible: !root.hasRun
                text: "Follow a question from evidence to a considered answer. Four specialists work in sequence, using the sources you allow."
            }
            Copy {
                visible: !!Agents.historyError
                text: Agents.historyError
                color: Theme.danger
            }
            Copy { visible: !!root.notice; text: root.notice; color: Theme.danger }

            Card {
                visible: !root.hasRun
                Copy { text: "YOUR QUESTION"; font: Theme.type.captionStrong; color: Theme.accent }
                C.ScrollView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 112
                    C.TextArea {
                        id: taskInput
                        objectName: "investigationTask"
                        textFormat: TextEdit.PlainText
                        placeholderText: "What would you like to understand? Include the scope, useful sources and the kind of answer you need."
                        placeholderTextColor: Theme.textTertiary
                        color: Theme.textPrimary
                        font: Theme.type.body
                        wrapMode: TextEdit.Wrap
                        selectByMouse: true
                        readOnly: Agents.busy
                        Accessible.name: "Research question"
                        background: Rectangle {
                            radius: Theme.radius.sm
                            color: Theme.surface
                            border.color: taskInput.activeFocus ? Theme.accent : Theme.separator
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Copy {
                        text: root.folder ? "Project folder · " + root.folder : "No project folder · uses your permitted sources"
                        font: Theme.type.caption
                        elide: Text.ElideMiddle
                        maximumLineCount: 1
                    }
                    Text {
                        text: taskInput.text.length + " / 4000"
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: taskInput.text.length > 4000 ? Theme.danger : Theme.textTertiary
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ActionButton { text: "Source permissions"; onClicked: root.permissionsRequested() }
                    Item { Layout.fillWidth: true }
                    ActionButton {
                        objectName: "investigationStart"
                        text: "Start investigation"
                        kind: "primary"
                        enabled: !Agents.busy && !Chat.busy && taskInput.text.trim().length > 0 && taskInput.text.length <= 4000
                        onClicked: root.start()
                    }
                }
                Copy {
                    visible: Agents.busy || Chat.busy
                    text: Agents.busy ? Agents.running + " is working. You can review saved findings while it finishes." : "Finish or stop the conversation before starting a team."
                    font: Theme.type.caption
                }
            }

            Card {
                visible: root.hasRun
                RowLayout {
                    Layout.fillWidth: true
                    Rectangle { width: 6; height: 6; radius: 3; color: root.selectedRun.status === "complete" ? Theme.accent : Theme.textSecondary }
                    Copy {
                        text: root.statusLabel(root.selectedRun.status || "") + (root.selectedRun.started ? " · " + Qt.formatDateTime(new Date(root.selectedRun.started * 1000), "MMM d, h:mm AP") : "")
                        font: Theme.type.captionStrong
                    }
                    ActionButton { visible: root.running; text: "Stop"; onClicked: Agents.stop() }
                    ActionButton { visible: !root.running; text: "New inquiry"; onClicked: root.prepare("") }
                }
                Copy { objectName: "investigationQuestion"; text: root.selectedRun.task || ""; font: Theme.type.headline; color: Theme.textPrimary }
                Copy {
                    text: root.selectedRun.projectName || ""
                    font: Theme.type.caption
                }
            }

            GridLayout {
                objectName: "investigationStages"
                Layout.fillWidth: true
                columns: width > 680 ? 4 : 2
                columnSpacing: 10; rowSpacing: 10
                Repeater {
                    model: root.stages
                    Rectangle {
                        id: stage
                        required property var modelData
                        readonly property string state: root.hasRun ? ((root.selectedRun.states || ({}))[modelData.name] || "Waiting") : modelData.detail
                        readonly property bool active: root.running && state !== "Waiting" && state !== "Done" && state !== "Failed"
                        Layout.fillWidth: true
                        implicitWidth: 120
                        implicitHeight: 66
                        radius: Theme.radius.md
                        color: active ? Theme.accentSubtle : Theme.surface
                        border.color: active ? Theme.accent : Theme.separator
                        Behavior on color { ColorAnimation { duration: Theme.duration.fast } }
                        RowLayout {
                            anchors.fill: parent; anchors.margins: 12; spacing: 10
                            Icon { name: stage.modelData.icon; size: 17; color: stage.active || stage.state === "Done" ? Theme.accent : Theme.textSecondary }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Text { text: stage.modelData.label; textFormat: Text.PlainText; font: Theme.type.captionStrong; color: Theme.textPrimary }
                                Text { Layout.fillWidth: true; text: stage.state; textFormat: Text.PlainText; font: Theme.type.caption; color: Theme.textSecondary; elide: Text.ElideRight }
                            }
                        }
                    }
                }
            }

            Card {
                visible: root.hasRun
                Copy { text: root.running ? "Following the evidence…" : "Findings"; font: Theme.type.title3; color: Theme.textPrimary }
                Copy {
                    visible: root.running
                    text: "The final synthesis will appear here. You can leave this view and return while the team works."
                }
                Copy {
                    visible: !root.running && !root.selectedRun.answer
                    text: root.selectedRun.status === "interrupted" ? "Akira closed before this run returned a result. Start a new inquiry to try again." : "This run ended without a final answer. Its progress and gathered references are retained below."
                }
                MessageBody { objectName: "investigationAnswer"; onLinkActivated: function (url) { Links.ask(url); } Layout.fillWidth: true; visible: !root.running && !!root.selectedRun.answer; content: root.selectedRun.answer || ""; isError: root.selectedRun.status !== "complete" }
            }
            Card {
                visible: root.hasRun
                RowLayout {
                    Layout.fillWidth: true
                    Copy { text: "Gathered material"; font: Theme.type.headline; color: Theme.textPrimary }
                    Text { text: (root.selectedRun.sources || []).length + " / 32"; textFormat: Text.PlainText; font: Theme.type.caption; color: Theme.textTertiary }
                }
                Copy {
                    font: Theme.type.caption
                    text: (root.selectedRun.sources || []).length ? "Material returned by read tools. Search results are snippets; these references are not a claim that every source was cited or verified." : "No source material recorded yet. A result without sources has not been verified against external evidence."
                }
                Repeater {
                    model: root.selectedRun.sources || []
                    C.AbstractButton {
                        id: sourceRow
                        required property var modelData
                        required property int index
                        objectName: "investigationSource" + index
                        Layout.fillWidth: true
                        implicitHeight: 72
                        hoverEnabled: true
                        Accessible.name: modelData.kind + ": " + modelData.title + ". Preview gathered text"
                        background: Rectangle { radius: Theme.radius.sm; color: sourceRow.hovered ? Theme.surfaceHover : Theme.surface; border.color: sourceRow.activeFocus ? Theme.accent : Theme.separator }
                        contentItem: RowLayout {
                            spacing: 12
                            Icon { Layout.leftMargin: 12; name: sourceRow.modelData.kind === "File read" ? "document" : "search"; size: 17; color: Theme.accent }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Text { Layout.fillWidth: true; text: sourceRow.modelData.title; textFormat: Text.PlainText; font: Theme.type.callout; color: Theme.textPrimary; elide: Text.ElideRight }
                                Text { Layout.fillWidth: true; text: sourceRow.modelData.kind + " · " + sourceRow.modelData.locator; textFormat: Text.PlainText; font: Theme.type.caption; color: Theme.textSecondary; elide: Text.ElideMiddle }
                            }
                            Icon { Layout.rightMargin: 12; name: "chevronRight"; size: 13; color: Theme.textTertiary }
                        }
                        onClicked: root.sourceRequested(Agents.previewSource(root.selectedId, modelData.id))
                    }
                }
            }
            RowLayout {
                visible: root.hasRun
                Layout.fillWidth: true
                ActionButton { text: root.showActivity ? "Hide activity" : "Run activity"; onClicked: root.showActivity = !root.showActivity }
                Item { Layout.fillWidth: true }
                ActionButton { visible: !root.running && !root.confirmingDelete; text: "Remove result"; enabled: !Agents.archiveBusy; onClicked: root.confirmingDelete = true }
            }
            RunArtifacts { Layout.fillWidth: true; run: root.selectedRun; onArtifactRequested: function (artifact) { root.artifactRequested(artifact); } }
            Card {
                visible: root.hasRun && root.showActivity
                Copy { text: "Model assignments at start"; font: Theme.type.headline; color: Theme.textPrimary }
                Repeater {
                    model: root.selectedRun.members || []
                    Copy {
                        required property var modelData
                        readonly property var assigned: (root.selectedRun.models || ({}))[modelData] || ({})
                        text: modelData + " · " + ModelNames.display(assigned.label) + (assigned.route ? " · " + assigned.route : "")
                        font: Theme.type.caption
                    }
                }
                Copy { text: "Tool calls and team handoffs"; font: Theme.type.headline; color: Theme.textPrimary }
                Copy { text: "Latest 80 steps. Intermediate model messages are not saved here."; font: Theme.type.caption }
                Repeater {
                    model: root.selectedRun.events || []
                    Copy {
                        required property var modelData
                        text: modelData.agent + (modelData.kind === "message" ? " → " + modelData.to
                             : modelData.kind === "tool_call" ? " · Called " + modelData.tool
                             : modelData.kind === "tool_result" ? (modelData.ok === false ? " · Declined or failed: " : " · Returned from ") + modelData.tool : " · Stopped")
                        font: Theme.type.caption
                    }
                }
            }
            Card {
                visible: root.confirmingDelete && !root.running && root.hasRun
                Copy { text: "Remove this saved question, result and source references? This does not delete the underlying files or audit log." }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    ActionButton { text: "Keep"; onClicked: root.confirmingDelete = false }
                    ActionButton { objectName: "investigationDelete"; text: "Remove result"; kind: "danger"; enabled: !Agents.archiveBusy; onClicked: root.notice = Agents.deleteRun(root.selectedId) }
                }
            }
            Copy { Layout.bottomMargin: 20; text: "Saved on this device · Keeps the latest 60 interactive runs across teams. Source previews stay in memory only."; font: Theme.type.caption; color: Theme.textTertiary }
        }
    }
}
