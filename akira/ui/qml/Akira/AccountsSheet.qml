import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import QtQuick.Layouts

/*!
    Google accounts: the client file, connecting an address, and what is connected.

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

    title: "Google accounts"
    subtitle: "Gmail and Google Calendar"
    sheetWidth: 640

    property string address: ""
    /*! What to connect, by service id. */
    property var chosen: ["mail", "calendar"]
    property string notice: ""
    property bool good: false
    /*! The address a first press of Disconnect armed. */
    property string armed: ""
    property int revision: 0

    Connections {
        target: Permissions
        function onGrantsChanged() { root.revision += 1 }
    }

    Connections {
        target: Accounts
        function onFinished(ok, message) {
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
    function allow(capability) {
        var now = Permissions.describe(capability);
        var held = now.granted ? now.scopes : [];
        var known = held.map(function (s) { return String(s).toLowerCase(); });
        if (known.indexOf(root.who) >= 0)
            return "";
        root.notice = Permissions.grant(capability, held.concat([root.who]));
        root.good = false;
        return root.notice;
    }

    function chooseClient(path) {
        var why = Accounts.chooseClientFile(path);
        root.notice = why === "" ? "Chosen, and sealed on this computer. You can delete the downloaded copy."
                                 : why;
        root.good = why === "";
        return why;
    }

    function connectNow() {
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
            onTextEdited: field.edited(text)
        }
    }

    // -- the client -------------------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "The Google client" }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.md
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Text {
                    text: Accounts.clientReady ? "Chosen, and sealed on this computer" : "Not chosen yet"
                    textFormat: Text.PlainText
                    font: Theme.type.body
                    color: Theme.textPrimary
                }
                Text {
                    Layout.fillWidth: true
                    text: "In Google Cloud, signed in as the address you made for Akira: make a project, turn on the Gmail API and the Google Calendar API, set up the consent screen as External with that address as a test user, then under Credentials make an OAuth client ID of the Desktop app kind and download its file. Choose it here. Never paste it into a chat."
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
    }

    // -- connecting -------------------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "Connect an address" }

        Field {
            objectName: "accountAddress"
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
                        text: offer.modelData.id === "mail"
                              ? "Search and read messages. Nothing is deleted or marked read."
                              : offer.modelData.id === "send"
                              ? "Send a message when you ask. Each one is shown to you whole, and goes only if you approve it."
                              : "See events. Nothing is added, moved or cancelled."
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
                        text: "Lets Akira, and agents you start, read it. Each request goes to Google with the sign-in, and nowhere else."
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
            Text {
                Layout.fillWidth: true
                visible: root.notice !== ""
                text: root.notice
                textFormat: Text.PlainText
                font: Theme.type.callout
                color: root.good ? Theme.success : Theme.danger
                wrapMode: Text.Wrap
            }
            Item { Layout.fillWidth: root.notice === "" }
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
}
