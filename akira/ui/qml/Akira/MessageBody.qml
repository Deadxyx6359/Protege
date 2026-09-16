import QtQuick
import QtQuick.Layouts
import "messageblocks.js" as Blocks

/*!
    A reply, rendered as prose and code rather than as one string.

    Model output is Markdown. Shown as plain text it is full of literal
    asterisks and backticks; shown as one Markdown element, code blocks inherit
    a proportional font and a wrapping measure, which is worse. So it is split,
    and each kind is rendered by something suited to it.
*/
Column {
    id: root

    /*! Raw reply text, Markdown included. */
    property string content: ""

    /*! Errors are shown in full, unparsed — an exception is not Markdown. */
    property bool isError: false

    /*! A link in the reply was clicked. The window asks before opening it:
        following an address is an outward action, and the address is the
        model's, not the person's. */
    signal linkActivated(string url)

    spacing: Theme.space.md

    /*  Re-parsed on every token while streaming, which is quadratic in the
        length of the reply. At a few kilobytes and tens of tokens a second
        that is not measurable; if replies ever get much longer, this is the
        line to revisit.  */
    readonly property var blocks: root.isError ? [] : Blocks.parse(root.content)

    TextEdit {
        width: parent.width
        visible: root.isError
        text: root.content
        font: Theme.type.body
        color: Theme.danger
        wrapMode: TextEdit.Wrap
        textFormat: TextEdit.PlainText
        // Readable and copyable, never editable: an error is most useful in a
        // search box or a bug report, which means it has to be selectable.
        readOnly: true
        selectByMouse: true
        selectionColor: Theme.accent
        selectedTextColor: Theme.textOnAccent
    }

    Repeater {
        model: root.blocks

        Loader {
            required property var modelData
            width: root.width
            sourceComponent: modelData.type === "code" ? codeBlock : proseBlock

            onLoaded: {
                if (modelData.type === "code") {
                    item.code = modelData.content;
                    item.lang = modelData.lang;
                    item.streaming = modelData.open;
                } else {
                    item.text = modelData.content;
                }
            }

            // A streaming block changes content after it loads, so the values
            // have to be pushed again rather than only set once.
            Connections {
                target: root
                function onBlocksChanged() {
                    if (!parent.item)
                        return;
                    if (parent.modelData.type === "code") {
                        parent.item.code = parent.modelData.content;
                        parent.item.streaming = parent.modelData.open;
                    } else {
                        parent.item.text = parent.modelData.content;
                    }
                }
            }
        }
    }

    Component {
        id: proseBlock

        TextEdit {
            width: root.width
            font: Theme.type.body
            color: Theme.textPrimary
            wrapMode: TextEdit.Wrap
            // Qt renders headings, emphasis, lists, quotes and inline code.
            textFormat: TextEdit.MarkdownText
            /*  A reply is reading matter, so it behaves like reading matter:
                the words can be selected and copied, and it can never be
                edited. Clicking a link does not open it here — it is handed to
                the window, which shows the whole address and asks, because
                opening one is an outward action and the address is the
                model's.  */
            readOnly: true
            selectByMouse: true
            selectionColor: Theme.accent
            selectedTextColor: Theme.textOnAccent
            onLinkActivated: function (link) { root.linkActivated(link); }

            HoverHandler {
                cursorShape: parent.hoveredLink !== "" ? Qt.PointingHandCursor
                                                       : Qt.IBeamCursor
            }
        }
    }

    Component {
        id: codeBlock

        CodeBlock { width: root.width }
    }
}
