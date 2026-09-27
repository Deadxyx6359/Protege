import QtQuick
import QtQuick.Layouts
import Akira

/*!
    The application window.

    The conversation is live: \c Chat is the Python bridge, and the transcript,
    busy state, model label and saved conversations all come from it, and the
    sidebar's projects come from \c Projects.
*/
Window {
    id: win

    width: 1440
    height: 900
    minimumWidth: 900
    minimumHeight: 600
    visible: true
    color: Theme.canvas
    title: "Akira"
    onClosing: function (close) {
        if (Voice.inCall) {
            close.accepted = false;
            win.hide();
            callWindow.raise();
        }
    }
    function showConversation() {
        if (win.fullPage) win.selectWorkspace("chats");
        win.showNormal(); win.raise(); win.requestActivate();
    }
    function finishCall() {
        if (!win.visible) win.showConversation();
        Voice.endCall();
    }
    property bool callWasActive: false
    property string lastVoiceNote: ""
    Connections {
        target: Voice
        function onCallChanged() {
            if (Voice.inCall) win.callWasActive = true;
            else if (win.callWasActive) {
                win.callWasActive = false;
                if (!win.visible) win.showConversation();
            }
        }
        function onStateChanged() {
            if (Voice.note && Voice.note !== win.lastVoiceNote) banners.show("Voice", Voice.note, false);
            win.lastVoiceNote = Voice.note;
        }
    }
    CallWindow {
        id: callWindow
        objectName: "voiceCallWindow"
        onEndRequested: win.finishCall()
        onReturnRequested: win.showConversation()
    }
    VoiceSheet {
        id: voiceSheet
        objectName: "voiceSheet"
        z: 12
        workBusy: Chat.busy || Agents.busy
        onStartRequested: {
            if (Chat.busy || Agents.busy) return;
            if (Voice.startCall()) { voiceSheet.close(); callWindow.raise(); callWindow.requestActivate(); }
        }
        onShowCallRequested: { voiceSheet.close(); callWindow.showNormal(); callWindow.raise(); callWindow.requestActivate(); }
    }

    ThemeLink {}
    PicturesSheet {
        id: picturesSheet
        objectName: "picturesSheet"
        z: 12
    }
    DraftsSheet {
        id: draftsSheet
        objectName: "draftsSheet"
        z: 12
        onPermissionsRequested: { draftsSheet.close(); permissionsSheet.open(); }
    }

    // -- sample state -------------------------------------------------------

    property string currentNav: "chats"
    property bool sidebarOpen: true
    property string observedProject: ""
    property var projectDrafts: ({})
    property bool restoringConversation: false
    property bool pendingProjectReset: false
    Component.onCompleted: observedProject = Projects.currentId
    readonly property var destinations: [
        { id: "chats", icon: "chat", label: "Chat", group: "Chat" },
        { id: "documents", icon: "document", label: "Documents", group: "Library" },
        { id: "memory", icon: "clock", label: "Memory", group: "Library", countLabel: "pending note" },
        { id: "code", icon: "code", label: "Code", group: "Tools" },
        { id: "research", icon: "search", label: "Research", group: "Tools" },
        { id: "agents", icon: "team", label: "Agents", group: "Tools" },
        { id: "watching", icon: "eye", label: "Watching", group: "Tools", countLabel: "saved notice" },
        { id: "schedule", icon: "calendar", label: "Schedule", group: "Tools", countLabel: "critical finding" }
    ]
    readonly property var navCounts: ({memory: Memory.pendingCount, watching: Monitor.notices.length, schedule: Schedule.criticalCount})
    // Views that fill the page themselves: no transcript, no composer.
    readonly property bool fullPage: currentNav !== "chats"

    function selectWorkspace(id) {
        const views = { "chat-1": "chats", "code-1": "code", "research-1": "research" };
        currentNav = views[id] || id;
    }

    function rememberDraft(project) {
        const drafts = Object.assign({}, projectDrafts);
        drafts[project] = composer.text;
        projectDrafts = drafts;
    }

    function selectProject(id) {
        if (id === Projects.currentId) return;
        if (Voice.inCall) { banners.show("Call is active", "End the call before switching projects.", false); return; }
        if (Chat.busy || Agents.busy) {
            banners.show("Work is still running", "Finish or stop the current work before switching projects.", false);
            return;
        }
        const why = Projects.openProject(id);
        if (why) banners.show("Project could not open", why, false);
    }

    function prepareTeam(name) {
        if (name === "research") {
            researchPage.prepareInvestigation(composer.text);
            win.selectWorkspace("research");
            return;
        }
        const project = Projects.projects.find(function (p) { return p.current; });
        const why = agentsPage.prepareTeam(name, composer.text, project ? project.folder : "");
        if (why) banners.show("Task could not open", why, false);
        else win.selectWorkspace("agents");
    }

    function finishProjectSwitch() {
        pendingProjectReset = false;
        Chat.newChat();
        composer.text = projectDrafts[Projects.currentId] || "";
    }

    function projectChanged() {
        const next = Projects.currentId;
        if (next === observedProject) return;
        // External project changes must not send call transcripts into a new context.
        if (Voice.inCall) Voice.endCall();
        if (!restoringConversation) rememberDraft(observedProject);
        observedProject = next;
        if (restoringConversation) return;
        // UI project controls are disabled while work runs. If another caller
        // switches anyway, wait for the old stream to unwind before resetting.
        if (Chat.busy) { pendingProjectReset = true; Chat.stop(); }
        else finishProjectSwitch();
    }

    function openRecent(id) {
        if (Voice.inCall) { banners.show("Call is active", "End the call before opening another conversation.", false); return; }
        if (Chat.busy || Agents.busy) {
            banners.show("Work is still running", "Finish or stop the current work before opening another conversation.", false);
            return;
        }
        restoringConversation = true;
        rememberDraft(Projects.currentId);
        Chat.openConversation(id);
        if (Chat.conversationId !== id) {
            restoringConversation = false;
            banners.show("Conversation could not open", "The saved conversation is unavailable. Your current work is still here.", false);
            return;
        }
        const saved = Chat.conversationProject;
        const exists = !saved || Projects.projects.some(function (p) { return p.id === saved; });
        const why = Projects.openProject(exists ? saved : "");
        restoringConversation = false;
        if (why) {
            Chat.newChat(); // Do not leave a saved chat under another project's context.
            banners.show("Project could not open", why, false);
        }
        else if (!exists) banners.show("Original project is unavailable", "This conversation will use personal workspace context for its next turn.", false);
        currentNav = "chats";
        composer.text = "";
    }

    // The open chat was filed under another project from its menu: go with it,
    // keeping the chat and the draft, as opening it from the list would.
    function followMovedChat(project) {
        if (project === Projects.currentId) return;
        const from = Projects.currentId;
        if (Agents.busy) {
            Chat.moveConversation(Chat.conversationId, from);
            banners.show("Work is still running", "Finish or stop the current work before moving the open chat to another project.", false);
            return;
        }
        restoringConversation = true;
        const why = Projects.openProject(project);
        restoringConversation = false;
        if (why) {
            Chat.moveConversation(Chat.conversationId, from);
            banners.show("Project could not open", why + " The chat stays where it was.", false);
        }
    }

    Connections { target: Projects; function onCurrentChanged() { win.projectChanged() } }
    Connections {
        target: Chat
        function onBusyChanged() { if (!Chat.busy && win.pendingProjectReset) win.finishProjectSwitch(); }
    }

    // A project keeps its colour when another is removed: it comes from the id.
    function projectColor(id) {
        const palette = [Theme.accent, Theme.success, Theme.warning];
        let sum = 0;
        for (let i = 0; i < id.length; i++)
            sum = (sum * 31 + id.charCodeAt(i)) % 9973;
        return palette[sum % palette.length];
    }

    // -- layout -------------------------------------------------------------

    // Declared before the layout but lifted above it: QML paints later
    // siblings on top, and a modal that renders under the window it is
    // modal over is not a modal.
    SettingsSheet {
        id: settingsSheet
        objectName: "settingsSheet"
        z: 10
        onPermissionsRequested: {
            settingsSheet.close();
            permissionsSheet.open();
        }
        onPlaceRequested: {
            settingsSheet.close();
            placeSheet.open();
        }
        onAccountsRequested: {
            settingsSheet.close();
            accountsSheet.open();
        }
        onVoiceRequested: { settingsSheet.close(); voiceSheet.open(); }
    }

    PermissionsSheet {
        id: permissionsSheet
        objectName: "permissionsSheet"
        z: 11
    }

    PlaceSheet {
        id: placeSheet
        objectName: "placeSheet"
        z: 11
    }

    ProjectSheet {
        id: projectSheet
        objectName: "projectSheet"
        z: 11
        canSwitch: !Chat.busy && !Agents.busy && !Voice.inCall
    }

    AccountsSheet {
        id: accountsSheet
        objectName: "accountsSheet"
        z: 11
    }

    ResearchSourceSheet { id: researchSource; objectName: "researchSourceSheet"; z: 50 }
    RunHistorySheet { id: runHistory; objectName: "runHistorySheet"; z: 12; onArtifactRequested: function (artifact) { artifactSheet.present(artifact); } }
    ArtifactSheet {
        id: artifactSheet; objectName: "artifactSheet"; z: 13
        onPermissionsRequested: { artifactSheet.close(); runHistory.close(); permissionsSheet.open(); }
    }

    CodeReviewSheet {
        id: codeReview
        objectName: "codeReviewSheet"
        z: 10
        onPermissionsRequested: { codeReview.close(); permissionsSheet.open(); }
    }

    // Above everything, sheets included: an irreversible action waits on it.
    ConfirmDialog {
        objectName: "confirmDialog"
        z: 100
    }

    // A link in a reply goes out to the person's own browser, so it is asked
    // about first, with the whole address shown.
    LinkPrompt {
        id: linkPrompt
        objectName: "linkPrompt"
        z: 90
    }

    // What must reach the person rather than wait in a list: what a watch's
    // job has to say, and a critical finding from the security review.
    NoticeBanner {
        id: banners
        objectName: "noticeBanner"
        z: 50
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: 52
        anchors.rightMargin: Theme.space.lg
        width: Math.min(360, parent.width - Theme.space.xxl * 2)
        onReviewRequested: win.currentNav = "schedule"
        onNoticesRequested: win.currentNav = "watching"
    }

    Connections {
        target: Monitor
        function onNoticed(title, text) { banners.show(title, text, false, "notices") }
    }

    Connections {
        target: Schedule
        function onCriticalFound(count) {
            var titles = Schedule.findings
                .filter(function (f) { return f.severity === "critical"; })
                .slice(0, 3)
                .map(function (f) { return f.title; });
            banners.show(count === 1 ? "The security review found a critical problem"
                                     : "The security review found " + count + " critical problems",
                         titles.join("\n"), true);
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Sidebar {
            id: sidebar
            objectName: "workspaceSidebar"
            Layout.fillHeight: true
            Layout.preferredWidth: win.sidebarOpen ? 264 : 0
            visible: Layout.preferredWidth > 0
            clip: true

            Behavior on Layout.preferredWidth {
                NumberAnimation {
                    duration: Theme.duration.normal
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easing.standard
                }
            }

            currentNav: win.currentNav
            currentProject: Projects.currentId
            currentRecent: Chat.conversationId
            newChatEnabled: !Chat.busy && !Voice.inCall

            navModel: win.destinations
            navCounts: win.navCounts

            projectModel: Projects.projects.map(function (p) {
                return { id: p.id, name: p.name, color: win.projectColor(p.id) };
            })

            recentModel: Chat.recents
            chats: Chat
            onOpenChatMoved: function (project) { win.followMovedChat(project) }
            contentMatches: Chat.historySearch.results
            searchBusy: Chat.historySearch.busy
            searchNote: Chat.historySearch.note
            onSearchRequested: function (query) { Chat.historySearch.search(query); }
            onSearchInvalidated: Chat.historySearch.clear()

            onNavSelected: function (id) { win.selectWorkspace(id) }
            onRecentSelected: function (id) { win.openRecent(id) }
            onProjectSelected: function (id) { win.selectProject(id) }
            onNewProjectRequested: projectSheet.openNew()
            onCollapseRequested: win.sidebarOpen = false
            onNewChatRequested: {
                if (Chat.busy || Voice.inCall) return;
                if (win.fullPage || win.currentNav === "documents")
                    win.selectWorkspace("chats");
                Chat.newChat();
                composer.text = "";
                composer.focusInput();
            }
            onSettingsRequested: settingsSheet.open()
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            WorkspaceHeader {
                objectName: "workspaceHeader"
                z: 1
                Layout.fillWidth: true
                Layout.preferredHeight: implicitHeight
                destinations: win.destinations
                counts: win.navCounts
                projects: Projects.projects
                currentView: win.currentNav
                currentProject: Projects.currentId
                sidebarOpen: win.sidebarOpen
                projectSwitchingEnabled: !Chat.busy && !Agents.busy && !Voice.inCall
                onViewSelected: function (id) { win.selectWorkspace(id) }
                onProjectSelected: function (id) { win.selectProject(id) }
                onNewProjectRequested: projectSheet.openNew()
                onManageProjectRequested: projectSheet.manage(Projects.currentId)
                onSidebarRequested: win.sidebarOpen = true
                onPermissionsRequested: permissionsSheet.open()
                onAppearanceRequested: ThemeBridge.toggle()
                onSettingsRequested: settingsSheet.open()
            }

            // -- content ----------------------------------------------------

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                AgentsView {
                    onHistoryRequested: runHistory.present("")
                    id: agentsPage
                    objectName: "agentsView"
                    anchors.fill: parent
                    visible: win.currentNav === "agents"
                }

                WatchView {
                    objectName: "watchView"
                    anchors.fill: parent
                    visible: win.currentNav === "watching"
                }

                ScheduleView {
                    objectName: "scheduleView"
                    onDraftsRequested: draftsSheet.open()
                    anchors.fill: parent
                    visible: win.currentNav === "schedule"
                    onPermissionsRequested: permissionsSheet.open()
                }

                MemoryView {
                    objectName: "memoryView"
                    anchors.fill: parent
                    visible: win.currentNav === "memory"
                }

                DocumentsView {
                    objectName: "documentsView"
                    onPicturesRequested: picturesSheet.open()
                    anchors.fill: parent
                    visible: win.currentNav === "documents"
                    onPermissionsRequested: permissionsSheet.open()
                }

                ChatView {
                    objectName: "mainChatView"
                    visible: win.currentNav === "chats"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: composer.top
                    model: Chat.messages
                    busy: Chat.busy
                    busyStage: Chat.stage
                    sources: Chat.lastSources
                    contextNote: Chat.lastContextNote
                }

                CodeView {
                    objectName: "codeView"
                    visible: win.currentNav === "code"
                    anchors.fill: parent
                    busy: Chat.busy
                    onTeamRequested: win.prepareTeam("software")
                    onReviewRequested: codeReview.present()
                    onHistoryRequested: runHistory.present("software")
                    onProjectRequested: {
                        if (Projects.currentId) projectSheet.manage(Projects.currentId);
                        else projectSheet.openNew();
                    }
                }

                ResearchView {
                    id: researchPage
                    objectName: "researchView"
                    anchors.fill: parent
                    visible: win.currentNav === "research"
                    onSourceRequested: function (error) { researchSource.present(error); }
                    onArtifactRequested: function (artifact) { artifactSheet.present(artifact); }
                    onPermissionsRequested: permissionsSheet.open()
                }

                Composer {
                    id: composer
                    objectName: "workspaceComposer"
                    visible: !win.fullPage
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: Theme.space.lg
                    width: Math.min(720, parent.width - Theme.space.xxl * 2)

                    busy: Chat.busy
                    placeholder: "Ask anything"
                    footnote: Chat.intentLabel + " · " + Chat.routeLabel
                    modes: Chat.modes
                    mode: Chat.mode
                    onModeSelected: function (id) { Chat.setMode(id); }
                    voiceAvailable: true
                    callActive: Voice.inCall
                    onVoiceRequested: {
                        if (Voice.inCall) { callWindow.showNormal(); callWindow.raise(); callWindow.requestActivate(); }
                        else voiceSheet.open();
                    }

                    onSubmitted: function (text) { Chat.send(text) }
                    onStopped: Chat.stop()
                }
            }
        }
    }
}
