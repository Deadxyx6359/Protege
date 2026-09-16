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

    /*! True when an animated backdrop is behind this view.

        The empty state then sits on a translucent card instead of directly on
        the scene. White text over a summer sky is unreadable, and dimming the
        whole scene to fix one paragraph throws away the reason it is there. */
    property bool onScene: false
    property bool showGreeting: true
    property string greetingTitle: "How can I help?"
    property string greetingSubtitle: "Your conversations stay on this machine."
    property string actionLabel: ""
    signal primaryActionRequested()
    property var sources: []
    property string contextNote: ""

    readonly property int columnWidth: 720
    readonly property int count: model ? model.count : 0

    // -- empty state --------------------------------------------------------

    Squircle {
        anchors.centerIn: greeting
        width: greeting.width + Theme.space.xxxl * 2
        height: greeting.height + Theme.space.xl * 2
        radius: Theme.radius.lg
        visible: root.showGreeting && root.onScene && root.count === 0
        // Translucent rather than opaque: the scene should still be visible
        // through it, the way a widget sits on a wallpaper.
        fillColor: Qt.rgba(Theme.canvas.r, Theme.canvas.g, Theme.canvas.b, 0.88)
        borderColor: Theme.separator
        opacity: root.count === 0 ? 1 : 0

        Behavior on opacity {
            NumberAnimation { duration: Theme.duration.slow }
        }
    }

    ColumnLayout {
        id: greeting
        anchors.centerIn: parent
        // Optically centred beats geometrically centred when a composer is
        // weighting the bottom of the view.
        anchors.verticalCenterOffset: -Theme.space.xxl
        spacing: Theme.space.md
        visible: root.showGreeting && root.count === 0
        opacity: visible ? 1 : 0

        Behavior on opacity {
            NumberAnimation { duration: Theme.duration.slow }
        }

        BrandMark {
            Layout.alignment: Qt.AlignHCenter
            size: 64
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: root.greetingTitle
            textFormat: Text.PlainText
            font: Theme.type.title1
            color: Theme.textPrimary
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: root.greetingSubtitle
            textFormat: Text.PlainText
            font: Theme.type.callout
            color: Theme.textSecondary
        }
        ActionButton {
            objectName: "workspacePrimaryAction"
            Layout.alignment: Qt.AlignHCenter
            visible: !!root.actionLabel
            text: root.actionLabel
            enabled: !root.busy
            onClicked: root.primaryActionRequested()
        }
    }

    // -- transcript ---------------------------------------------------------

    ListView {
        id: list
        anchors.fill: parent
        anchors.bottomMargin: contextSources.visible ? contextSources.height + Theme.space.sm * 2 : 0
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

                    TextEdit {
                        id: mineText
                        anchors.fill: parent
                        anchors.margins: Theme.space.md
                        anchors.leftMargin: Theme.space.lg
                        anchors.rightMargin: Theme.space.lg
                        text: row.text
                        // As typed. Pasted text can carry HTML, and AutoText
                        // would render it and load any picture it names.
                        textFormat: TextEdit.PlainText
                        // What you said can be selected and copied, like the
                        // reply. Read-only: the record of what was sent.
                        readOnly: true
                        selectByMouse: true
                        selectionColor: Theme.accent
                        selectedTextColor: Theme.textOnAccent
                        font: Theme.type.body
                        color: Theme.textPrimary
                        wrapMode: TextEdit.Wrap
                    }
                }

                // ---- what came back ----
                RowLayout {
                    id: theirs
                    visible: !row.mine
                    width: parent.width
                    spacing: Theme.space.md

                    Item {
                        Layout.alignment: Qt.AlignTop
                        Layout.topMargin: 2
                        Layout.preferredWidth: 32
                        Layout.preferredHeight: 32
                        BrandMark { visible: !row.isError; size: 32 }
                        Icon {
                            anchors.centerIn: parent
                            visible: row.isError
                            name: "close"
                            size: 18
                            color: Theme.danger
                        }
                    }

                    MessageBody {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        content: row.text
                        isError: row.isError
                        onLinkActivated: function (url) { Links.ask(url); }
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
                        running: root.busy && root.visible && Theme.motionScale > 0
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.3; duration: 700; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: root.busyStage
                    textFormat: Text.PlainText
                    font: Theme.type.body
                    color: Theme.textSecondary
                }
            }
        }
    }

    ContextSources {
        id: contextSources
        objectName: "contextSources"
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.space.sm
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(root.columnWidth, root.width - Theme.space.xxl * 2)
        height: implicitHeight
        maximumHeight: Math.max(80, root.height * 0.35)
        sources: root.count > 0 ? root.sources : []
        note: root.count > 0 ? root.contextNote : ""
    }
}
