import QtQuick
import QtQuick.Window
import QtQuick.Layouts

/*!
    Asks before a link in a reply is opened.

    The links in a reply are the model's words, and the words of a link say one
    thing while the address goes wherever it likes. Opening one leaves Akira
    altogether: it hands the address to the person's own browser, where they are
    signed in to things. So the whole address is shown, as plain text they can
    read and copy, and nothing is opened without a yes.

    Only http and https are offered. Anything else — a file, a program's own
    handler — is shown and refused, because a click on a line of text must never
    start a program.
*/
Item {
    id: root

    anchors.fill: parent
    z: 90
    visible: address !== ""

    /*! The address in question. Empty when nothing is being asked. */
    property string address: ""

    /*! Whether this is an address a browser opens, rather than anything else. */
    readonly property bool openable: /^https?:\/\/[^\s]+$/i.test(root.address)

    property var returnFocus: null

    function ask(url) {
        const text = String(url).trim();
        if (text === "")
            return;
        if (!root.returnFocus && root.Window.window)
            root.returnFocus = root.Window.window.activeFocusItem;
        root.address = text;
        refuse.forceActiveFocus();
    }

    function dismiss() {
        root.address = "";
        const target = root.returnFocus;
        root.returnFocus = null;
        if (target && target.visible && target.enabled)
            target.forceActiveFocus();
    }

    function open() {
        if (!root.openable)
            return;
        Qt.openUrlExternally(root.address);
        root.dismiss();
    }

    Connections {
        target: Links
        function onRequested(url) { root.ask(url); }
    }

    // Modal: a press anywhere around it means no.
    Rectangle {
        anchors.fill: parent
        color: Theme.scrim

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: root.dismiss()
        }
        WheelHandler {}
    }

    FocusScope {
        id: panel
        objectName: "linkPanel"
        anchors.centerIn: parent
        width: Math.min(520, root.width - Theme.space.xxl * 2)
        height: content.implicitHeight + Theme.space.xl * 2

        Keys.onEscapePressed: root.dismiss()

        Squircle {
            anchors.fill: parent
            radius: Theme.radius.lg
            fillColor: Theme.overlay
            borderColor: Theme.separatorStrong
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
        }

        ColumnLayout {
            id: content
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.space.xl
            spacing: Theme.space.md

            RowLayout {
                spacing: Theme.space.sm
                Icon { name: "globe"; size: 20; color: Theme.accent }
                Text {
                    Layout.fillWidth: true
                    text: root.openable ? "Open this in your browser?"
                                        : "This is not a web address"
                    textFormat: Text.PlainText
                    font: Theme.type.title3
                    color: Theme.textPrimary
                }
            }

            // Verbatim, and selectable: the address is what is being decided on.
            TextEdit {
                objectName: "linkAddress"
                Layout.fillWidth: true
                text: root.address
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                selectionColor: Theme.accent
                selectedTextColor: Theme.textOnAccent
                font: Theme.type.body
                color: Theme.textPrimary
                wrapMode: TextEdit.WrapAnywhere
            }

            Text {
                Layout.fillWidth: true
                text: root.openable
                      ? "It opens outside Akira, in the browser you are signed in to. "
                        + "The words of a link are not its address: this is. Akira has "
                        + "not opened it, and an address a model wrote may lead nowhere."
                      : "Akira opens http and https addresses only. Nothing was opened."
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textTertiary
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.space.sm
                spacing: Theme.space.sm

                Item { Layout.fillWidth: true }

                ActionButton {
                    id: refuse
                    objectName: "linkRefuse"
                    text: root.openable ? "Don't open" : "Close"
                    kind: "secondary"
                    focus: true
                    KeyNavigation.tab: root.openable ? accept : refuse
                    onClicked: root.dismiss()
                }
                ActionButton {
                    id: accept
                    objectName: "linkOpen"
                    visible: root.openable
                    text: "Open"
                    kind: "primary"
                    KeyNavigation.tab: refuse
                    onClicked: root.open()
                }
            }
        }
    }
}
