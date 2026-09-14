import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import QtQuick.Layouts

/*!
    What Akira may do.

    Every capability the application has, grouped the way a person thinks about
    them, with what each one means and what is allowed now. Deny by default, and
    nothing here softens it: there is no "allow all", a scoped capability is
    allowed for the folders, sites or accounts named and nothing wider, and one
    marked "asks each time" still asks each time, whatever is allowed here.

    The bridge refuses what it will not grant, with a reason. The reason is
    shown as it comes, because it says what to do instead.
*/
Sheet {
    id: root

    title: "Permissions"
    subtitle: "Nothing is allowed until you allow it here."
    sheetWidth: 780

    /*! Bumped whenever grants change, so everything that reads them reads again. */
    property int revision: 0
    /*! The bridge's last refusal, or "". */
    property string notice: ""

    readonly property var groups: [
        { name: "Files and programs", domains: ["files", "docs", "shell", "vcs"] },
        { name: "Your notes and memory", domains: ["vault", "memory"] },
        { name: "This computer", domains: ["screen", "clipboard", "location", "audio", "notify"] },
        { name: "The internet", domains: ["net", "web"] },
        { name: "Your accounts", domains: ["mail", "messages", "calendar", "lms", "bank"] },
        { name: "Cloud models", domains: ["model"] }
    ]

    readonly property var placeholders: ({
        host: "A site, such as example.com",
        account: "An account, such as you@example.com",
        provider: "A provider's name"
    })

    Connections {
        target: Permissions
        function onGrantsChanged() { root.revision += 1 }
    }

    function entries(domains) {
        return Permissions.catalogue.filter(function (c) { return domains.indexOf(c.domain) >= 0; });
    }

    function info(id) {
        void root.revision;
        return Permissions.describe(id);
    }

    /*! Allow \a id, unscoped, or take it away. Returns "" or why not. */
    function setGranted(id, on) {
        var why = "";
        if (on)
            why = Permissions.grant(id, []);
        else
            Permissions.revoke(id);
        root.notice = why;
        return why;
    }

    /*! Allow \a id for exactly \a scopes; none takes it away. Returns "" or why not. */
    function setScopes(id, scopes) {
        var why = "";
        if (scopes.length === 0)
            Permissions.revoke(id);
        else
            why = Permissions.grant(id, scopes);
        root.notice = why;
        return why;
    }

    function addScope(id, scope) {
        var text = String(scope).trim();
        if (text === "")
            return "";
        var held = info(id).scopes || [];
        if (held.indexOf(text) >= 0)
            return "";
        return setScopes(id, held.concat([text]));
    }

    function removeScope(id, scope) {
        return setScopes(id, (info(id).scopes || []).filter(function (s) { return s !== scope; }));
    }

    function localPath(url) {
        var text = url.toString();
        if (text.indexOf("file:///") === 0)
            text = text.substring(8);
        return decodeURIComponent(text);
    }

    function when(at) {
        var moment = typeof at === "number" ? new Date(at * 1000) : new Date(at);
        return Qt.formatDateTime(moment, "d MMM hh:mm");
    }

    readonly property var leaving: {
        void root.revision;
        return Permissions.catalogue
            .filter(function (c) { return c.leavesMachine; })
            .map(function (c) { return Permissions.describe(c.id); })
            .filter(function (c) { return c.granted; });
    }

    readonly property var activity: {
        void root.revision;
        return root.opened ? Permissions.recentActivity(40) : [];
    }

    FolderDialog {
        id: folderPicker
        property string target: ""
        title: "Allow a folder"
        onAccepted: root.addScope(target, root.localPath(selectedFolder))
    }

    // -- pieces ------------------------------------------------------------------

    component Badge: Rectangle {
        id: badge
        property string label: ""
        property color tone: Theme.textSecondary
        radius: Theme.radius.xs
        color: Qt.rgba(tone.r, tone.g, tone.b, 0.14)
        implicitWidth: badgeText.implicitWidth + Theme.space.sm * 2
        implicitHeight: 20
        Text {
            id: badgeText
            anchors.centerIn: parent
            text: badge.label
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: badge.tone
        }
    }

    component ScopeChip: Rectangle {
        id: chip
        property string label: ""
        signal removed()
        radius: Theme.radius.xs
        color: Theme.surfaceActive
        implicitHeight: 26
        implicitWidth: chipRow.implicitWidth + Theme.space.sm * 2
        Row {
            id: chipRow
            anchors.centerIn: parent
            spacing: Theme.space.xs
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: chip.label
                textFormat: Text.PlainText
                font: Theme.type.monoSmall
                color: Theme.textPrimary
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                icon: "close"
                size: 18
                iconSize: 11
                flat: true
                onClicked: chip.removed()
            }
        }
    }

    component Field: Rectangle {
        id: field
        property alias text: input.text
        property alias placeholder: input.placeholderText
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
            font: Theme.type.callout
            color: Theme.textPrimary
            placeholderTextColor: Theme.textTertiary
            selectionColor: Theme.accentSubtle
            selectedTextColor: Theme.textPrimary
            verticalAlignment: TextInput.AlignVCenter
            selectByMouse: true
            background: null
            padding: 0
            onAccepted: field.accepted()
        }
    }

    component CapabilityRow: ColumnLayout {
        id: row
        required property var modelData
        readonly property var now: root.info(modelData.id)
        readonly property bool scoped: modelData.scopeKind !== "none"
        readonly property bool held: now.granted === true
        spacing: Theme.space.sm

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.md

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3

                Text {
                    text: row.modelData.title
                    textFormat: Text.PlainText
                    font: Theme.type.bodyStrong
                    color: Theme.textPrimary
                }
                Text {
                    Layout.fillWidth: true
                    text: row.modelData.summary
                    textFormat: Text.PlainText
                    font: Theme.type.caption
                    color: Theme.textSecondary
                    wrapMode: Text.Wrap
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: Theme.space.xs
                    Badge { visible: row.modelData.risk === "high"; label: "High risk"; tone: Theme.warning }
                    Badge { visible: row.modelData.leavesMachine; label: "Leaves this computer"; tone: Theme.info }
                    Badge { visible: row.modelData.irreversible; label: "Asks each time"; tone: Theme.textSecondary }
                }
            }

            Toggle {
                objectName: "grant:" + row.modelData.id
                label: row.modelData.title
                visible: !row.scoped
                checked: row.held
                onToggled: function (value) {
                    root.setGranted(row.modelData.id, value);
                    // The switch sets itself when tapped; bind it back to what is true.
                    checked = Qt.binding(function () { return row.held; });
                }
            }

            ActionButton {
                visible: row.scoped && row.held
                text: "Remove all"
                onClicked: root.setScopes(row.modelData.id, [])
            }
        }

        Flow {
            Layout.fillWidth: true
            visible: row.scoped && row.held
            spacing: Theme.space.xs
            Repeater {
                model: row.now.scopes || []
                ScopeChip {
                    required property var modelData
                    label: modelData
                    onRemoved: root.removeScope(row.modelData.id, modelData)
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: row.scoped
            spacing: Theme.space.sm

            ActionButton {
                visible: row.modelData.scopeKind === "path"
                text: row.held ? "Allow another folder…" : "Allow a folder…"
                onClicked: {
                    folderPicker.target = row.modelData.id;
                    folderPicker.open();
                }
            }

            Field {
                id: entry
                visible: row.modelData.scopeKind !== "path"
                Layout.fillWidth: true
                placeholder: root.placeholders[row.modelData.scopeKind] || ""
                onAccepted: add.clicked()
            }
            ActionButton {
                id: add
                visible: row.modelData.scopeKind !== "path"
                text: "Allow"
                enabled: entry.text.trim() !== ""
                onClicked: {
                    if (root.addScope(row.modelData.id, entry.text) === "")
                        entry.text = "";
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space.xs
            Layout.preferredHeight: 1
            color: Theme.separator
        }
    }

    // -- what leaves this computer ---------------------------------------------------

    Squircle {
        width: parent.width
        height: leavingText.implicitHeight + Theme.space.lg * 2
        radius: Theme.radius.sm
        fillColor: Theme.inset
        borderColor: Theme.separator

        RowLayout {
            anchors.fill: parent
            anchors.margins: Theme.space.lg
            spacing: Theme.space.sm
            Icon {
                Layout.alignment: Qt.AlignTop
                name: "globe"
                size: 16
                color: root.leaving.length > 0 ? Theme.info : Theme.success
            }
            Text {
                id: leavingText
                Layout.fillWidth: true
                text: root.leaving.length === 0
                      ? "Nothing you have allowed sends anything off this computer."
                      : "Allowed to send something off this computer: "
                        + root.leaving.map(function (c) {
                              return c.title + (c.scopes.length ? " (" + c.scopes.join(", ") + ")" : "");
                          }).join("; ") + "."
                textFormat: Text.PlainText
                font: Theme.type.callout
                color: Theme.textPrimary
                wrapMode: Text.Wrap
            }
        }
    }

    Text {
        objectName: "permissionsNotice"
        width: parent.width
        visible: root.notice !== ""
        text: root.notice
        textFormat: Text.PlainText
        font: Theme.type.callout
        color: Theme.danger
        wrapMode: Text.Wrap
    }

    // -- the capabilities ------------------------------------------------------------

    Repeater {
        model: root.groups

        ColumnLayout {
            id: group
            required property var modelData
            width: parent ? parent.width : 0
            spacing: Theme.space.md

            SectionLabel { text: group.modelData.name }

            Repeater {
                model: root.entries(group.modelData.domains)
                CapabilityRow { Layout.fillWidth: true }
            }
        }
    }

    // -- the record --------------------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.xs

        SectionLabel { text: "Recent activity" }

        Text {
            visible: root.activity.length === 0
            text: "Nothing has been done or refused yet."
            font: Theme.type.caption
            color: Theme.textTertiary
        }

        Repeater {
            model: root.activity

            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.space.sm

                Text {
                    text: root.when(parent.modelData.at)
                    textFormat: Text.PlainText
                    font: Theme.type.monoSmall
                    color: Theme.textTertiary
                }
                Text {
                    text: parent.modelData.allowed ? "done" : "refused"
                    textFormat: Text.PlainText
                    font: Theme.type.captionStrong
                    color: parent.modelData.allowed ? Theme.success : Theme.danger
                }
                Text {
                    Layout.fillWidth: true
                    text: parent.modelData.actor + " · " + parent.modelData.action
                          + (parent.modelData.detail ? " — " + parent.modelData.detail : "")
                    textFormat: Text.PlainText
                    font: Theme.type.caption
                    color: Theme.textSecondary
                    elide: Text.ElideRight
                }
            }
        }
    }

    RowLayout {
        width: parent.width

        Item { Layout.fillWidth: true }

        ActionButton {
            id: panic
            property bool armed: false
            text: armed ? "Press again to take everything away" : "Take everything away"
            kind: "danger"
            onClicked: {
                if (armed) {
                    Permissions.revokeAll();
                    armed = false;
                } else {
                    armed = true;
                    disarm.restart();
                }
            }
            Timer {
                id: disarm
                interval: 4000
                onTriggered: panic.armed = false
            }
        }
    }
}
