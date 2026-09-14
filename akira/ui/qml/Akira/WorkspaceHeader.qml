import QtQuick
import QtQuick.Layouts

// One persistent place for project context. Workspace navigation lives in the
// sidebar; when the sidebar is hidden, this header exposes the same choices.
Rectangle {
    id: root
    property var destinations: []
    property var counts: ({})
    property var projects: []
    property string currentView: "chats"
    property string currentProject: ""
    property bool sidebarOpen: true
    property bool projectSwitchingEnabled: true
    readonly property var destination: destinations.find(function (d) { return d.id === root.currentView; }) || ({})
    readonly property bool globalContext: ["watching", "schedule", "memory"].indexOf(currentView) >= 0
    signal viewSelected(string id)
    signal projectSelected(string id)
    signal newProjectRequested()
    signal manageProjectRequested()
    signal sidebarRequested()
    signal permissionsRequested()
    signal appearanceRequested()
    signal settingsRequested()

    implicitHeight: 68
    color: Theme.surface
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.separator }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 20
        anchors.rightMargin: 16
        spacing: 8
        IconButton {
            objectName: "showSidebar"
            visible: !root.sidebarOpen
            icon: "sidebar"; label: "Show sidebar"
            onClicked: root.sidebarRequested()
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 105
            spacing: 2
            RowLayout {
                visible: root.sidebarOpen
                spacing: 8
                Icon { name: root.destination.icon || "chat"; size: 16; color: Theme.accent }
                Text {
                    text: root.destination.label || "Workspace"
                    textFormat: Text.PlainText
                    font: Theme.type.headline
                    color: Theme.textPrimary
                }
            }
            Select {
                objectName: "collapsedWorkspacePicker"
                Layout.preferredWidth: 156
                visible: !root.sidebarOpen
                label: "Workspace"
                minimumPopupWidth: 290
                current: root.currentView
                options: root.destinations.map(function (d) {
                    const count = root.counts[d.id] || 0;
                    return {value: d.id, label: d.label, detail: count ? count + " " + (d.countLabel || "item") + (count === 1 ? "" : "s") : ""};
                })
                onPicked: function (value) { root.viewSelected(value) }
            }
            Text {
                objectName: "workspaceScope"
                Layout.fillWidth: true
                text: root.globalContext ? "Global permissions" : root.currentProject ? "Project context" : "Personal workspace"
                textFormat: Text.PlainText
                elide: Text.ElideRight
                font: Theme.type.caption
                color: Theme.textSecondary
            }
        }
        ColumnLayout {
            Layout.preferredWidth: Math.min(236, root.width * 0.29)
            Layout.minimumWidth: 150
            Layout.maximumWidth: 260
            spacing: 3
            Text { text: "Active project"; font: Theme.type.caption; color: Theme.textSecondary }
            Select {
                objectName: "activeProjectPicker"
                Layout.fillWidth: true
                enabled: root.projectSwitchingEnabled
                label: "Active project"
                current: root.currentProject
                options: [{value: "", label: "Personal workspace"}].concat(root.projects.map(function (p) {
                    return {value: p.id, label: p.name};
                })).concat([{value: "__create_project__", label: "New project…"}])
                onPicked: function (value) {
                    if (value === "__create_project__") root.newProjectRequested();
                    else root.projectSelected(value);
                }
            }
        }
        ActionButton {
            objectName: "manageActiveProject"
            Layout.alignment: Qt.AlignBottom
            Layout.bottomMargin: 10
            text: "Manage"
            implicitWidth: 74
            visible: !!root.currentProject
            Accessible.name: "Manage active project"
            onClicked: root.manageProjectRequested()
        }
        IconButton { objectName: "openPermissions"; icon: "shield"; onClicked: root.permissionsRequested() }
        IconButton { icon: Theme.isDark ? "sun" : "moon"; onClicked: root.appearanceRequested() }
        IconButton { visible: !root.sidebarOpen; icon: "settings"; onClicked: root.settingsRequested() }
    }
}
