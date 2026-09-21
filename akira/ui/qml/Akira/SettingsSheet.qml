import QtQuick
import QtQuick.Layouts
import "modelnames.js" as ModelNames

Sheet {
    id: root
    title: "Settings"
    subtitle: "Make Akira yours"
    sheetWidth: 700
    property string section: "general"
    property bool modelDetails: false
    readonly property int accountCount: Accounts.accounts.length + Accounts.canvasSites.length + Accounts.bankConnections.length
    readonly property int availableRoutes: Settings.routes.filter(function (r) { return r.usable; }).length
    signal permissionsRequested()
    signal placeRequested()
    signal accountsRequested()
    onOpenedChanged: { if (opened) Settings.refresh(); }

    ColumnLayout {
        width: parent.width
        spacing: 18
        Segmented {
            objectName: "settingsSections"
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            current: root.section
            options: [{id: "general", label: "General"}, {id: "appearance", label: "Appearance"}, {id: "models", label: "Models"}]
            onSelected: function (id) { root.section = id; }
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
                text: "To add a model, place a .gguf file in this folder, then refresh. File availability does not verify that a model will load."
                font: Theme.type.caption
                color: Theme.textSecondary
                wrapMode: Text.Wrap
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
    }
}
