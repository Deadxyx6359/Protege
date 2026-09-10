import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

/*!
    The conversation.

    Held to a fixed reading column and centred, so a wider window buys margin
    rather than longer lines. Prose stops being comfortable somewhere around 90
    characters and a maximised window on this display is far past that.

    The two speakers are distinguished structurally, not decoratively: what you
    said is a contained bubble, what came back is unbounded text in the column.
    Wrapping the reply in a bubble too would make it look like a quoted fragment
    rather than the body of the page.
*/
Item {
    id: root

    /*! A QAbstractListModel exposing messageId, role, text, isError. */
    property var model: null

    /*! Shows the working indicator beneath the last message. */
    property bool busy: false

    /*! Named in plain language: "Loading Qwen3 8B", "Writing". */
    property string busyStage: "Thinking"

    readonly property int columnWidth: 720
    readonly property int count: model ? model.count : 0

    // -- empty state --------------------------------------------------------

    ColumnLayout {
        anchors.centerIn: parent
        // Optically centred beats geometrically centred when a composer is
        // weighting the bottom of the view.
        anchors.verticalCenterOffset: -Theme.space.xxl
        spacing: Theme.space.md
        visible: root.count === 0
        opacity: visible ? 1 : 0

        Behavior on opacity {
            NumberAnimation { duration: Theme.duration.slow }
        }

        Icon {
            Layout.alignment: Qt.AlignHCenter
            name: "sparkle"
            size: 44
            color: Theme.accent

            SequentialAnimation on opacity {
                running: root.count === 0
                loops: Animation.Infinite
                NumberAnimation { to: 0.55; duration: 2400; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.00; duration: 2400; easing.type: Easing.InOutSine }
            }
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: "How can I help?"
            font: Theme.type.title1
            color: Theme.textPrimary
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: "Everything stays on this machine."
            font: Theme.type.callout
            color: Theme.textTertiary
        }
    }

    // -- transcript ---------------------------------------------------------

    ListView {
        id: list
        anchors.fill: parent
        visible: root.count > 0
        clip: true
        spacing: Theme.space.xl
        topMargin: Theme.space.xl
        bottomMargin: Theme.space.lg

        model: root.model

        /*  Follow the stream only while the reader is already at the bottom.
            Yanking the view down while someone is scrolled up reading an
            earlier answer is the single most irritating thing a chat interface
            can do.  */
        property bool following: true

        function atBottom() {
            return contentY >= contentHeight - height - 24;
        }

        onContentHeightChanged: if (following) positionViewAtEnd()
        onMovementEnded: following = atBottom()
        onCountChanged: {
            following = true;
            Qt.callLater(positionViewAtEnd);
        }

        C.ScrollBar.vertical: C.ScrollBar {}

        delegate: Item {
            id: row

            required property string role
            required property string text
            required property bool isError

            readonly property bool mine: role === "user"

            width: ListView.view.width
            implicitHeight: content.implicitHeight

            Item {
                id: content
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(root.columnWidth, row.width - Theme.space.xxl * 2)
                implicitHeight: row.mine ? minePlate.height : theirs.implicitHeight

                // ---- what you said ----
                Squircle {
                    id: minePlate
                    visible: row.mine
                    anchors.right: parent.right
                    width: Math.min(parent.width * 0.82,
                                    mineText.implicitWidth + Theme.space.lg * 2)
                    height: mineText.implicitHeight + Theme.space.md * 2
                    radius: Theme.radius.md
                    fillColor: Theme.surface

                    Text {
                        id: mineText
                        anchors.fill: parent
                        anchors.margins: Theme.space.md
                        anchors.leftMargin: Theme.space.lg
                        anchors.rightMargin: Theme.space.lg
                        text: row.text
                        font: Theme.type.body
                        color: Theme.textPrimary
                        wrapMode: Text.Wrap
                        lineHeight: Theme.leading.relaxed
                        lineHeightMode: Text.ProportionalHeight
                    }
                }

                // ---- what came back ----
                RowLayout {
                    id: theirs
                    visible: !row.mine
                    width: parent.width
                    spacing: Theme.space.md

                    Icon {
                        Layout.alignment: Qt.AlignTop
                        Layout.topMargin: 2
                        name: row.isError ? "close" : "sparkle"
                        size: 16
                        // An error dressed as an answer is worse than no
                        // answer, so it is coloured as what it is.
                        color: row.isError ? Theme.danger : Theme.accent
                    }

                    MessageBody {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        content: row.text
                        isError: row.isError
                    }
                }
            }
        }

        // -- working indicator ----------------------------------------------

        footer: Item {
            width: list.width
            height: root.busy ? 34 : 0
            visible: root.busy

            RowLayout {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: Theme.space.sm
                width: Math.min(root.columnWidth, list.width - Theme.space.xxl * 2)
                spacing: Theme.space.md

                Icon {
                    name: "sparkle"
                    size: 16
                    color: Theme.accent

                    /*  A named phase with visible motion is the difference
                        between "working" and "hung". A local model can take
                        tens of seconds before the first token; silence that
                        long reads as a crash.  */
                    SequentialAnimation on opacity {
                        running: root.busy
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.3; duration: 700; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: root.busyStage
                    font: Theme.type.body
                    color: Theme.textSecondary
                }
            }
        }
    }
}
