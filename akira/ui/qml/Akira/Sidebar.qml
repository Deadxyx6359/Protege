import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

/*!
    The navigation rail.

    Deliberately shallow: a handful of destinations, your projects, and what
    you were last working on. Everything else is reachable from where it is
    used rather than from a list of every feature the application has — the
    old sidebar listed thirteen rows, which is a menu bar wearing a sidebar's
    clothes.

    Models arrive as plain arrays so this file has no idea where the data comes
    from; Python replaces them later without touching the layout.
*/
Item {
    id: root
    property var navCounts: ({})

    /*! [{ id, icon, label }] — the fixed destinations. */
    property var navModel: []
    /*! [{ id, name, color }] */
    property var projectModel: []
    /*! [{ id, title, when }] */
    property var recentModel: []

    property string currentNav: ""
    property string currentProject: ""
    property string currentRecent: ""
    property bool newChatEnabled: true
    property alias searchText: search.text
    property var contentMatches: null
    property bool searchBusy: false
    property string searchNote: ""
    readonly property bool searchPending: searchDelay.running || searchBusy
    readonly property string query: searchText.trim().toLowerCase()
    readonly property bool searching: query.length > 0
    readonly property var navGroups: {
        var names = [];
        navModel.forEach(function (d) { if (names.indexOf(d.group || "Workspaces") < 0) names.push(d.group || "Workspaces"); });
        return names;
    }
    readonly property var filteredProjects: searching ? projectModel.filter(function (p) {
        return String(p.name || "").toLowerCase().indexOf(root.query) !== -1;
    }) : projectModel
    readonly property var filteredRecents: searching && contentMatches !== null ? contentMatches : searching ? recentModel.filter(function (r) {
        return String(r.title || "").toLowerCase().indexOf(root.query) !== -1;
    }) : recentModel

    function openFirstMatch() {
        if (!searching || searchPending) return;
        if (filteredProjects.length > 0) projectSelected(filteredProjects[0].id);
        else if (filteredRecents.length > 0) recentSelected(filteredRecents[0].id);
        else return;
        searchText = "";
    }

    signal navSelected(string id)
    signal projectSelected(string id)
    signal recentSelected(string id)
    signal newChatRequested()
    signal newProjectRequested()
    signal settingsRequested()
    signal collapseRequested()
    signal searchRequested(string query)
    signal searchInvalidated()
    onQueryChanged: {
        searchInvalidated();
        if (root.query.length > 0 && contentMatches !== null) searchDelay.restart();
        else searchDelay.stop();
    }
    Timer { id: searchDelay; interval: 180; onTriggered: root.searchRequested(root.query) }

    implicitWidth: 264

    Rectangle {
        anchors.fill: parent
        color: Theme.surface

        Behavior on color {
            ColorAnimation { duration: Theme.duration.slow }
        }
    }

    // A hairline rather than a border: the sidebar and the content area differ
    // in tone already, and a full-strength divider on top of that reads as two
    // applications side by side.
    Rectangle {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 1
        color: Theme.separator
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // -- brand ----------------------------------------------------------

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 64
            Layout.leftMargin: Theme.space.md
            Layout.rightMargin: Theme.space.sm
            spacing: Theme.space.sm

            BrandMark {
                size: 36
                Accessible.ignored: true // The adjacent wordmark supplies the name.
            }

            Text {
                Layout.fillWidth: true
                text: "Akira"
                font: Theme.type.title3
                color: Theme.textPrimary
            }

            IconButton {
                icon: "sidebar"
                label: "Hide sidebar"
                iconSize: 17
                onClicked: root.collapseRequested()
            }
        }

        // -- search ---------------------------------------------------------

        SearchField {
            id: search
            objectName: "workspaceSearch"
            placeholder: "Find projects or chats"
            maximumLength: 200
            onAccepted: root.openFirstMatch()
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space.md
            Layout.rightMargin: Theme.space.md
            Layout.bottomMargin: Theme.space.sm
        }

        // -- new chat -------------------------------------------------------

        ActionButton {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space.sm
            Layout.rightMargin: Theme.space.sm
            Layout.preferredHeight: 36
            text: "New chat"
            enabled: root.newChatEnabled
            icon: "plus"
            kind: "primary"
            onClicked: root.newChatRequested()
        }

        // -- scrolling body -------------------------------------------------

        C.ScrollView {
            // Isolate vector icon painting inside the scroll viewport, including
            // the Qt software renderer used on machines without GPU rendering.
            layer.enabled: true
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.topMargin: Theme.space.md
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: root.width
                spacing: 0

                Repeater {
                    model: root.searching ? [] : root.navGroups
                    ColumnLayout {
                        id: group
                        required property string modelData
                        required property int index
                        Layout.fillWidth: true
                        Layout.topMargin: index ? 18 : 0
                        spacing: 0
                        SectionLabel {
                            Layout.leftMargin: Theme.space.md
                            Layout.bottomMargin: Theme.space.xs
                            text: group.modelData
                        }
                        Repeater {
                            model: root.navModel.filter(function (d) { return (d.group || "Workspaces") === group.modelData; })
                            NavRow {
                                required property var modelData
                                readonly property int count: root.navCounts[modelData.id] || 0
                                objectName: "nav_" + modelData.id
                                Layout.fillWidth: true
                                Layout.leftMargin: Theme.space.sm
                                Layout.rightMargin: Theme.space.sm
                                icon: modelData.icon
                                label: modelData.label
                                detail: count > 0 ? (count > 99 ? "99+" : String(count)) : ""
                                detailDescription: count + " " + (modelData.countLabel || "item") + (count === 1 ? "" : "s")
                                detailColor: modelData.id === "schedule" ? Theme.danger : Theme.textSecondary
                                selected: root.currentNav === modelData.id
                                onClicked: root.navSelected(modelData.id)
                            }
                        }
                    }
                }

                SectionLabel {
                    Layout.leftMargin: Theme.space.md
                    Layout.topMargin: Theme.space.lg
                    Layout.bottomMargin: Theme.space.xs
                    text: "Projects"
                    visible: root.searching && root.filteredProjects.length > 0
                }

                Repeater {
                    model: root.searching ? root.filteredProjects : []

                    NavRow {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.space.sm
                        Layout.rightMargin: Theme.space.sm
                        label: modelData.name
                        dotColor: modelData.color
                        selected: root.currentProject === modelData.id
                        onClicked: { root.projectSelected(modelData.id); root.searchText = ""; }
                    }
                }

                SectionLabel {
                    Layout.leftMargin: Theme.space.md
                    Layout.topMargin: Theme.space.lg
                    Layout.bottomMargin: Theme.space.xs
                    text: root.searching ? "Matching chats" : "All recent chats"
                    visible: root.filteredRecents.length > 0
                }

                Repeater {
                    model: root.filteredRecents

                    NavRow {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.space.sm
                        Layout.rightMargin: Theme.space.sm
                        icon: "chat"
                        label: modelData.title
                        subtitle: root.searching ? (modelData.snippet || "") : ""
                        detail: modelData.when
                        selected: root.currentRecent === modelData.id
                        onClicked: { root.recentSelected(modelData.id); root.searchText = ""; }
                    }
                }

                Text {
                    objectName: "sidebarSearchEmpty"
                    Layout.fillWidth: true
                    Layout.margins: Theme.space.lg
                    visible: root.searching && !root.searchPending && root.filteredProjects.length === 0
                             && root.filteredRecents.length === 0
                    text: "No matching projects or chats.\nTry other words from the title or conversation."
                    textFormat: Text.PlainText
                    font: Theme.type.callout
                    color: Theme.textSecondary
                    wrapMode: Text.Wrap
                    lineHeight: Theme.leading.normal
                }

                Text {
                    objectName: "sidebarSearchStatus"
                    Layout.fillWidth: true
                    Layout.margins: Theme.space.lg
                    visible: root.searching && (root.searchPending || root.searchNote !== "")
                    text: root.searchPending ? "Searching saved chats…" : root.searchNote
                    textFormat: Text.PlainText
                    font: Theme.type.caption
                    color: Theme.textSecondary
                    wrapMode: Text.Wrap
                }

                Item { Layout.preferredHeight: Theme.space.lg }
            }
        }

        // -- footer ---------------------------------------------------------

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.separator
        }

        NavRow {
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            Layout.leftMargin: Theme.space.sm
            Layout.rightMargin: Theme.space.sm
            icon: "settings"
            label: "Settings & connections"
            onClicked: root.settingsRequested()
        }
    }
}
