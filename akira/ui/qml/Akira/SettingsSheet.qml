import QtQuick
import QtQuick.Layouts
import "modelnames.js" as ModelNames

Sheet {
    id: root
    title: "Settings"
    subtitle: "Make Akira yours"
    sheetWidth: 700
    property string section: "general"
    // A short section opened after a long one was scrolled starts at its top,
    // with the section switch in view.
    onSectionChanged: Qt.callLater(scrollToTop)
    property bool modelDetails: false
    readonly property int accountCount: Accounts.accounts.length + Accounts.canvasSites.length + Accounts.bankConnections.length
    readonly property int availableRoutes: Settings.routes.filter(function (r) { return r.usable; }).length
    // -- Chats: deleting in bulk, asked first with how many --------------------
    property bool keepPinned: true
    property int olderThanDays: 30
    /*! The delete being asked about: "old", "all" or "". */
    property string clearing: ""
    /*! What the last delete did, in a sentence. */
    property string cleared: ""
    readonly property int oldCount: { Chat.recents; return Chat.countConversations(olderThanDays, keepPinned); }
    readonly property int allCount: { Chat.recents; return Chat.countConversations(0, keepPinned); }

    function chats(n) { return n + (n === 1 ? " chat" : " chats"); }
    function clearChats() {
        const gone = clearing === "old" ? Chat.deleteConversationsOlderThan(olderThanDays, keepPinned)
                                        : Chat.deleteAllConversations(keepPinned);
        clearing = "";
        cleared = gone ? "Deleted " + chats(gone) + "." : "Nothing to delete.";
    }

    signal permissionsRequested()
    signal setupRequested()
    signal placeRequested()
    signal accountsRequested()
    signal voiceRequested()
    onOpenedChanged: { if (opened) { Settings.refresh(); clearing = ""; cleared = ""; } }

    ColumnLayout {
        width: parent.width
        spacing: 18
        Segmented {
            objectName: "settingsSections"
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            current: root.section
            options: [{id: "general", label: "General"}, {id: "appearance", label: "Appearance"}, {id: "models", label: "Models"}, {id: "chats", label: "Chats"}]
            onSelected: function (id) { root.section = id; root.clearing = ""; root.cleared = ""; }
        }
        ColumnLayout {
            objectName: "settingsGeneral"
            visible: root.section === "general"
            Layout.fillWidth: true
            spacing: 0
            Squircle {
                Layout.fillWidth: true
                Layout.preferredHeight: overview.implicitHeight + 28
                Layout.bottomMargin: 8
                radius: Theme.radius.md
                fillColor: Theme.inset
                borderColor: Theme.separator
                RowLayout {
                    id: overview
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 14
                    BrandMark { size: 44 }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Text {
                            Layout.fillWidth: true
                            text: root.availableRoutes ? "Your local workspace" : "Set up your first model"
                            textFormat: Text.PlainText
                            font: Theme.type.headline
                            color: Theme.textPrimary
                            wrapMode: Text.Wrap
                        }
                        Text {
                            objectName: "settingsModelStatus"
                            Layout.fillWidth: true
                            text: root.availableRoutes ? root.availableRoutes + " of " + Settings.routes.length + " model assignments have a local file."
                                : "Choose a local model to start a conversation."
                            textFormat: Text.PlainText
                            font: Theme.type.caption
                            color: Theme.textSecondary
                            wrapMode: Text.Wrap
                        }
                    }
                    ActionButton {
                        objectName: "setupModels"
                        text: root.availableRoutes ? "Models" : "Set up"
                        onClicked: root.section = "models"
                    }
                }
            }
            FormRow {
                Layout.fillWidth: true
                title: "Permissions"
                description: Permissions.grants.length + " global grants. Project grants are managed separately."
                ActionButton { objectName: "quickSetup"; text: "Quick setup"; onClicked: root.setupRequested() }
                ActionButton { objectName: "reviewPermissions"; text: "Review"; onClicked: root.permissionsRequested() }
            }
            FormRow {
                Layout.fillWidth: true
                title: Place.name || "Location & weather"
                description: Place.name ? (Place.weatherSummary || "Location saved. Weather follows its permissions.")
                                        : "Set your location for local seasons and weather."
                ActionButton { objectName: "setPlace"; text: Place.name ? "Change" : "Set"; onClicked: root.placeRequested() }
            }
            FormRow {
                Layout.fillWidth: true
                divider: false
                title: "Connected accounts"
                description: root.accountCount ? root.accountCount + " connection" + (root.accountCount === 1 ? "" : "s") + " across Google, Canvas and banks."
                    : "Google, Canvas and read-only banking. Connect only what you need."
                ActionButton { objectName: "openAccounts"; text: root.accountCount ? "Manage" : "Connect"; onClicked: root.accountsRequested() }
            }
            FormRow {
                Layout.fillWidth: true
                title: "Voice & calls"
                description: "Choose a voice, hear a sample, or start a hands-free call."
                ActionButton { objectName: "openVoiceSettings"; text: "Open"; onClicked: root.voiceRequested() }
            }
        }
        ColumnLayout {
            objectName: "settingsAppearance"
            visible: root.section === "appearance"
            Layout.fillWidth: true
            spacing: 0
            FormRow {
                Layout.fillWidth: true
                title: "Appearance"
                description: "Auto follows Windows."
                Segmented {
                    objectName: "appearanceModes"
                    Layout.preferredWidth: 210
                    current: ThemeBridge.mode
                    options: [{id: "auto", label: "Auto"}, {id: "light", label: "Light"}, {id: "dark", label: "Dark"}]
                    onSelected: function (id) { ThemeBridge.mode = id; }
                }
            }
            FormRow {
                Layout.fillWidth: true
                divider: false
                title: "Reduce motion"
                description: "Still scenes and instant transitions."
                Toggle {
                    objectName: "reduceMotionToggle"
                    label: "Reduce motion"
                    checked: ThemeBridge.reduceMotion
                    onToggled: function (value) { ThemeBridge.reduceMotion = value; }
                }
            }
        }
        ColumnLayout {
            objectName: "settingsModels"
            visible: root.section === "models"
            Layout.fillWidth: true
            spacing: 14
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text { text: "Local models"; font: Theme.type.headline; color: Theme.textPrimary }
                    Text {
                        Layout.fillWidth: true
                        text: Settings.availableModels.length ? "Choose a model for each kind of work." : "No model files found in the model folder."
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: Theme.textSecondary
                        wrapMode: Text.Wrap
                    }
                }
                ActionButton { text: root.modelDetails ? "Hide details" : "File details"; onClicked: root.modelDetails = !root.modelDetails }
                IconButton { icon: "refresh"; label: "Refresh local models"; onClicked: Settings.refresh() }
            }
            Text {
                Layout.fillWidth: true
                visible: Chat.busy || Agents.busy
                text: "Model choices unlock when the current work finishes."
                font: Theme.type.caption
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
            Repeater {
                model: Settings.routes
                ColumnLayout {
                    id: routeRow
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 7
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text {
                                Layout.fillWidth: true
                                text: routeRow.modelData.label === "Chat" ? "Everyday" : routeRow.modelData.label
                                textFormat: Text.PlainText
                                font: Theme.type.bodyStrong
                                color: Theme.textPrimary
                            }
                            Text {
                                Layout.fillWidth: true
                                text: routeRow.modelData.blurb
                                textFormat: Text.PlainText
                                font: Theme.type.caption
                                color: Theme.textSecondary
                                wrapMode: Text.Wrap
                            }
                        }
                        Text {
                            text: routeRow.modelData.loaded ? "Loaded" : routeRow.modelData.usable ? "File available" : routeRow.modelData.path ? "File missing" : "Not assigned"
                            textFormat: Text.PlainText
                            font: Theme.type.captionStrong
                            color: routeRow.modelData.usable ? Theme.success : Theme.textSecondary
                        }
                    }
                    Select {
                        objectName: "modelChoice_" + routeRow.modelData.id
                        Layout.fillWidth: true
                        label: "Model for " + routeRow.modelData.label
                        current: routeRow.modelData.path
                        placeholder: "Choose a local model"
                        enabled: !Chat.busy && !Agents.busy
                        options: {
                            const found = Settings.availableModels.map(function (m) {
                                return {value: m.path, label: ModelNames.display(m.name), detail: ModelNames.detail(m.name, m.size)};
                            });
                            if (routeRow.modelData.path && !found.some(function (m) { return m.value === routeRow.modelData.path; }))
                                found.unshift({value: routeRow.modelData.path, label: ModelNames.display(routeRow.modelData.name), detail: routeRow.modelData.usable ? "Assigned" : "Missing"});
                            return [{value: "", label: "Not assigned"}].concat(found);
                        }
                        onPicked: function (value) { Settings.assign(routeRow.modelData.id, value); }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: root.modelDetails
                        text: (routeRow.modelData.path || "No file assigned") + "\nContext: " + routeRow.modelData.contextTokens
                            + " · Maximum reply: " + routeRow.modelData.maxTokens + " tokens"
                        textFormat: Text.PlainText
                        font: Theme.type.monoSmall
                        color: Theme.textSecondary
                        wrapMode: Text.WrapAnywhere
                    }
                    Rectangle { Layout.fillWidth: true; Layout.topMargin: 3; height: 1; color: Theme.separator }
                }
            }
            Text {
                Layout.fillWidth: true
                text: Settings.modelsDirectory
                textFormat: Text.PlainText
                font: Theme.type.monoSmall
                color: Theme.textSecondary
                wrapMode: Text.WrapAnywhere
            }
        }
        ColumnLayout {
            objectName: "settingsChats"
            visible: root.section === "chats"
            Layout.fillWidth: true
            spacing: 0
            FormRow {
                Layout.fillWidth: true
                title: "Keep pinned chats"
                Toggle {
                    objectName: "keepPinnedToggle"
                    label: "Keep pinned chats when deleting"
                    checked: root.keepPinned
                    onToggled: function (value) { root.keepPinned = value; root.clearing = ""; }
                }
            }
            FormRow {
                Layout.fillWidth: true
                title: "Chats not used in"
                Select {
                    objectName: "olderThanChoice"
                    Layout.preferredWidth: 150
                    label: "Delete chats not used in"
                    current: String(root.olderThanDays)
                    options: [{value: "7", label: "A week"}, {value: "30", label: "30 days"},
                              {value: "90", label: "90 days"}, {value: "365", label: "A year"}]
                    onPicked: function (value) { root.olderThanDays = Number(value); root.clearing = ""; }
                }
                ActionButton {
                    objectName: "deleteOldChats"
                    text: root.oldCount ? "Delete " + root.chats(root.oldCount) + "…" : "None that old"
                    enabled: root.oldCount > 0 && root.clearing === ""
                    onClicked: { root.cleared = ""; root.clearing = "old"; }
                }
            }
            FormRow {
                Layout.fillWidth: true
                divider: false
                title: "All chats"
                ActionButton {
                    objectName: "deleteAllChats"
                    text: root.allCount ? "Delete " + root.chats(root.allCount) + "…" : "No chats to delete"
                    enabled: root.allCount > 0 && root.clearing === ""
                    onClicked: { root.cleared = ""; root.clearing = "all"; }
                }
            }
            Squircle {
                objectName: "clearChatsQuestion"
                visible: root.clearing !== ""
                Layout.fillWidth: true
                Layout.topMargin: 8
                Layout.preferredHeight: question.implicitHeight + 28
                radius: Theme.radius.md
                fillColor: Theme.inset
                borderColor: Theme.separator
                onVisibleChanged: if (visible) keepChats.forceActiveFocus()
                RowLayout {
                    id: question
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10
                    Text {
                        Layout.fillWidth: true
                        text: "Delete " + root.chats(root.clearing === "old" ? root.oldCount : root.allCount)
                              + (root.clearing === "old" ? " not used in " + (root.olderThanDays === 7 ? "a week" : root.olderThanDays === 365 ? "a year" : root.olderThanDays + " days") : "")
                              + (root.keepPinned ? ", keeping pinned chats" : ", pinned chats too")
                              + "? This cannot be undone."
                        textFormat: Text.PlainText
                        font: Theme.type.callout
                        color: Theme.textPrimary
                        wrapMode: Text.Wrap
                    }
                    ActionButton { id: keepChats; objectName: "keepChats"; text: "Keep"; onClicked: root.clearing = "" }
                    ActionButton { objectName: "confirmClearChats"; text: "Delete"; kind: "danger"; onClicked: root.clearChats() }
                }
            }
            Text {
                objectName: "clearedChats"
                visible: root.cleared !== ""
                Layout.fillWidth: true
                Layout.topMargin: 8
                text: root.cleared
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textSecondary
            }
        }
    }
}
