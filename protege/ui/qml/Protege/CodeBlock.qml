import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts
import "messageblocks.js" as Blocks

/*!
    A fenced code block.

    Scrolls horizontally rather than wrapping. A wrapped line of code is harder
    to read than one that runs off the edge, because the wrap point carries no
    meaning and the eye keeps mistaking continuations for new statements.
*/
Item {
    id: root

    /*  Not `required`: a Loader cannot initialise required properties, and
        this block is filled in after loading so that a streaming fence can
        keep updating it.  */
    property string code: ""

    /*! Fence tag, e.g. "python". Empty renders no label. */
    property string lang: ""

    /*! True while the closing fence has not arrived. Suppresses copy — offering
        to copy something still being written invites copying half of it. */
    property bool streaming: false

    implicitHeight: plate.height

    Squircle {
        id: plate
        width: parent.width
        height: header.height + body.height + Theme.space.sm
        radius: Theme.radius.sm
        fillColor: Theme.inset
        borderColor: Theme.separator
    }

    // -- header -------------------------------------------------------------

    Item {
        id: header
        width: parent.width
        height: 30

        Text {
            anchors.left: parent.left
            anchors.leftMargin: Theme.space.md
            anchors.verticalCenter: parent.verticalCenter
            text: Blocks.languageLabel(root.lang)
            // The tag after the fence is the model's, so it is plain text.
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textTertiary
        }

        Row {
            anchors.right: parent.right
            anchors.rightMargin: Theme.space.xs
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.space.xxs

            Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: copied.running
                text: "Copied"
                font: Theme.type.caption
                color: Theme.success
            }

            IconButton {
                visible: !root.streaming
                icon: "copy"
                size: 24
                iconSize: 14
                flat: true
                onClicked: root.copy()
            }
        }
    }

    // -- code ---------------------------------------------------------------

    C.ScrollView {
        id: body
        anchors.top: header.bottom
        width: parent.width
        height: Math.min(codeText.implicitHeight + Theme.space.sm, 420)

        C.ScrollBar.horizontal.policy: C.ScrollBar.AsNeeded
        C.ScrollBar.vertical.policy: C.ScrollBar.AsNeeded

        TextEdit {
            id: codeText
            text: root.code
            leftPadding: Theme.space.md
            rightPadding: Theme.space.md
            bottomPadding: Theme.space.sm

            font: Theme.type.mono
            color: Theme.textPrimary
            selectionColor: Theme.accentSubtle
            selectedTextColor: Theme.textPrimary

            // Selectable so a fragment can be taken without the whole block,
            // but never editable — this is a transcript, not a scratch pad.
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.NoWrap
            textFormat: TextEdit.PlainText
        }
    }

    Timer {
        id: copied
        interval: 1600
    }

    /*! Put the code on the clipboard.

        Goes through TextEdit's own copy() because QML exposes no clipboard API
        of its own, and routing it through Python would put a UI concern in the
        bridge. */
    function copy() {
        codeText.selectAll();
        codeText.copy();
        codeText.deselect();
        copied.restart();
    }
}
