import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

/*!
    The input.

    Grows with what you type, up to a ceiling, then scrolls. Send is the only
    coloured thing in the resting interface, and it only takes colour once
    there is something to send — so the one saturated pixel on screen always
    means the same thing.
*/
Item {
    id: root

    property string placeholder: "Ask anything"
    property alias text: input.text

    /*! Swaps send for stop while a reply is streaming. */
    property bool busy: false

    /*! Shown under the field. Keep it to a few words. */
    property string footnote: ""
    // The host must supply an attachment flow before advertising this action.
    property bool attachmentsAvailable: false

    readonly property bool hasText: input.text.trim().length > 0

    signal submitted(string text)
    signal stopped()
    signal attachRequested()

    implicitHeight: column.implicitHeight

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        spacing: Theme.space.sm

        Squircle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(52, inputRow.implicitHeight + Theme.space.md)
            radius: Theme.radius.lg
            fillColor: Theme.surface
            borderColor: input.activeFocus ? Theme.accent : Theme.separatorStrong

            Behavior on Layout.preferredHeight {
                NumberAnimation {
                    duration: Theme.duration.fast
                    easing.type: Easing.Bezier
                    easing.bezierCurve: Theme.easing.standard
                }
            }

            RowLayout {
                id: inputRow
                anchors.fill: parent
                anchors.leftMargin: Theme.space.sm
                anchors.rightMargin: Theme.space.sm
                anchors.topMargin: Theme.space.sm
                anchors.bottomMargin: Theme.space.sm
                spacing: Theme.space.xs

                IconButton {
                    visible: root.attachmentsAvailable
                    Layout.alignment: Qt.AlignBottom
                    icon: "attach"
                    size: 34
                    iconSize: 18
                    onClicked: root.attachRequested()
                }

                C.ScrollView {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    // Six lines, then it scrolls. Past that the composer starts
                    // eating the conversation it is meant to be part of.
                    Layout.preferredHeight: Math.min(input.implicitHeight, 140)
                    Layout.minimumHeight: 34

                    C.TextArea {
                        id: input
                        wrapMode: TextEdit.Wrap
                        font: Theme.type.body
                        color: Theme.textPrimary
                        selectionColor: Theme.accentSubtle
                        selectedTextColor: Theme.textPrimary
                        placeholderText: root.placeholder
                        placeholderTextColor: Theme.textTertiary
                        background: null
                        topPadding: Theme.space.xs + 3
                        bottomPadding: Theme.space.xs
                        leftPadding: Theme.space.xs
                        rightPadding: Theme.space.xs

                        Keys.onPressed: function (event) {
                            if (event.key !== Qt.Key_Return && event.key !== Qt.Key_Enter)
                                return;
                            // Shift+Enter is the newline, Enter sends. The
                            // reverse is defensible but every comparable tool
                            // does it this way, and muscle memory outranks
                            // consistency arguments.
                            if (event.modifiers & Qt.ShiftModifier)
                                return;
                            event.accepted = true;
                            root._submit();
                        }
                    }
                }

                Item {
                    Layout.alignment: Qt.AlignBottom
                    Layout.preferredWidth: 34
                    Layout.preferredHeight: 34

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radius.full
                        color: root.busy ? Theme.danger
                             : (root.hasText ? (sendTap.pressed ? Theme.accentPressed
                                                                : Theme.accent)
                                             : Theme.surfaceActive)

                        Behavior on color {
                            ColorAnimation { duration: Theme.duration.fast }
                        }

                        scale: sendTap.pressed ? 0.90 : 1.0
                        Behavior on scale {
                            NumberAnimation {
                                duration: Theme.duration.normal
                                easing.type: Easing.Bezier
                                easing.bezierCurve: Theme.easing.spring
                            }
                        }
                    }

                    Icon {
                        anchors.centerIn: parent
                        name: root.busy ? "stop" : "send"
                        size: 17
                        weight: 2.0
                        color: root.busy ? Theme.textOnDanger
                             : root.hasText ? Theme.textOnAccent : Theme.textTertiary
                    }

                    HoverHandler {
                        cursorShape: root.busy || root.hasText ? Qt.PointingHandCursor
                                                               : Qt.ArrowCursor
                    }
                    TapHandler {
                        id: sendTap
                        onTapped: root.busy ? root.stopped() : root._submit()
                    }
                }
            }
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            visible: root.footnote !== ""
            text: root.footnote
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textTertiary
        }
    }

    function _submit() {
        if (!hasText || busy)
            return;
        const payload = input.text.trim();
        input.clear();
        submitted(payload);
    }

    function focusInput() {
        input.forceActiveFocus();
    }
}
