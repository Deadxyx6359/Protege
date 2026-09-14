import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import QtQuick.Layouts

/*!
    Memory: notes distilled from conversations, waiting for a person.

    Each night the memory job reads recent conversations and proposes notes for
    the vault. Nothing reaches the vault until it is accepted here, and what
    waits cannot shape an answer, so each proposal is shown as it would be
    written: the whole note, or the lines it adds to one. The preview is the
    model's writing about the person's own conversations, so it is plain text.

    The job needs two grants, offered beside the vault they concern: reading
    conversations (\c memory.read) and reading the vault (\c vault.read).
    Accepting needs writing, and when it is refused, writing is offered for the
    folder that note goes in, never the whole vault. Every grant is taken only
    on the person's press, and read fresh so no other folder is dropped.
*/
Item {
    id: root

    property string notice: ""
    /*! "write" when accepting was refused for want of it, else "". */
    property string needs: ""
    /*! The proposal waiting on that permission. */
    property string waiting: ""
    property int revision: 0

    Connections {
        target: Permissions
        function onGrantsChanged() { root.revision += 1 }
    }

    readonly property bool remembers: {
        void root.revision;
        return Permissions.describe("memory.read").granted === true;
    }
    readonly property bool readsVault: {
        void root.revision;
        return Memory.vault !== "" && root.covers("vault.read", Memory.vault);
    }

    function slashed(path) { return String(path).replace(/\\/g, "/"); }
    function norm(path) { return root.slashed(path).replace(/\/+$/, "").toLowerCase(); }

    /*! Whether a grant appears to cover a path. For display; the bridge decides. */
    function covers(capability, path) {
        var held = Permissions.describe(capability);
        if (held.granted !== true)
            return false;
        var target = root.norm(path);
        return (held.scopes || []).some(function (s) {
            var scope = root.norm(s);
            return target === scope || target.indexOf(scope + "/") === 0;
        });
    }

    /*! The folder a note goes in, inside the vault. */
    function folderOf(target) {
        var cut = target.lastIndexOf("/");
        var vault = root.slashed(Memory.vault).replace(/\/+$/, "");
        return cut > 0 ? vault + "/" + target.substring(0, cut) : vault;
    }

    function proposal(id) {
        var all = Memory.pending;
        for (var i = 0; i < all.length; i++)
            if (all[i].id === id)
                return all[i];
        return null;
    }

    function when(at) {
        var d = new Date(at * 1000);
        return d.toDateString() === new Date().toDateString()
            ? "today at " + Qt.formatTime(d, "hh:mm") : Qt.formatDate(d, "d MMM");
    }

    /*! Add one scope to a capability's grant, keeping every scope it holds now. */
    function addScope(capability, scope) {
        var now = Permissions.describe(capability);
        var held = now.granted ? now.scopes : [];
        if (held.some(function (s) { return root.norm(s) === root.norm(scope); }))
            return "";
        return Permissions.grant(capability, held.concat([scope]));
    }

    function removeScope(capability, scope) {
        var now = Permissions.describe(capability);
        var rest = (now.scopes || []).filter(function (s) { return root.norm(s) !== root.norm(scope); });
        if (rest.length === 0) {
            Permissions.revoke(capability);
            return "";
        }
        return Permissions.grant(capability, rest);
    }

    function chooseVault(path) {
        root.notice = Memory.setVault(path);
        return root.notice;
    }

    function setRemembering(on) {
        var why = "";
        if (on)
            why = Permissions.grant("memory.read", []);
        else
            Permissions.revoke("memory.read");
        root.notice = why;
        return why;
    }

    function setReading(on) {
        root.notice = on ? root.addScope("vault.read", root.slashed(Memory.vault))
                         : root.removeScope("vault.read", Memory.vault);
        return root.notice;
    }

    function distil() {
        root.notice = Memory.distilNow();
        return root.notice;
    }

    function accept(id) {
        var why = Memory.accept(id);
        var refused = why.indexOf("Not permitted") === 0;
        root.needs = refused ? "write" : "";
        root.waiting = refused ? id : "";
        root.notice = why;
        return why;
    }

    /*! Allow writing in the folder the waiting note goes in, then accept it. */
    function allowWritingAndAccept() {
        var p = root.proposal(root.waiting);
        if (p === null) {
            root.needs = "";
            root.waiting = "";
            return "";
        }
        var why = root.addScope("vault.write", root.folderOf(p.target));
        if (why !== "") {
            root.notice = why;
            return why;
        }
        return root.accept(p.id);
    }

    function reject(id) {
        root.needs = "";
        root.waiting = "";
        root.notice = Memory.reject(id);
        return root.notice;
    }

    FolderDialog {
        id: vaultPicker
        title: "The vault to keep memory in"
        onAccepted: {
            var text = selectedFolder.toString();
            root.chooseVault(decodeURIComponent(text.indexOf("file:///") === 0 ? text.substring(8) : text));
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
                    Icon { name: "clock"; size: 18; color: Theme.accent }
                    Text {
                        Layout.fillWidth: true
                        text: "Memory"
                        font: Theme.type.title3
                        color: Theme.textPrimary
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: "Each night Akira reads your recent conversations and proposes notes for your vault. Nothing is written until you accept it, and nothing waiting here can shape an answer."
                    font: Theme.type.caption
                    color: Theme.textSecondary
                    wrapMode: Text.Wrap
                }
                Text {
                    Layout.fillWidth: true
                    visible: root.notice !== "" && root.needs === ""
                    text: root.notice
                    textFormat: Text.PlainText
                    font: Theme.type.callout
                    color: Theme.danger
                    wrapMode: Text.Wrap
                }
            }

            // -- where it is kept ------------------------------------------------------
            Card {
                objectName: "memorySetup"
                SectionLabel { text: "Where memory is kept" }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space.sm
                    ActionButton {
                        text: Memory.vault === "" ? "Choose the vault…" : "Change vault…"
                        onClicked: vaultPicker.open()
                    }
                    Text {
                        Layout.fillWidth: true
                        text: Memory.vault === "" ? "No vault chosen." : Memory.vault
                        textFormat: Text.PlainText
                        font: Memory.vault === "" ? Theme.type.caption : Theme.type.monoSmall
                        color: Theme.textTertiary
                        elide: Text.ElideMiddle
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space.md
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text { text: "Remember past conversations"; font: Theme.type.body; color: Theme.textPrimary }
                        Text {
                            Layout.fillWidth: true
                            text: "Lets the memory job, and agents, read your conversations on this computer."
                            font: Theme.type.caption
                            color: Theme.textTertiary
                            wrapMode: Text.Wrap
                        }
                    }
                    Toggle {
                        objectName: "allowRemembering"
                        label: "Remember conversations"
                        checked: root.remembers
                        onToggled: function (value) {
                            root.setRemembering(value);
                            checked = Qt.binding(function () { return root.remembers; });
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: Memory.vault !== ""
                    spacing: Theme.space.md
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text { text: "Read the vault"; font: Theme.type.body; color: Theme.textPrimary }
                        Text {
                            Layout.fillWidth: true
                            text: "So a proposal adds to a note you already have rather than repeating it. Agents may read the vault too."
                            font: Theme.type.caption
                            color: Theme.textTertiary
                            wrapMode: Text.Wrap
                        }
                    }
                    ActionButton {
                        text: root.readsVault ? "Remove" : "Allow"
                        kind: root.readsVault ? "secondary" : "primary"
                        onClicked: root.setReading(!root.readsVault)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space.sm
                    Text {
                        Layout.fillWidth: true
                        text: Memory.busy ? "Reading conversations…"
                              : Memory.lastRun !== "" ? Memory.lastRun
                              : "It runs at 03:30, or late if this computer was off."
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: Theme.textSecondary
                        wrapMode: Text.Wrap
                    }
                    ActionButton {
                        text: "Read them now"
                        enabled: Memory.vault !== "" && !Memory.busy
                        onClicked: root.distil()
                    }
                }
            }

            // -- waiting ---------------------------------------------------------------
            Card {
                objectName: "memoryPending"
                SectionLabel { text: Memory.pendingCount > 0 ? "Waiting for you · " + Memory.pendingCount : "Waiting for you" }
                Text {
                    Layout.fillWidth: true
                    visible: Memory.pendingCount === 0
                    text: "Nothing waiting."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                }
                Repeater {
                    model: Memory.pending
                    ColumnLayout {
                        id: item
                        required property var modelData
                        readonly property var p: modelData
                        readonly property bool blocked: root.needs === "write" && root.waiting === p.id
                        Layout.fillWidth: true
                        spacing: Theme.space.xs

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.space.sm
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text {
                                    Layout.fillWidth: true
                                    text: item.p.title
                                    textFormat: Text.PlainText
                                    font: Theme.type.bodyStrong
                                    color: Theme.textPrimary
                                    wrapMode: Text.Wrap
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: (item.p.addsTo ? "Adds to " : "A new note, ") + item.p.target
                                          + " · from " + (item.p.sources.join(", ") || "a conversation")
                                          + (item.p.project !== "" ? " in " + item.p.project : "")
                                          + " · " + root.when(item.p.created)
                                    textFormat: Text.PlainText
                                    font: Theme.type.caption
                                    color: Theme.textSecondary
                                    wrapMode: Text.Wrap
                                }
                            }
                            ActionButton {
                                Layout.alignment: Qt.AlignTop
                                text: "Reject"
                                onClicked: root.reject(item.p.id)
                            }
                            ActionButton {
                                Layout.alignment: Qt.AlignTop
                                text: "Accept"
                                kind: "primary"
                                onClicked: root.accept(item.p.id)
                            }
                        }

                        CodeBlock {
                            Layout.fillWidth: true
                            code: item.p.preview
                            lang: item.p.addsTo ? "diff" : "markdown"
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: item.blocked
                            spacing: Theme.space.md
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                Text {
                                    Layout.fillWidth: true
                                    text: "Allow writing in " + root.folderOf(item.p.target)
                                    textFormat: Text.PlainText
                                    font: Theme.type.body
                                    color: Theme.textPrimary
                                    elide: Text.ElideMiddle
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Only that folder of the vault. Agents may write there too, like any folder you allow."
                                    font: Theme.type.caption
                                    color: Theme.textTertiary
                                    wrapMode: Text.Wrap
                                }
                            }
                            ActionButton {
                                text: "Allow and accept"
                                kind: "primary"
                                onClicked: root.allowWritingAndAccept()
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: item.blocked && root.notice !== ""
                            text: root.notice
                            textFormat: Text.PlainText
                            font: Theme.type.caption
                            color: Theme.danger
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: Theme.space.xxl }
        }
    }
}
