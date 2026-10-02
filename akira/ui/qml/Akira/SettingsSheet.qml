import QtQuick
import QtQuick.Layouts
import "modelnames.js" as ModelNames

/*!
    Settings: a list of pages on the left, one page at a time on the right.

    Every setting is a row with its name, one short line on what it does, and its
    control. The pages that were sheets of their own (Permissions, Location,
    Accounts, Web search, Voice) are their panes here, loaded only while their
    page is shown, so what was typed into one (a token, a key) is gone when the
    page or Settings is left. `show(id)` opens Settings on a page: every
    "Permissions" button in the window comes here.
*/
Sheet {
    id: root
    title: "Settings"
    sheetWidth: 920
    sheetHeight: 660
    sidebarWidth: 208

    property string section: "general"
    readonly property var pages: [
        {id: "general", label: "General", icon: "settings", blurb: "How Akira starts, runs and stops."},
        {id: "appearance", label: "Appearance", icon: "sun", blurb: "How Akira looks."},
        {id: "models", label: "Models", icon: "sparkle", blurb: "Which model answers: one on this computer, or Claude."},
        {id: "voice", label: "Voice", icon: "mic", blurb: "Talking with Akira, and calls."},
        {id: "firmware", label: "Firmware", icon: "chip", blurb: "ST's tools, and the boards plugged in."},
        {id: "permissions", label: "Permissions", icon: "shield", blurb: "What Akira may do. Everything is off until you allow it."},
        {id: "accounts", label: "Accounts", icon: "user", blurb: "Google, Canvas and banks."},
        {id: "search", label: "Web search", icon: "globe", blurb: "Every site through Tavily, not only DuckDuckGo and Wikipedia."},
        {id: "location", label: "Location", icon: "location", blurb: "Your place, for the seasons and the weather."},
        {id: "chats", label: "Chats", icon: "chat", blurb: "Clear out old conversations."}
    ]
    readonly property var page: pages.find(function (p) { return p.id === root.section; }) || pages[0]

    // A short page opened after a long one was scrolled starts at its top.
    onSectionChanged: { root.clearing = ""; root.cleared = ""; Qt.callLater(scrollToTop); }
    onOpenedChanged: { if (opened) { Settings.refresh(); Firmware.refresh(); clearing = ""; cleared = ""; } }

    /*! Open Settings on page \a id. */
    function show(id) {
        if (root.pages.some(function (p) { return p.id === id; })) root.section = id;
        root.open();
    }

    /*! Move to the page \a by places up or down the list, as the arrow keys do. */
    function step(by) {
        const at = root.pages.findIndex(function (p) { return p.id === root.section; });
        const next = Math.max(0, Math.min(root.pages.length - 1, at + by));
        root.section = root.pages[next].id;
        const row = tabs.itemAt(next);
        if (row) row.forceActiveFocus();
    }

    signal setupRequested()
    signal claudeRequested()
    signal startCallRequested()
    signal showCallRequested()

    // -- General ----------------------------------------------------------------
    readonly property int availableRoutes: Settings.routes.filter(function (r) { return r.usable; }).length

    // -- Chats: deleting in bulk, asked first with how many -------------------------
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

    // -- Models -------------------------------------------------------------------
    property bool modelDetails: false

    // -- Firmware: what the permission rows show, read again when grants change -------
    property int grantsRevision: 0
    property string firmwareNotice: ""
    Connections { target: Permissions; function onGrantsChanged() { root.grantsRevision += 1; } }
    function granted(capability) {
        void root.grantsRevision;
        return Permissions.describe(capability).granted === true;
    }
    function setGranted(capability, on) {
        root.firmwareNotice = "";
        if (on) root.firmwareNotice = Permissions.grant(capability, []);
        else Permissions.revoke(capability);
    }

    /*! Whether one of ST's tools is on this computer, beside its row. */
    component Status: Text {
        property bool found: false
        text: found ? "Found" : "Not found"
        textFormat: Text.PlainText
        font: Theme.type.captionStrong
        color: found ? Theme.success : Theme.textSecondary
    }

    // -- the list of pages ------------------------------------------------------------

    sidebar: Column {
        id: sections
        objectName: "settingsSections"
        anchors.fill: parent
        anchors.margins: Theme.space.sm
        anchors.topMargin: Theme.space.md
        spacing: 2
        /*! A page was chosen from the list. */
        signal selected(string id)
        onSelected: function (id) { root.section = id; }

        Repeater {
            id: tabs
            model: root.pages
            NavRow {
                required property var modelData
                objectName: "settingsTab_" + modelData.id
                width: sections.width
                label: modelData.label
                icon: modelData.icon
                selected: root.section === modelData.id
                onClicked: sections.selected(modelData.id)
                Keys.onUpPressed: root.step(-1)
                Keys.onDownPressed: root.step(1)
            }
        }
    }

    // -- the page shown -----------------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.lg

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.space.xs
            Text {
                objectName: "settingsPageTitle"
                Layout.fillWidth: true
                text: root.page.label
                textFormat: Text.PlainText
                font: Theme.type.title2
                color: Theme.textPrimary
                Accessible.role: Accessible.Heading
            }
            Text {
                Layout.fillWidth: true
                text: root.page.blurb
                textFormat: Text.PlainText
                font: Theme.type.callout
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
        }

        // Only the page shown is made: two of a pane would each hold their own half-typed key.
        Loader {
            id: pageLoader
            objectName: "settingsPage"
            Layout.fillWidth: true
            sourceComponent: ({
                general: generalPage, appearance: appearancePage, models: modelsPage,
                voice: voicePage, firmware: firmwarePage, permissions: permissionsPage,
                accounts: accountsPage, search: searchPage, location: locationPage, chats: chatsPage
            })[root.section] || generalPage
        }
    }

    // -- General -----------------------------------------------------------------------

    Component {
        id: generalPage
        ColumnLayout {
            objectName: "settingsGeneral"
            spacing: 0
            Squircle {
                Layout.fillWidth: true
                Layout.preferredHeight: overview.implicitHeight + 28
                Layout.bottomMargin: Theme.space.sm
                radius: Theme.radius.md
                fillColor: Theme.inset
                borderColor: Theme.separator
                RowLayout {
                    id: overview
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 14
                    BrandMark { size: 40 }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            Layout.fillWidth: true
                            text: root.availableRoutes || Chat.claudeConnected ? "Ready to chat" : "Set up your first model"
                            textFormat: Text.PlainText
                            font: Theme.type.headline
                            color: Theme.textPrimary
                            wrapMode: Text.Wrap
                        }
                        Text {
                            objectName: "settingsModelStatus"
                            Layout.fillWidth: true
                            text: root.availableRoutes
                                  ? root.availableRoutes + " of " + Settings.routes.length + " kinds of work have a model on this computer."
                                  : "Choose a model on this computer, or add Claude."
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
                title: "Quick setup"
                description: "Choose what Akira may do, in one step."
                ActionButton { objectName: "quickSetup"; text: "Open"; onClicked: root.setupRequested() }
            }
            FormRow {
                Layout.fillWidth: true
                title: "Keep running when closed"
                description: Background.keepRunning
                    ? "Reminders, watches and jobs go on from the icon by the clock."
                    : "Closing the window quits Akira and everything it was doing."
                Toggle {
                    objectName: "keepRunningToggle"
                    label: "Keep running when closed"
                    checked: Background.keepRunning
                    onToggled: function (value) { Background.keepRunning = value; }
                }
            }
            FormRow {
                Layout.fillWidth: true
                divider: false
                title: "Quit Akira"
                description: "Stop everything now, background work too."
                ActionButton { objectName: "quitAkira"; text: "Quit"; onClicked: Background.quit() }
            }
        }
    }

    // -- Appearance ----------------------------------------------------------------------

    Component {
        id: appearancePage
        ColumnLayout {
            objectName: "settingsAppearance"
            spacing: 0
            FormRow {
                Layout.fillWidth: true
                title: "Theme"
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
    }

    // -- Models --------------------------------------------------------------------------

    Component {
        id: modelsPage
        ColumnLayout {
            objectName: "settingsModels"
            spacing: Theme.space.md

            SectionLabel { text: "Claude" }
            FormRow {
                Layout.fillWidth: true
                title: "Claude Opus 5.5"
                description: Chat.claudeConnected
                    ? "Connected. Choose it in the chat box. " + Chat.claudeSpend
                    : "Anthropic's model, chosen in the chat box. Needs an API key."
                ActionButton {
                    objectName: "manageClaude"
                    text: Chat.claudeConnected ? "Manage" : "Add key"
                    onClicked: root.claudeRequested()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.space.sm
                SectionLabel { Layout.fillWidth: true; text: "On this computer" }
                ActionButton { text: root.modelDetails ? "Hide details" : "File details"; onClicked: root.modelDetails = !root.modelDetails }
                IconButton { icon: "refresh"; label: "Look for model files again"; onClicked: Settings.refresh() }
            }
            Text {
                Layout.fillWidth: true
                text: Settings.availableModels.length ? "A model for each kind of work." : "No model files found in the model folder."
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
            Text {
                Layout.fillWidth: true
                visible: Chat.busy || Agents.busy
                text: "These unlock when the current work finishes."
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
    }

    // -- Voice ---------------------------------------------------------------------------

    Component {
        id: voicePage
        VoicePane {
            objectName: "voicePane"
            workBusy: Chat.busy || Agents.busy
            onStartRequested: root.startCallRequested()
            onShowCallRequested: root.showCallRequested()
        }
    }

    // -- Firmware ------------------------------------------------------------------------

    Component {
        id: firmwarePage
        ColumnLayout {
            objectName: "settingsFirmware"
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                SectionLabel { Layout.fillWidth: true; text: "Tools" }
                IconButton { objectName: "refreshFirmwareTools"; icon: "refresh"; label: "Look for ST's tools again"; onClicked: Firmware.refresh() }
            }
            FormRow {
                Layout.fillWidth: true
                title: "STM32CubeProgrammer"
                description: Firmware.programmer ? "Finds, reads and programs boards over ST-LINK."
                                                 : "Install it from ST to find, read and program boards."
                Status { objectName: "programmerStatus"; found: Firmware.programmer !== "" }
            }
            FormRow {
                Layout.fillWidth: true
                title: "STM32CubeMX"
                description: Firmware.cubemx ? "Regenerates a project's code after its .ioc changes."
                                             : "Install it from ST to regenerate code from a .ioc."
                Status { objectName: "cubemxStatus"; found: Firmware.cubemx !== "" }
            }
            FormRow {
                Layout.fillWidth: true
                divider: false
                title: "Serial ports"
                description: Firmware.serial ? "Reads what a board prints." : "Needs pyserial to read what a board prints."
                Status { objectName: "serialStatus"; found: Firmware.serial }
            }

            SectionLabel { Layout.topMargin: Theme.space.lg; text: "Permissions" }
            FormRow {
                Layout.fillWidth: true
                title: "Read connected boards"
                description: "See boards, what they print, and their registers. Changes nothing."
                Toggle {
                    objectName: "allowBoardReading"
                    label: "Read connected boards"
                    checked: root.granted("device.read")
                    onToggled: function (on) { root.setGranted("device.read", on); }
                }
            }
            FormRow {
                Layout.fillWidth: true
                divider: false
                title: "Program connected boards"
                description: "Write a build to a board. You are still asked every time."
                Toggle {
                    objectName: "allowBoardProgramming"
                    label: "Program connected boards"
                    checked: root.granted("device.write")
                    onToggled: function (on) { root.setGranted("device.write", on); }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: root.firmwareNotice !== ""
                text: root.firmwareNotice
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.danger
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.space.lg
                SectionLabel { Layout.fillWidth: true; text: "Plugged in" }
                ActionButton {
                    objectName: "findBoards"
                    text: Firmware.scanning ? "Looking…" : "Look for boards"
                    enabled: !Firmware.scanning && root.granted("device.read")
                    onClicked: root.firmwareNotice = Firmware.scan()
                }
            }
            Text {
                Layout.fillWidth: true
                Layout.topMargin: Theme.space.xs
                visible: !root.granted("device.read")
                text: "Allow reading connected boards to look."
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
            Repeater {
                model: Firmware.boards
                FormRow {
                    required property var modelData
                    Layout.fillWidth: true
                    title: modelData.board || "An ST-LINK"
                    description: "ST-LINK " + modelData.serial + (modelData.firmware ? " · firmware " + modelData.firmware : "")
                }
            }
            Repeater {
                model: Firmware.ports
                FormRow {
                    required property var modelData
                    Layout.fillWidth: true
                    title: modelData.name
                    description: modelData.description || "A serial port"
                }
            }
            Text {
                objectName: "boardsFound"
                Layout.fillWidth: true
                Layout.topMargin: Theme.space.xs
                visible: Firmware.scanned && !Firmware.scanning
                text: Firmware.error ? Firmware.error
                    : Firmware.boards.length || Firmware.ports.length
                      ? (Firmware.boards.length === 1 ? "1 board" : Firmware.boards.length + " boards") + " and "
                        + (Firmware.ports.length === 1 ? "1 serial port" : Firmware.ports.length + " serial ports") + " found."
                      : "Nothing plugged in was found."
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Firmware.error ? Theme.danger : Theme.textSecondary
                wrapMode: Text.Wrap
            }
        }
    }

    // -- the panes that were sheets --------------------------------------------------------

    Component {
        id: permissionsPage
        PermissionsPane {
            objectName: "permissionsPane"
            active: root.opened
            onScrollRequested: root.scrollToTop()
        }
    }

    Component {
        id: accountsPage
        AccountsPane {
            objectName: "accountsPane"
            active: root.opened
            onScrollRequested: root.scrollToTop()
        }
    }

    Component {
        id: searchPage
        AccountsPane {
            objectName: "searchPane"
            section: "search"
            showSections: false
            active: root.opened
            onScrollRequested: root.scrollToTop()
        }
    }

    Component {
        id: locationPage
        PlacePane {
            objectName: "placePane"
            active: root.opened
            onScrollRequested: root.scrollToTop()
        }
    }

    // -- Chats ---------------------------------------------------------------------------

    Component {
        id: chatsPage
        ColumnLayout {
            objectName: "settingsChats"
            spacing: 0
            FormRow {
                Layout.fillWidth: true
                title: "Keep pinned chats"
                description: "Deleting below leaves pinned chats alone."
                Toggle {
                    objectName: "keepPinnedToggle"
                    label: "Keep pinned chats when deleting"
                    checked: root.keepPinned
                    onToggled: function (value) { root.keepPinned = value; root.clearing = ""; }
                }
            }
            FormRow {
                Layout.fillWidth: true
                title: "Old chats"
                description: "Chats not used in the time chosen."
                Select {
                    objectName: "olderThanChoice"
                    Layout.preferredWidth: 140
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
                description: "Every chat, once you confirm."
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
