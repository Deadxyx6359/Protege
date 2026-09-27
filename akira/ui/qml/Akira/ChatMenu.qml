import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

/*!
    What can be done to one saved chat: rename it, pin it, move it to another
    project, or delete it.

    Opened from a chat in the sidebar by a right-click, a press and hold, the
    Menu key or Shift+F10. Rename, move and delete open in place, in the same
    small panel, rather than as dialogs over the window: each is one question
    about one chat, and it stays next to the chat it is about.

    Delete asks first, with the focus on Keep. Deleting cannot be undone.
*/
C.Popup {
    id: root
    objectName: "chatMenu"

    /*! The chat bridge. */
    property var chats: null
    /*! [{ id, name }] */
    property var projects: []

    /*! The chat the menu is for: { id, title, pinned, project }. */
    property var chat: ({})
    /*! "menu", "rename", "move" or "delete". */
    property string page: "menu"
    /*! Why the last change did not happen, or "". */
    property string reason: ""

    readonly property bool isOpenChat: !!chats && chat.id === chats.conversationId
    readonly property bool canMove: !(isOpenChat && chats && chats.busy)

    /*! The open chat was moved to \a project: the window follows it there. */
    signal movedOpenChat(string project)

    function openFor(item, x, y, entry) {
        chat = entry;
        page = "menu";
        reason = "";
        const at = item.mapToItem(parent, x, y);
        root.x = at.x;
        root.y = at.y;
        open();
    }

    function show(next) {
        reason = "";
        page = next;
    }

    function rename(text) {
        reason = chats.renameConversation(chat.id, text);
        if (!reason) close();
    }

    function togglePin() {
        reason = chats.pinConversation(chat.id, !chat.pinned);
        if (!reason) close();
    }

    function moveTo(project) {
        if (project === (chat.project || "")) { close(); return; }
        const wasOpen = isOpenChat;
        reason = chats.moveConversation(chat.id, project);
        if (reason) return;
        close();
        if (wasOpen) movedOpenChat(project);
    }

    function remove() {
        chats.deleteConversation(chat.id);
        close();
    }

    onPageChanged: Qt.callLater(function () {
        if (!root.opened) return;
        if (page === "rename") { nameInput.forceActiveFocus(); nameInput.selectAll(); }
        else if (page === "delete") keepButton.forceActiveFocus();
        else if (page === "move") moveList.itemAt(0).forceActiveFocus();
        else firstChoice.forceActiveFocus();
    })
    onOpened: firstChoice.forceActiveFocus()

    width: page === "menu" ? 220 : 300
    padding: 4
    margins: Theme.space.sm
    focus: true
    closePolicy: C.Popup.CloseOnEscape | C.Popup.CloseOnPressOutside

    background: Squircle {
        radius: Theme.radius.sm
        fillColor: Theme.overlay
        borderColor: Theme.separatorStrong
        // A press on the menu stops here. Buttons take their taps passively, so
        // without this a press on "Rename" also reached the chat underneath it.
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
    }

    contentItem: ColumnLayout {
        spacing: 2

        // -- the menu ---------------------------------------------------------

        Choice {
            id: firstChoice
            objectName: "chatMenuRename"
            visible: root.page === "menu"
            label: "Rename…"
            onChosen: root.show("rename")
        }
        Choice {
            objectName: "chatMenuPin"
            visible: root.page === "menu"
            label: root.chat.pinned ? "Unpin" : "Pin to top"
            onChosen: root.togglePin()
        }
        Choice {
            objectName: "chatMenuMove"
            visible: root.page === "menu"
            enabled: root.canMove
            label: "Move to project"
            trailing: "chevronRight"
            onChosen: root.show("move")
        }
        Rectangle {
            visible: root.page === "menu"
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            Layout.topMargin: 2
            Layout.bottomMargin: 2
            color: Theme.separator
        }
        Choice {
            objectName: "chatMenuDelete"
            visible: root.page === "menu"
            label: "Delete…"
            danger: true
            onChosen: root.show("delete")
        }

        // -- rename -----------------------------------------------------------

        Heading { visible: root.page === "rename"; text: "Rename chat" }
        Rectangle {
            visible: root.page === "rename"
            Layout.fillWidth: true
            Layout.margins: Theme.space.xs
            implicitHeight: 32
            radius: Theme.radius.sm
            color: Theme.inset
            border.width: 1
            border.color: nameInput.activeFocus ? Theme.accent : Theme.separator

            C.TextField {
                id: nameInput
                objectName: "chatMenuName"
                anchors.fill: parent
                anchors.leftMargin: Theme.space.sm
                anchors.rightMargin: Theme.space.sm
                text: root.page === "rename" ? (root.chat.title || "") : ""
                maximumLength: 120
                font: Theme.type.callout
                color: Theme.textPrimary
                selectionColor: Theme.accentSubtle
                selectedTextColor: Theme.textPrimary
                selectByMouse: true
                background: null
                padding: 0
                verticalAlignment: TextInput.AlignVCenter
                Accessible.name: "Chat name"
                onAccepted: root.rename(text)
                onTextEdited: root.reason = ""
            }
        }

        // -- move -------------------------------------------------------------

        Heading { visible: root.page === "move"; text: "Move to project" }
        Repeater {
            id: moveList
            model: root.page === "move"
                   ? [{ id: "", name: "Personal workspace" }].concat(root.projects) : []
            Choice {
                required property var modelData
                objectName: "chatMove_" + (modelData.id || "personal")
                label: modelData.name
                trailing: modelData.id === (root.chat.project || "") ? "check" : ""
                onChosen: root.moveTo(modelData.id)
            }
        }

        // -- delete -----------------------------------------------------------

        Heading {
            visible: root.page === "delete"
            text: "Delete “" + (root.chat.title || "this chat") + "”?"
        }
        Text {
            visible: root.page === "delete"
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space.sm
            Layout.rightMargin: Theme.space.sm
            text: "The chat and everything in it is removed from this computer. This cannot be undone."
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }

        // -- why not, and the answer buttons ----------------------------------

        Text {
            objectName: "chatMenuReason"
            visible: root.reason !== ""
            Layout.fillWidth: true
            Layout.margins: Theme.space.xs
            text: root.reason
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.danger
            wrapMode: Text.Wrap
        }

        RowLayout {
            visible: root.page === "rename" || root.page === "delete"
            Layout.fillWidth: true
            Layout.margins: Theme.space.xs
            spacing: Theme.space.sm
            Item { Layout.fillWidth: true }
            ActionButton {
                id: keepButton
                objectName: "chatMenuCancel"
                text: root.page === "delete" ? "Keep" : "Cancel"
                onClicked: root.close()
            }
            ActionButton {
                objectName: "chatMenuConfirm"
                text: root.page === "delete" ? "Delete" : "Save"
                kind: root.page === "delete" ? "danger" : "primary"
                onClicked: root.page === "delete" ? root.remove() : root.rename(nameInput.text)
            }
        }
    }

    component Heading: Text {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.space.sm
        Layout.rightMargin: Theme.space.sm
        Layout.topMargin: Theme.space.xs
        textFormat: Text.PlainText
        font: Theme.type.bodyStrong
        color: Theme.textPrimary
        elide: Text.ElideRight
    }

    /*! One line of the menu. Up and down move between lines. */
    component Choice: Item {
        id: choice
        property string label: ""
        property string trailing: ""
        property bool danger: false
        signal chosen()

        Layout.fillWidth: true
        implicitHeight: 32
        opacity: enabled ? 1 : 0.45
        activeFocusOnTab: true
        Accessible.role: Accessible.MenuItem
        Accessible.name: label
        Accessible.onPressAction: if (enabled) chosen()
        Keys.onReturnPressed: if (enabled) chosen()
        Keys.onEnterPressed: if (enabled) chosen()
        Keys.onSpacePressed: if (enabled) chosen()
        Keys.onDownPressed: nextItemInFocusChain(true).forceActiveFocus()
        Keys.onUpPressed: nextItemInFocusChain(false).forceActiveFocus()

        Rectangle {
            anchors.fill: parent
            radius: Theme.radius.xs
            color: choice.activeFocus || (hover.hovered && choice.enabled)
                   ? Theme.accentSubtle : "transparent"
        }
        Text {
            anchors.left: parent.left
            anchors.right: mark.left
            anchors.leftMargin: Theme.space.sm
            anchors.verticalCenter: parent.verticalCenter
            text: choice.label
            textFormat: Text.PlainText
            font: Theme.type.callout
            color: choice.danger ? Theme.danger : Theme.textPrimary
            elide: Text.ElideRight
        }
        Icon {
            id: mark
            anchors.right: parent.right
            anchors.rightMargin: Theme.space.sm
            anchors.verticalCenter: parent.verticalCenter
            visible: choice.trailing !== ""
            name: choice.trailing || "dot"
            size: 14
            color: Theme.textSecondary
        }
        HoverHandler { id: hover; enabled: choice.enabled; cursorShape: Qt.PointingHandCursor }
        TapHandler {
            enabled: choice.enabled
            gesturePolicy: TapHandler.WithinBounds
            onTapped: choice.chosen()
        }
    }
}
