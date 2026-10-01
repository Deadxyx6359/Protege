import QtQuick
import QtQuick.Layouts

// Read the run's marshalled state, not a truncated trace of older runs.
Item {
    id: root
    readonly property var run: Agents.currentRun
    readonly property var live: AgentTrace.activity
    implicitHeight: rows.implicitHeight

    function activity(name) {
        const state = (run.states || {})[name];
        const observed = live[name];
        if (!state) return observed ? observed.label : "Idle";
        if (run.status !== "running" && observed && observed.at > (run.ended || 0)) return observed.label;
        if (state === "Waiting" && run.status !== "running") return "Not run";
        return state;
    }

    function working(name) {
        const observed = live[name];
        const state = (run.states || {})[name];
        if (!state || (run.status !== "running" && observed && observed.at > (run.ended || 0)))
            return observed ? observed.working : false;
        return run.status === "running" && ["Waiting", "Done", "Failed"].indexOf(state) < 0;
    }

    GridLayout {
        id: rows
        width: parent.width
        columns: width >= 480 ? 2 : 1
        columnSpacing: 20
        rowSpacing: 0
        Repeater {
            model: Agents.roles
            RowLayout {
                id: agent
                required property var modelData
                readonly property string activity: root.activity(modelData.name)
                readonly property bool working: root.working(modelData.name)
                objectName: "agentRow_" + modelData.name
                Layout.fillWidth: true
                Layout.preferredHeight: 52
                spacing: 10
                Rectangle {
                    Layout.preferredWidth: 6
                    Layout.preferredHeight: 6
                    radius: 3
                    color: agent.working ? Theme.accent
                         : ["Failed", "Incomplete", "Tool declined"].indexOf(agent.activity) >= 0 ? Theme.danger
                         : agent.activity === "Done" ? Theme.success : Theme.textTertiary
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        Layout.fillWidth: true
                        text: agent.modelData.name.charAt(0).toUpperCase() + agent.modelData.name.slice(1)
                        textFormat: Text.PlainText
                        font: Theme.type.captionStrong
                        color: Theme.textPrimary
                        elide: Text.ElideRight
                    }
                    Text {
                        objectName: "agentActivity_" + agent.modelData.name
                        Layout.fillWidth: true
                        text: agent.activity.replace(/_/g, " ")
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: agent.working ? Theme.accent : Theme.textSecondary
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
