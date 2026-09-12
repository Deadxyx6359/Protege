import QtQuick
import QtQuick.Layouts

/*!
    Asks the person to approve one irreversible action.

    Driven by the \c Confirm bridge: \c requested(token, summary) raises it,
    \c withdrawn(token) takes a stale one down, and \c Confirm.answer is the only
    way out. Requests queue, one showing at a time, so an answer can only land on
    the question it was given for.

    Focus starts on "Don't allow". Escape means no. A click outside does nothing:
    the question stays until it is answered or runs out of time, and the bridge
    treats running out of time, or the window closing, as no. There is no
    "don't ask again", and there must never be one.
*/
Item {
    id: root

    anchors.fill: parent
    z: 100
    visible: queue.length > 0

    /*! Waiting questions, oldest first: { token, summary }. */
    property var queue: []
    readonly property var current: queue.length > 0 ? queue[0] : null

    function _drop(token) {
        queue = queue.filter(function (request) { return request.token !== token; });
    }

    function answer(approved) {
        if (!current)
            return;
        var token = current.token;
        _drop(token);
        Confirm.answer(token, approved);
    }

    onCurrentChanged: if (current) refuse.forceActiveFocus()

    Connections {
        target: Confirm
        function onRequested(token, summary) {
            root.queue = root.queue.concat([{ token: token, summary: summary }]);
        }
        function onWithdrawn(token) { root._drop(token); }
    }

    // Modal: swallows every press around it, and answers none of them.
    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
        TapHandler {}
        WheelHandler {}
    }

    FocusScope {
        id: panel
        anchors.centerIn: parent
        width: Math.min(520, root.width - Theme.space.xxl * 2)
        height: content.implicitHeight + Theme.space.xl * 2

        Keys.onEscapePressed: root.answer(false)

        Squircle {
            anchors.fill: parent
            radius: Theme.radius.lg
            fillColor: Theme.overlay
            borderColor: Theme.separatorStrong
        }

        TapHandler {}

        ColumnLayout {
            id: content
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.space.xl
            spacing: Theme.space.md

            RowLayout {
                spacing: Theme.space.sm
                Icon { name: "shield"; size: 20; color: Theme.warning }
                Text {
                    Layout.fillWidth: true
                    text: "Allow this?"
                    font: Theme.type.title3
                    color: Theme.textPrimary
                }
            }

            // Verbatim: it names the real file, command, address or message.
            Text {
                objectName: "confirmSummary"
                Layout.fillWidth: true
                text: root.current ? root.current.summary : ""
                textFormat: Text.PlainText
                font: Theme.type.body
                color: Theme.textPrimary
                wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                lineHeight: Theme.leading.normal
                lineHeightMode: Text.ProportionalHeight
            }

            Text {
                Layout.fillWidth: true
                text: "It cannot be undone once it happens. Unanswered, it is refused after "
                      + Math.round(Confirm.timeoutSeconds / 60) + " minutes."
                      + (root.queue.length > 1 ? " " + (root.queue.length - 1)
                         + " more waiting after this." : "")
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
                    objectName: "confirmRefuse"
                    text: "Don't allow"
                    kind: "secondary"
                    focus: true
                    onClicked: root.answer(false)
                }
                ActionButton {
                    objectName: "confirmAllow"
                    text: "Allow"
                    kind: "primary"
                    onClicked: root.answer(true)
                }
            }
        }
    }
}
