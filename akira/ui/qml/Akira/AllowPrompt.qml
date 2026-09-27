import QtQuick
import QtQuick.Layouts
import QtQuick.Window

/*!
    Asks the person to let the work in progress read one more site or folder.

    Driven by the \c Allow bridge: \c requested(token, request) raises it,
    \c withdrawn(token) takes a stale one down, and \c Allow.answer is the only
    way out. Questions queue, one showing at a time.

    It is a card, not a modal: the work waits for it, but the person can go on
    reading while they decide. Focus starts on "Don't allow", Escape means no,
    and unanswered, it is refused after a few minutes. "Always allow" adds the
    site or folder to the permission, where Settings can take it back.
*/
Item {
    id: root
    objectName: "allowPrompt"

    /*! Waiting questions, oldest first: { token, title, detail, always, kind, who, why }. */
    property var queue: []
    readonly property var current: queue.length > 0 ? queue[0] : null
    property var returnFocus: null

    visible: current !== null
    width: Math.min(460, parent ? parent.width - Theme.space.xl * 2 : 460)
    height: card.implicitHeight

    function _drop(token) {
        queue = queue.filter(function (request) { return request.token !== token; });
    }

    function answer(choice) {
        if (!current)
            return;
        var token = current.token;
        _drop(token);
        Allow.answer(token, choice);
    }

    onCurrentChanged: if (current) {
        if (!returnFocus && root.Window.window) returnFocus = root.Window.window.activeFocusItem;
        refuse.forceActiveFocus();
    } else if (returnFocus) {
        const target = returnFocus;
        returnFocus = null;
        if (target.visible && target.enabled) target.forceActiveFocus();
    }

    Connections {
        target: Allow
        function onRequested(token, request) {
            root.queue = root.queue.concat([Object.assign({ token: token }, request)]);
        }
        function onWithdrawn(token) { root._drop(token); }
    }

    FocusScope {
        anchors.fill: parent
        Keys.onEscapePressed: root.answer("no")

        Squircle {
            anchors.fill: parent
            radius: Theme.radius.lg
            fillColor: Theme.overlay
            borderColor: Theme.separatorStrong
            // A press on the card stops here, not on what is under it.
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
        }

        ColumnLayout {
            id: card
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: Theme.space.sm

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.space.lg
                Layout.leftMargin: Theme.space.lg
                Layout.rightMargin: Theme.space.lg
                spacing: Theme.space.sm
                Icon {
                    name: root.current && root.current.kind === "site" ? "globe" : "folder"
                    size: 18
                    color: Theme.accent
                }
                Text {
                    objectName: "allowTitle"
                    Layout.fillWidth: true
                    text: root.current ? root.current.title : ""
                    textFormat: Text.PlainText
                    font: Theme.type.headline
                    color: Theme.textPrimary
                    elide: Text.ElideRight
                }
            }

            // Verbatim: the whole address or path, so an odd one can be seen.
            Text {
                objectName: "allowDetail"
                Layout.fillWidth: true
                Layout.leftMargin: Theme.space.lg
                Layout.rightMargin: Theme.space.lg
                text: root.current ? root.current.detail : ""
                textFormat: Text.PlainText
                font: Theme.type.monoSmall
                color: Theme.textSecondary
                wrapMode: Text.WrapAnywhere
                maximumLineCount: 4
                elide: Text.ElideRight
            }

            Text {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.space.lg
                Layout.rightMargin: Theme.space.lg
                text: "The work in progress wants to read "
                      + (root.current && root.current.kind === "site" ? "this page. " : "this. ")
                      + "Always adds " + (root.current ? root.current.always : "")
                      + " to what Akira may read, until you remove it in Settings. "
                      + "The work waits for your answer; unanswered, it is refused after "
                      + Math.round(Allow.timeoutSeconds / 60) + " minutes."
                      + (root.queue.length > 1 ? " " + (root.queue.length - 1) + " more waiting." : "")
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textTertiary
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.margins: Theme.space.lg
                Layout.topMargin: Theme.space.xs
                spacing: Theme.space.sm

                ActionButton {
                    id: refuse
                    objectName: "allowRefuse"
                    text: "Don't allow"
                    focus: true
                    KeyNavigation.tab: once
                    onClicked: root.answer("no")
                }
                Item { Layout.fillWidth: true }
                ActionButton {
                    id: once
                    objectName: "allowOnce"
                    text: "Allow once"
                    KeyNavigation.tab: always
                    KeyNavigation.backtab: refuse
                    onClicked: root.answer("once")
                }
                ActionButton {
                    id: always
                    objectName: "allowAlways"
                    text: "Always allow"
                    kind: "primary"
                    KeyNavigation.backtab: once
                    onClicked: root.answer("always")
                }
            }
        }
    }
}
