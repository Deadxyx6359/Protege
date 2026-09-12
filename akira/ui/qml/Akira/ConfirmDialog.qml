import QtQuick
import QtQuick.Controls as C
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

    onCurrentChanged: if (current) {
        summaryScroll.contentItem.contentY = 0;
        refuse.forceActiveFocus();
    }

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
        objectName: "confirmPanel"
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
                id: titleRow
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
            C.ScrollView {
                id: summaryScroll
                objectName: "confirmSummaryScroll"
                Layout.fillWidth: true
                // Leave room for the heading, explanation and BOTH decisions.
                // A 5,000-character message must never push Allow off-screen.
                Layout.preferredHeight: Math.min(summaryText.implicitHeight, Math.max(80,
                    root.height - Theme.space.xl * 4 - titleRow.implicitHeight
                    - explanation.implicitHeight - actions.implicitHeight
                    - content.spacing * 3 - Theme.space.sm))
                contentWidth: availableWidth
                rightPadding: 12
                clip: true
                focusPolicy: Qt.StrongFocus
                Accessible.name: "Action details"
                KeyNavigation.tab: refuse
                KeyNavigation.backtab: allow
                C.ScrollBar.horizontal.policy: C.ScrollBar.AlwaysOff
                C.ScrollBar.vertical.policy: C.ScrollBar.AsNeeded
                C.ScrollBar.vertical.active: true

                Keys.onPressed: function (event) {
                    var last = Math.max(0, contentHeight - availableHeight);
                    var next = contentItem.contentY;
                    if (event.key === Qt.Key_Down) next += 32;
                    else if (event.key === Qt.Key_Up) next -= 32;
                    else if (event.key === Qt.Key_PageDown) next += availableHeight;
                    else if (event.key === Qt.Key_PageUp) next -= availableHeight;
                    else if (event.key === Qt.Key_Home) next = 0;
                    else if (event.key === Qt.Key_End) next = last;
                    else { event.accepted = false; return; }
                    contentItem.contentY = Math.max(0, Math.min(last, next));
                    event.accepted = true;
                }

                Text {
                    id: summaryText
                    objectName: "confirmSummary"
                    width: summaryScroll.availableWidth
                    text: root.current ? root.current.summary : ""
                    textFormat: Text.PlainText
                    font: Theme.type.body
                    color: Theme.textPrimary
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                    lineHeight: Theme.leading.normal
                    lineHeightMode: Text.ProportionalHeight
                }
            }

            Text {
                id: explanation
                Layout.fillWidth: true
                text: (summaryScroll.contentHeight > summaryScroll.availableHeight
                       ? "Scroll to read the full action. " : "")
                      + "It cannot be undone once it happens. Unanswered, it is refused after "
                      + Math.round(Confirm.timeoutSeconds / 60) + " minutes."
                      + (root.queue.length > 1 ? " " + (root.queue.length - 1)
                         + " more waiting after this." : "")
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textTertiary
                wrapMode: Text.Wrap
            }

            RowLayout {
                id: actions
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
                    KeyNavigation.tab: allow
                    KeyNavigation.backtab: summaryScroll
                    onClicked: root.answer(false)
                }
                ActionButton {
                    id: allow
                    objectName: "confirmAllow"
                    text: "Allow"
                    kind: "primary"
                    KeyNavigation.tab: summaryScroll
                    KeyNavigation.backtab: refuse
                    onClicked: root.answer(true)
                }
            }
        }
    }
}
