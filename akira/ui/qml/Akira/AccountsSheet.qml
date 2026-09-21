import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import QtQuick.Layouts

/*!
    Connected accounts: Google (the client file, connecting an address, and what
    is connected) and Canvas (a site and an access token, read only).

    Connecting reads only, and needs the address allowed first: Gmail
    (\c mail.read) or Google Calendar (\c calendar.read) for that address,
    offered here beside what it is for and taken only when the person presses.
    Grants are read fresh when changed, so allowing this address never drops
    another allowed since. Signing in happens in the person's own browser;
    nothing secret is typed or shown here, and the client file is sealed on this
    computer the moment it is chosen.
*/
Sheet {
    id: root

    title: "Accounts"
    subtitle: "Connect only what you need"
    sheetWidth: 700
    property string section: "google"
    property string noticeSection: "google"
    property bool setupDetails: false
    onSectionChanged: { root.armed = ""; root.scrollToTop(); }
    onOpenedChanged: {
        if (!opened) { root.canvasToken = ""; root.bankToken = ""; root.armed = ""; }
    }

    property string address: ""
    /*! What to connect, by service id. */
    property var chosen: ["mail", "calendar"]
    property string notice: ""
    onNoticeChanged: { if (opened && notice !== "") root.scrollToTop(); }
    property bool good: false
    /*! The address a first press of Disconnect armed. */
    property string armed: ""
    property int revision: 0
    property string canvasSite: ""
    /*! Held only until it is handed to the bridge, then cleared. */
    property string canvasToken: ""
    /*! The SimpleFIN setup token, held only until it is handed over, then cleared. */
    property string bankToken: ""

    Connections {
        target: Permissions
        function onGrantsChanged() { root.revision += 1 }
    }

    Connections {
        target: Accounts
        function onBankFinished(ok, message) {
            root.noticeSection = "banks";
            root.notice = message;
            root.good = ok;
        }
        function onCanvasFinished(ok, message) {
            root.noticeSection = "canvas";
            root.notice = message;
            root.good = ok;
            if (ok)
                root.canvasSite = "";
        }
        function onFinished(ok, message) {
            root.noticeSection = "google";
            root.notice = message;
            root.good = ok;
            if (ok)
                root.address = "";
        }
    }

    readonly property string who: root.address.trim().toLowerCase()
    readonly property bool validAddress: /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(root.who)
    readonly property var gaps: {
        void root.revision;
        return root.validAddress ? Accounts.missing(root.who, root.chosen) : [];
    }

    function has(id) { return root.chosen.indexOf(id) >= 0; }

    function setChosen(id, on) {
        var next = root.chosen.filter(function (s) { return s !== id; });
        if (on)
            next.push(id);
        root.chosen = next;
    }

    /*! Allow \a capability for the typed address, keeping every address it allows now. */
    function allow(capability) { return root.allowFor(capability, root.who); }

    /*! Allow \a capability for \a scope, keeping every scope it allows now. */
    function allowFor(capability, scope) {
        var now = Permissions.describe(capability);
        var held = now.granted ? now.scopes : [];
        var known = held.map(function (s) { return String(s).toLowerCase(); });
        if (known.indexOf(scope) >= 0)
            return "";
        root.noticeSection = root.section;
        root.notice = Permissions.grant(capability, held.concat([scope]));
        root.good = false;
        return root.notice;
    }

    readonly property string canvasWhere: Accounts.canvasSite(root.canvasSite)
    readonly property var canvasGaps: {
        void root.revision;
        return root.canvasWhere !== "" ? Accounts.canvasMissing(root.canvasWhere) : [];
    }

    readonly property string bankWhere: Accounts.bankBridge(root.bankToken)
    readonly property var bankGaps: {
        void root.revision;
        return root.bankWhere !== "" ? Accounts.bankMissing(root.bankWhere) : [];
    }

    function connectBank() {
        root.noticeSection = "banks";
        root.notice = Accounts.connectBank(root.bankToken);
        root.good = false;
        root.bankToken = "";
        return root.notice;
    }

    /*! The first press arms; the second forgets the access. */
    function disconnectBank(bridge) {
        if (root.armed !== bridge) {
            root.armed = bridge;
            return "";
        }
        root.armed = "";
        root.noticeSection = "banks";
        root.notice = Accounts.disconnectBank(bridge);
        root.good = true;
        return root.notice;
    }

    function connectCanvas() {
        root.noticeSection = "canvas";
        root.notice = Accounts.connectCanvas(root.canvasSite, root.canvasToken);
        root.good = false;
        root.canvasToken = "";
        return root.notice;
    }

    /*! The first press arms; the second forgets the token. */
    function disconnectCanvas(site) {
        if (root.armed !== site) {
            root.armed = site;
            return "";
        }
        root.armed = "";
        root.noticeSection = "canvas";
        root.notice = Accounts.disconnectCanvas(site);
        root.good = true;
        return root.notice;
    }

    function chooseClient(path) {
        root.noticeSection = "google";
        var why = Accounts.chooseClientFile(path);
        root.notice = why === "" ? "Chosen, and sealed on this computer. You can delete the downloaded copy."
                                 : why;
        root.good = why === "";
        return why;
    }

    function connectNow() {
        root.noticeSection = "google";
        root.notice = Accounts.connectAccount(root.who, root.chosen);
        root.good = false;
        return root.notice;
    }

    function again(account) {
        root.address = account.address;
        root.chosen = account.services;
        return root.connectNow();
    }

    /*! The first press arms; the second disconnects. */
    function disconnect(address) {
        if (root.armed !== address) {
            root.armed = address;
            return "";
        }
        root.armed = "";
        root.noticeSection = "google";
        var note = Accounts.disconnectAccount(address);
        root.notice = note === "" ? "Disconnected " + address + ", and Google was told." : note;
        root.good = note === "";
        return note;
    }

    Timer { running: root.armed !== ""; interval: 5000; onTriggered: root.armed = "" }

    FileDialog {
        id: clientPicker
        title: "The client file from Google Cloud"
        nameFilters: ["Google client file (*.json)"]
        onAccepted: {
            var text = selectedFile.toString();
            root.chooseClient(decodeURIComponent(text.indexOf("file:///") === 0 ? text.substring(8) : text));
        }
    }

    component Field: Rectangle {
        id: field
        property string text: ""
        /*! Shown as dots, for a token. */
        property bool secret: false
        property string label: placeholder
        property alias placeholder: input.placeholderText
        signal edited(string value)
        radius: Theme.radius.sm
        color: Theme.inset
        border.width: 1
        border.color: input.activeFocus ? Theme.accent : Theme.separator
        implicitHeight: 32
        C.TextField {
            id: input
            anchors.fill: parent
            anchors.leftMargin: Theme.space.sm
            anchors.rightMargin: Theme.space.sm
            text: field.text
            font: Theme.type.callout
            color: Theme.textPrimary
            placeholderTextColor: Theme.textTertiary
            selectionColor: Theme.accentSubtle
            selectedTextColor: Theme.textPrimary
            selectByMouse: true
            background: null
            padding: 0
            verticalAlignment: TextInput.AlignVCenter
            echoMode: field.secret ? TextInput.Password : TextInput.Normal
            Accessible.name: field.label
            onTextEdited: field.edited(text)
        }
    }

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md
        Segmented {
            objectName: "accountSections"
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            current: root.section
            options: [{id: "google", label: "Google"}, {id: "canvas", label: "Canvas"}, {id: "banks", label: "Banks"}]
            onSelected: function (id) { root.section = id; }
        }
        Text {
            Layout.fillWidth: true
            text: root.section === "google" ? "Mail, calendars & Drive" : root.section === "canvas" ? "Your coursework, in reach" : "Your finances, read only"
            textFormat: Text.PlainText
            font: Theme.type.headline
            color: Theme.textPrimary
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            text: root.section === "google" ? "Choose individual services. Sending mail and changing events are optional."
                : root.section === "canvas" ? "Read courses and assignments from the school you connect."
                : "Read balances and transactions through SimpleFIN. Akira cannot move money."
            textFormat: Text.PlainText
            font: Theme.type.callout
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: feedback.implicitHeight + 24
            visible: root.notice !== ""
            radius: Theme.radius.sm
            color: Theme.inset
            border.color: root.good ? Theme.separator : Theme.danger
            Text {
                id: feedback
                objectName: "accountFeedback"
                anchors.fill: parent; anchors.margins: 12
                text: (root.noticeSection === "google" ? "Google · " : root.noticeSection === "canvas" ? "Canvas · " : "Banks · ") + root.notice
                textFormat: Text.PlainText
                font: Theme.type.callout
                color: root.good ? Theme.success : Theme.danger
                wrapMode: Text.Wrap
            }
        }
    }

    // -- the client -------------------------------------------------------------------

    ColumnLayout {
        objectName: "googleClientSetup"
        visible: root.section === "google"
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "1 · App connection" }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.md
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Text {
                    text: Accounts.clientReady ? "Client file saved securely" : "Choose your Google client file"
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    textFormat: Text.PlainText
                    font: Theme.type.body
                    color: Theme.textPrimary
                }
                Text {
                    visible: root.setupDetails
                    Layout.fillWidth: true
                    text: "In Google Cloud, signed in as the address you made for Akira: make a project, turn on the Gmail API, the Google Calendar API and the Google Drive API, set up the consent screen as External with that address as a test user, then under Credentials make an OAuth client ID of the Desktop app kind and download its file. Choose it here. Never paste it into a chat."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                    wrapMode: Text.Wrap
                }
            }
            ActionButton {
                objectName: "chooseClient"
                text: Accounts.clientReady ? "Choose another…" : "Choose the file…"
                onClicked: clientPicker.open()
            }
        }
        ActionButton {
            objectName: "googleSetupHelp"
            text: root.setupDetails ? "Hide setup instructions" : "How to get a client file"
            onClicked: root.setupDetails = !root.setupDetails
        }
    }

    // -- connecting -------------------------------------------------------------------

    ColumnLayout {
        objectName: "googleConnection"
        visible: root.section === "google"
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "2 · Address & services" }

        Field {
            objectName: "accountAddress"
            label: "Google email address"
            Layout.fillWidth: true
            text: root.address
            placeholder: "The Google address, such as akira.helper@gmail.com"
            onEdited: function (value) { root.address = value }
        }

        Repeater {
            model: Accounts.services
            RowLayout {
                id: offer
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.space.md
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        text: offer.modelData.title
                        textFormat: Text.PlainText
                        font: Theme.type.body
                        color: Theme.textPrimary
                    }
                    Text {
                        Layout.fillWidth: true
                        // Written beside the service in Python, so a new one
                        // arrives with its own words rather than another's.
                        text: offer.modelData.detail
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: Theme.textTertiary
                        wrapMode: Text.Wrap
                    }
                }
                Toggle {
                    label: offer.modelData.title
                    checked: root.has(offer.modelData.id)
                    onToggled: function (value) {
                        root.setChosen(offer.modelData.id, value);
                        checked = Qt.binding(function () { return root.has(offer.modelData.id); });
                    }
                }
            }
        }

        // What must be allowed first, beside what it allows.
        Repeater {
            model: root.gaps
            RowLayout {
                id: gap
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.space.md
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: "Allow " + gap.modelData.title + " for " + root.who
                        textFormat: Text.PlainText
                        font: Theme.type.body
                        color: Theme.textPrimary
                        elide: Text.ElideMiddle
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Applies only to this address. The service description above explains the access you are allowing."
                        font: Theme.type.caption
                        color: Theme.textTertiary
                        wrapMode: Text.Wrap
                    }
                }
                ActionButton {
                    text: "Allow"
                    kind: "primary"
                    onClicked: root.allow(gap.modelData.capability)
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: Accounts.busy
            spacing: Theme.space.md
            Text {
                Layout.fillWidth: true
                text: "Finish signing in as " + Accounts.connecting + " in your browser. Google will say the app is unverified: it is your own client, so continue past that."
                textFormat: Text.PlainText
                font: Theme.type.callout
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
            ActionButton {
                text: "Stop"
                onClicked: Accounts.cancel()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.sm
            Item { Layout.fillWidth: true }
            ActionButton {
                objectName: "connectAccount"
                text: "Connect"
                kind: "primary"
                enabled: Accounts.clientReady && root.validAddress && root.chosen.length > 0
                         && root.gaps.length === 0 && !Accounts.busy
                onClicked: root.connectNow()
            }
        }
    }

    // -- connected --------------------------------------------------------------------

    ColumnLayout {
        visible: root.section === "google"
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "Connected" }

        Text {
            visible: Accounts.accounts.length === 0
            text: "No address yet."
            font: Theme.type.callout
            color: Theme.textSecondary
        }

        Repeater {
            model: Accounts.accounts
            RowLayout {
                id: held
                required property var modelData
                readonly property bool isArmed: root.armed === held.modelData.address
                Layout.fillWidth: true
                spacing: Theme.space.sm
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: held.modelData.address
                        textFormat: Text.PlainText
                        font: Theme.type.bodyStrong
                        color: Theme.textPrimary
                        elide: Text.ElideMiddle
                    }
                    Text {
                        Layout.fillWidth: true
                        text: held.modelData.needsSignIn !== "" ? held.modelData.needsSignIn
                              : held.modelData.titles.join(", ") + " · since "
                                + Qt.formatDate(new Date(held.modelData.connected * 1000), "d MMM yyyy")
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: held.modelData.needsSignIn !== "" ? Theme.danger : Theme.textSecondary
                        wrapMode: Text.Wrap
                    }
                }
                ActionButton {
                    visible: held.modelData.needsSignIn !== ""
                    text: "Connect again"
                    kind: "primary"
                    enabled: !Accounts.busy
                    onClicked: root.again(held.modelData)
                }
                ActionButton {
                    text: held.isArmed ? "Disconnect it" : "Disconnect"
                    kind: held.isArmed ? "danger" : "secondary"
                    onClicked: root.disconnect(held.modelData.address)
                }
            }
        }
    }

    // -- Canvas -----------------------------------------------------------------------

    ColumnLayout {
        objectName: "canvasConnection"
        visible: root.section === "canvas"
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "Canvas" }

        Text {
            Layout.fillWidth: true
            text: Accounts.canvasHelp
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textTertiary
            wrapMode: Text.Wrap
        }

        Field {
            objectName: "canvasSite"
            label: "Canvas school address"
            Layout.fillWidth: true
            text: root.canvasSite
            placeholder: "Your school's Canvas address, such as school.instructure.com"
            onEdited: function (value) { root.canvasSite = value }
        }

        Field {
            objectName: "canvasToken"
            label: "Canvas access token"
            Layout.fillWidth: true
            secret: true
            text: root.canvasToken
            placeholder: "The access token from Canvas"
            onEdited: function (value) { root.canvasToken = value }
        }

        // What must be allowed first, beside what it allows.
        Repeater {
            model: root.canvasGaps
            RowLayout {
                id: canvasGap
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.space.md
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: "Allow " + canvasGap.modelData.title + " for " + root.canvasWhere
                        textFormat: Text.PlainText
                        font: Theme.type.body
                        color: Theme.textPrimary
                        elide: Text.ElideMiddle
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Lets Akira, and agents you start, read your courses there. Each request goes to that site with the token, and nowhere else."
                        font: Theme.type.caption
                        color: Theme.textTertiary
                        wrapMode: Text.Wrap
                    }
                }
                ActionButton {
                    text: "Allow"
                    kind: "primary"
                    onClicked: root.allowFor(canvasGap.modelData.capability, root.canvasWhere)
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.sm
            Item { Layout.fillWidth: true }
            ActionButton {
                objectName: "connectCanvas"
                text: Accounts.canvasConnecting !== "" ? "Connecting…" : "Connect Canvas"
                kind: "primary"
                enabled: root.canvasWhere !== "" && root.canvasToken.length >= 20
                         && root.canvasGaps.length === 0 && Accounts.canvasConnecting === ""
                onClicked: root.connectCanvas()
            }
        }

        Repeater {
            model: Accounts.canvasSites
            RowLayout {
                id: school
                required property var modelData
                readonly property bool isArmed: root.armed === school.modelData.site
                Layout.fillWidth: true
                spacing: Theme.space.sm
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: school.modelData.site
                        textFormat: Text.PlainText
                        font: Theme.type.bodyStrong
                        color: Theme.textPrimary
                        elide: Text.ElideMiddle
                    }
                    Text {
                        Layout.fillWidth: true
                        text: (school.modelData.name !== "" ? school.modelData.name + " · " : "")
                              + "reading only · since "
                              + Qt.formatDate(new Date(school.modelData.connected * 1000), "d MMM yyyy")
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: Theme.textSecondary
                        wrapMode: Text.Wrap
                    }
                }
                ActionButton {
                    text: school.isArmed ? "Forget it" : "Disconnect"
                    kind: school.isArmed ? "danger" : "secondary"
                    onClicked: root.disconnectCanvas(school.modelData.site)
                }
            }
        }
    }

    // -- banks, through SimpleFIN ------------------------------------------------------

    ColumnLayout {
        objectName: "bankConnection"
        visible: root.section === "banks"
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "Banks, through SimpleFIN" }

        Text {
            Layout.fillWidth: true
            text: Accounts.bankHelp
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textTertiary
            wrapMode: Text.Wrap
        }

        Field {
            objectName: "bankToken"
            label: "SimpleFIN setup token"
            Layout.fillWidth: true
            secret: true
            text: root.bankToken
            placeholder: "The setup token from SimpleFIN Bridge"
            onEdited: function (value) { root.bankToken = value }
        }

        // What must be allowed first, beside what it allows.
        Repeater {
            model: root.bankGaps
            RowLayout {
                id: bankGap
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.space.md
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: "Allow " + bankGap.modelData.title + " through " + root.bankWhere
                        textFormat: Text.PlainText
                        font: Theme.type.body
                        color: Theme.textPrimary
                        elide: Text.ElideMiddle
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Lets Akira, and agents you start, read balances and transactions. Nothing can move money."
                        font: Theme.type.caption
                        color: Theme.textTertiary
                        wrapMode: Text.Wrap
                    }
                }
                ActionButton {
                    text: "Allow"
                    kind: "primary"
                    onClicked: root.allowFor(bankGap.modelData.capability, root.bankWhere)
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.sm
            Item { Layout.fillWidth: true }
            ActionButton {
                objectName: "connectBank"
                text: Accounts.bankConnecting ? "Connecting…" : "Connect banks"
                kind: "primary"
                enabled: root.bankWhere !== "" && root.bankGaps.length === 0
                         && !Accounts.bankConnecting
                onClicked: root.connectBank()
            }
        }

        Repeater {
            model: Accounts.bankConnections
            RowLayout {
                id: linked
                required property var modelData
                readonly property bool isArmed: root.armed === linked.modelData.bridge
                Layout.fillWidth: true
                spacing: Theme.space.sm
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: "SimpleFIN (" + linked.modelData.bridge + ")"
                        textFormat: Text.PlainText
                        font: Theme.type.bodyStrong
                        color: Theme.textPrimary
                        elide: Text.ElideMiddle
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Reading only · since "
                              + Qt.formatDate(new Date(linked.modelData.connected * 1000), "d MMM yyyy")
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: Theme.textSecondary
                        wrapMode: Text.Wrap
                    }
                }
                ActionButton {
                    text: linked.isArmed ? "Forget it" : "Disconnect"
                    kind: linked.isArmed ? "danger" : "secondary"
                    onClicked: root.disconnectBank(linked.modelData.bridge)
                }
            }
        }
    }
}
