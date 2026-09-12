import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import QtQuick.Layouts

/*!
    Watching: the folders, web pages, feeds and inboxes Akira keeps an eye on,
    and the notices they have put up.

    A watch on its own only turns changes into events; something visible
    happens when a job waits for them. So "Tell me when it changes" pairs a
    watch with a notice job waiting on its events (\c Schedule.jobs names the
    watch each job waits on), and removing the watch removes those jobs too.

    Nothing here grants anything by itself. When a watch is refused for want of
    a permission, the grant it needs is offered right there, with what else it
    allows, and taken only when the person presses the button. Grants are read
    fresh whenever one is changed, so adding a folder or a site never drops one
    allowed elsewhere since.
*/
Item {
    id: root

    /*! What the form watches: "folder", "page", "feed" or "inbox". */
    property string kind: "folder"
    property string folder: ""
    property string address: ""
    /*! File patterns for a folder, words for a page or feed, separated by commas. */
    property string words: ""
    /*! Minutes between looks at a page or feed; 0 is hourly. */
    property int minutes: 0
    property bool tell: true

    property string notice: ""
    /*! What the last refusal needs: "folder", "site", "mailbox", "notices", or "". */
    property string needs: ""

    readonly property var events: ({ folder: "folder.changed", page: "page.changed",
                                     feed: "feed.changed", inbox: "mail.changed" })

    /*! The addresses connected for mail, which an inbox watch chooses from. */
    readonly property var mailboxes: Accounts.accounts
        .filter(function (a) { return a.services.indexOf("mail") >= 0; })
        .map(function (a) { return a.address; })

    /*! The site an address is on, or "". */
    function site(url) {
        var m = /^[a-z][a-z0-9+.-]*:\/\/(?:[^@\/?#]*@)?([^\/:?#]+)/i.exec(String(url).trim());
        return m ? m[1].toLowerCase() : "";
    }

    function split(text) {
        return String(text).split(",").map(function (w) { return w.trim(); })
                           .filter(function (w) { return w !== ""; });
    }

    function label(w) {
        if (w.title)
            return w.title;
        if (w.kind === "folder") {
            var parts = w.folder.replace(/[\\\/]+$/, "").split(/[\\\/]/);
            return parts[parts.length - 1] || w.folder;
        }
        if (w.kind === "inbox")
            return "Inbox of " + w.address;
        return root.site(w.url) || w.url;
    }

    function often(minutes) {
        if (minutes <= 0 || minutes === 60)
            return "hourly";
        if (minutes === 1440)
            return "once a day";
        if (minutes % 60 === 0)
            return "every " + minutes / 60 + " hours";
        return "every " + minutes + " minutes";
    }

    function detail(w) {
        var only = w.patterns.length > 0
            ? (w.kind === "folder" ? "files like " : "mentioning ") + w.patterns.join(", ")
            : ({ folder: "every file", page: "every line", feed: "every entry",
                 inbox: "every message" })[w.kind];
        var what = w.kind === "folder" ? w.folder : w.kind === "inbox" ? w.address : w.url;
        return what + " · " + only + (w.kind === "folder" ? "" : " · " + root.often(w.every));
    }

    function when(at) {
        var d = new Date(at * 1000);
        return d.toDateString() === new Date().toDateString()
            ? Qt.formatTime(d, "hh:mm") : Qt.formatDateTime(d, "d MMM, hh:mm");
    }

    function lastSeen(w) {
        if (!w.lastLook)
            return "Not looked at yet.";
        return "Looked at " + root.when(w.lastLook)
               + (w.lastChange ? " · last change " + root.when(w.lastChange) : " · no change yet");
    }

    /*! The jobs waiting on a watch's events. */
    function jobsFor(id) {
        return Schedule.jobs.filter(function (j) { return j.watch === id; });
    }

    function noticesAllowed() {
        return Permissions.describe("notify.send").granted === true;
    }

    /*! Add one scope to a capability's grant, keeping every scope it holds now. */
    function addScope(capability, scope) {
        var now = Permissions.describe(capability);
        var held = now.granted ? now.scopes : [];
        if (held.indexOf(scope) >= 0)
            return "";
        return Permissions.grant(capability, held.concat([scope]));
    }

    /*! Watch what the form describes. Returns "" or why not. */
    function submit() {
        var target = root.kind === "folder" ? root.folder : root.address.trim();
        return root.watchNow(root.kind, target, root.split(root.words), root.minutes, root.tell);
    }

    function watchNow(kind, target, words, minutes, tell) {
        var before = {};
        Monitor.watches.forEach(function (w) { before[w.id] = true; });
        var why = kind === "folder" ? Monitor.addWatch(target, words)
                : kind === "page" ? Monitor.addPageWatch(target, words, minutes)
                : kind === "inbox" ? Monitor.addInboxWatch(target, words, minutes)
                : Monitor.addFeedWatch(target, words, minutes);
        if (why !== "") {
            root.needs = why.indexOf("Not permitted") < 0 ? ""
                       : ({ folder: "folder", inbox: "mailbox" })[kind] || "site";
            root.notice = why;
            return why;
        }
        root.needs = "";
        root.notice = "";
        root.folder = "";
        root.address = "";
        root.words = "";
        var added = Monitor.watches.filter(function (w) { return !before[w.id]; });
        return tell && added.length > 0 ? root.startTelling(added[0]) : "";
    }

    /*! Pair a watch with a notice job that waits on its events. */
    function startTelling(w) {
        var why = Schedule.addJob({
            name: "Watching " + root.label(w),
            action: "notify",
            trigger: { kind: "event", name: root.events[w.kind], match: { watch: w.id }, cooldown: 60 },
            arguments: { text: w.kind === "folder" ? "Something changed in the folder."
                             : w.kind === "page" ? "The page changed."
                             : w.kind === "inbox" ? "New mail arrived." : "The feed has something new." },
            grants: [{ capability: "notify.send", scopes: [] }],
            missed: "skip"
        });
        if (why !== "") {
            root.notice = why;
            return why;
        }
        if (!root.noticesAllowed()) {
            // The job is made either way; it waits for the permission, not the other way round.
            root.needs = "notices";
            root.notice = "Watching. It will tell you once notices are allowed.";
        }
        return "";
    }

    /*! Grant what the last refusal needed, then watch. Only ever on the person's press. */
    function allowAndWatch() {
        var why = root.needs === "folder" ? root.addScope("files.read", root.folder)
                : root.needs === "site" ? root.addScope("net.http", root.site(root.address))
                : root.needs === "mailbox" ? root.addScope("mail.read", root.address.trim().toLowerCase())
                : "";
        if (why !== "") {
            root.notice = why;
            return why;
        }
        return root.submit();
    }

    function allowNotices() {
        var why = Permissions.grant("notify.send", []);
        root.notice = why;
        if (why === "")
            root.needs = "";
        return why;
    }

    /*! Stop watching, and remove the jobs that waited on it. */
    function forget(id) {
        var waiting = root.jobsFor(id);
        var why = Monitor.removeWatch(id);
        if (why === "")
            for (var i = 0; i < waiting.length; i++)
                Schedule.remove(waiting[i].id);
        root.notice = why;
        return why;
    }

    FolderDialog {
        id: folderPicker
        title: "The folder to watch"
        onAccepted: {
            var text = selectedFolder.toString();
            root.folder = decodeURIComponent(text.indexOf("file:///") === 0 ? text.substring(8) : text);
            root.needs = "";
            root.notice = "";
        }
    }

    // -- pieces ------------------------------------------------------------------

    component Card: Squircle {
        default property alias content: inner.data
        property int pad: Theme.space.lg
        Layout.fillWidth: true
        implicitHeight: inner.implicitHeight + pad * 2
        radius: Theme.radius.md
        fillColor: Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.94)
        borderColor: Theme.separator
        ColumnLayout {
            id: inner
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: parent.pad
            spacing: Theme.space.md
        }
    }

    component Field: Rectangle {
        id: field
        property string text: ""
        property alias placeholder: input.placeholderText
        signal edited(string value)
        signal accepted()
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
            onAccepted: field.accepted()
        }
    }

    // -- the page --------------------------------------------------------------------

    C.ScrollView {
        id: scroller
        anchors.fill: parent
        anchors.topMargin: Theme.space.lg
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: Math.min(820, scroller.availableWidth - Theme.space.xxl * 2)
            x: (scroller.availableWidth - width) / 2
            spacing: Theme.space.lg

            Card {
                RowLayout {
                    Layout.fillWidth: true
                    Icon { name: "eye"; size: 18; color: Theme.accent }
                    Text {
                        Layout.fillWidth: true
                        text: "Watching"
                        font: Theme.type.title3
                        color: Theme.textPrimary
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: "Akira can keep an eye on a folder, a web page, a feed or an inbox, and tell you when something changes. It looks only at what you name here, with the permissions you give it."
                    font: Theme.type.caption
                    color: Theme.textSecondary
                    wrapMode: Text.Wrap
                }
            }

            // -- what they said --------------------------------------------------------
            Card {
                objectName: "noticeList"
                RowLayout {
                    Layout.fillWidth: true
                    SectionLabel { Layout.fillWidth: true; text: "Notices" }
                    ActionButton {
                        visible: Monitor.notices.length > 0
                        text: "Clear"
                        onClicked: Monitor.clearNotices()
                    }
                }
                Text {
                    Layout.fillWidth: true
                    visible: Monitor.notices.length === 0
                    text: "None yet. When a watch tells you something, it appears at the top of the window for a moment and stays here."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                    wrapMode: Text.Wrap
                }
                Repeater {
                    model: Monitor.notices
                    RowLayout {
                        id: note
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: Theme.space.sm
                        Text {
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredWidth: 88
                            text: root.when(note.modelData.at)
                            textFormat: Text.PlainText
                            font: Theme.type.monoSmall
                            color: Theme.textTertiary
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text {
                                Layout.fillWidth: true
                                text: note.modelData.title
                                textFormat: Text.PlainText
                                font: Theme.type.captionStrong
                                color: Theme.textPrimary
                                wrapMode: Text.Wrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: note.modelData.text
                                textFormat: Text.PlainText
                                font: Theme.type.caption
                                color: Theme.textSecondary
                                wrapMode: Text.Wrap
                                maximumLineCount: 6
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }

            // -- what is watched -------------------------------------------------------
            Card {
                objectName: "watchList"
                SectionLabel { text: "What is watched" }
                Text {
                    Layout.fillWidth: true
                    visible: Monitor.watches.length === 0
                    text: "Nothing yet. A folder, page or feed you watch appears here, with when it was last looked at."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                    wrapMode: Text.Wrap
                }
                Repeater {
                    model: Monitor.warnings
                    Text {
                        required property var modelData
                        Layout.fillWidth: true
                        text: modelData
                        textFormat: Text.PlainText
                        font: Theme.type.callout
                        color: Theme.danger
                        wrapMode: Text.Wrap
                    }
                }
                Repeater {
                    model: Monitor.watches
                    RowLayout {
                        id: row
                        required property var modelData
                        readonly property var w: modelData
                        readonly property bool telling: root.jobsFor(w.id).length > 0
                        Layout.fillWidth: true
                        spacing: Theme.space.md
                        Icon {
                            Layout.alignment: Qt.AlignTop
                            name: row.w.kind === "folder" ? "folder" : row.w.kind === "page" ? "globe"
                                : row.w.kind === "inbox" ? "mail" : "feed"
                            size: 18
                            color: row.w.paused !== "" ? Theme.danger : Theme.accent
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text {
                                Layout.fillWidth: true
                                text: root.label(row.w)
                                textFormat: Text.PlainText
                                font: Theme.type.bodyStrong
                                color: Theme.textPrimary
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: root.detail(row.w)
                                textFormat: Text.PlainText
                                font: Theme.type.caption
                                color: Theme.textSecondary
                                elide: Text.ElideMiddle
                            }
                            Text {
                                Layout.fillWidth: true
                                text: row.w.paused !== "" ? row.w.paused : root.lastSeen(row.w)
                                textFormat: Text.PlainText
                                font: Theme.type.caption
                                color: row.w.paused !== "" ? Theme.danger : Theme.textTertiary
                                wrapMode: Text.Wrap
                            }
                        }
                        Text {
                            visible: row.telling
                            text: "Tells you"
                            font: Theme.type.caption
                            color: Theme.success
                        }
                        ActionButton {
                            visible: !row.telling
                            text: "Tell me"
                            onClicked: root.startTelling(row.w)
                        }
                        ActionButton {
                            text: "Remove"
                            onClicked: root.forget(row.w.id)
                        }
                    }
                }
            }

            // -- something new ---------------------------------------------------------
            Card {
                objectName: "watchForm"
                SectionLabel { text: "Watch something new" }

                Segmented {
                    Layout.fillWidth: true
                    options: [
                        { id: "folder", label: "A folder" },
                        { id: "page", label: "A web page" },
                        { id: "feed", label: "A feed" },
                        { id: "inbox", label: "An inbox" }
                    ]
                    current: root.kind
                    onSelected: function (id) {
                        // An address chosen for one kind means nothing to another.
                        var wasMailbox = root.mailboxes.indexOf(root.address) >= 0;
                        if (id === "inbox" && !wasMailbox)
                            root.address = root.mailboxes.length > 0 ? root.mailboxes[0] : "";
                        else if (id !== "inbox" && wasMailbox)
                            root.address = "";
                        root.kind = id;
                        root.needs = "";
                        root.notice = "";
                    }
                }

                RowLayout {
                    visible: root.kind === "inbox"
                    Layout.fillWidth: true
                    spacing: Theme.space.md
                    Text {
                        Layout.fillWidth: true
                        text: root.mailboxes.length > 0 ? "Which inbox"
                              : "No Google address is connected for mail. Connect one in Settings, Accounts."
                        textFormat: Text.PlainText
                        font: root.mailboxes.length > 0 ? Theme.type.body : Theme.type.callout
                        color: root.mailboxes.length > 0 ? Theme.textPrimary : Theme.textSecondary
                        wrapMode: Text.Wrap
                    }
                    Select {
                        visible: root.mailboxes.length > 0
                        Layout.preferredWidth: 280
                        options: root.mailboxes.map(function (a) { return { value: a, label: a }; })
                        current: root.address
                        onPicked: function (value) { root.address = value }
                    }
                }

                RowLayout {
                    visible: root.kind === "folder"
                    Layout.fillWidth: true
                    spacing: Theme.space.sm
                    ActionButton {
                        text: root.folder === "" ? "Choose a folder…" : "Change folder…"
                        onClicked: folderPicker.open()
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.folder === "" ? "No folder chosen." : root.folder
                        textFormat: Text.PlainText
                        font: root.folder === "" ? Theme.type.caption : Theme.type.monoSmall
                        color: Theme.textTertiary
                        elide: Text.ElideMiddle
                    }
                }

                Field {
                    visible: root.kind === "page" || root.kind === "feed"
                    Layout.fillWidth: true
                    text: root.address
                    placeholder: root.kind === "page" ? "The page's address, such as https://example.com/tickets"
                                                      : "The feed's address, such as https://example.com/feed.xml"
                    onEdited: function (value) {
                        root.address = value;
                        root.needs = "";
                    }
                    onAccepted: if (watchButton.enabled) root.submit()
                }

                Field {
                    Layout.fillWidth: true
                    text: root.words
                    placeholder: root.kind === "folder" ? "Only some files? Patterns such as *.pdf, *.docx"
                               : root.kind === "page" ? "Only lines that mention… (words, separated by commas)"
                               : root.kind === "inbox" ? "Only mail that mentions… (words, separated by commas)"
                               : "Only entries that mention… (words, separated by commas)"
                    onEdited: function (value) { root.words = value }
                }

                RowLayout {
                    visible: root.kind !== "folder"
                    Layout.fillWidth: true
                    spacing: Theme.space.md
                    Text {
                        Layout.fillWidth: true
                        text: "How often to look"
                        font: Theme.type.body
                        color: Theme.textPrimary
                    }
                    Select {
                        Layout.preferredWidth: 220
                        options: [
                            { value: "0", label: "Every hour" },
                            { value: "15", label: "Every 15 minutes" },
                            { value: "30", label: "Every 30 minutes" },
                            { value: "180", label: "Every 3 hours" },
                            { value: "1440", label: "Once a day" }
                        ]
                        current: String(root.minutes)
                        onPicked: function (value) { root.minutes = parseInt(value) }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space.md
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text { text: "Tell me when it changes"; font: Theme.type.body; color: Theme.textPrimary }
                        Text {
                            Layout.fillWidth: true
                            text: "A notice appears on screen. Without it, the watch only wakes jobs that wait for it."
                            font: Theme.type.caption
                            color: Theme.textTertiary
                            wrapMode: Text.Wrap
                        }
                    }
                    Toggle {
                        checked: root.tell
                        onToggled: function (value) {
                            root.tell = value;
                            checked = Qt.binding(function () { return root.tell; });
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: root.kind === "folder"
                          ? "Only the names, sizes and times of files are compared. Nothing leaves this computer."
                          : root.kind === "inbox"
                          ? "Akira reads the last week of this inbox " + root.often(root.minutes)
                            + ", up to ten messages a look, and notices what is new. Nothing is sent, "
                            + "deleted or marked read."
                          : "Akira asks " + (root.site(root.address) || "the site") + " for this address "
                            + root.often(root.minutes) + " and sends nothing else. Addresses are shown and "
                            + "logged without the part after a ?, where private feeds keep their keys."
                    textFormat: Text.PlainText
                    font: Theme.type.caption
                    color: Theme.textTertiary
                    wrapMode: Text.Wrap
                }

                // What a refusal needs, offered beside what else it allows.
                RowLayout {
                    visible: root.needs !== ""
                    Layout.fillWidth: true
                    spacing: Theme.space.md
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text {
                            Layout.fillWidth: true
                            text: root.needs === "folder" ? "Allow reading " + root.folder
                                : root.needs === "site" ? "Allow fetching from " + root.site(root.address)
                                : root.needs === "mailbox" ? "Allow reading mail in " + root.address
                                : "Allow notices"
                            textFormat: Text.PlainText
                            font: Theme.type.body
                            color: Theme.textPrimary
                            elide: Text.ElideMiddle
                        }
                        Text {
                            Layout.fillWidth: true
                            text: root.needs === "folder"
                                  ? "Agents may read it too, like any folder you allow. The permission screen can take it away."
                                  : root.needs === "site"
                                  ? "Agents may fetch from it too, like any site you allow. The permission screen can take it away."
                                  : root.needs === "mailbox"
                                  ? "Agents may read it too, like any mailbox you allow. The permission screen can take it away."
                                  : "Lets jobs put a notice on screen. Nothing leaves this computer."
                            textFormat: Text.PlainText
                            font: Theme.type.caption
                            color: Theme.textTertiary
                            wrapMode: Text.Wrap
                        }
                    }
                    ActionButton {
                        objectName: "watchAllow"
                        text: root.needs === "notices" ? "Allow" : "Allow and watch"
                        kind: "primary"
                        onClicked: root.needs === "notices" ? root.allowNotices() : root.allowAndWatch()
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
                        color: root.needs === "notices" ? Theme.textSecondary : Theme.danger
                        wrapMode: Text.Wrap
                    }
                    Item { Layout.fillWidth: root.notice === "" }
                    ActionButton {
                        id: watchButton
                        objectName: "watchStart"
                        text: "Watch"
                        kind: "primary"
                        enabled: root.kind === "folder" ? root.folder !== "" : root.address.trim() !== ""
                        onClicked: root.submit()
                    }
                }
            }

            Item { Layout.preferredHeight: Theme.space.xxl }
        }
    }
}
