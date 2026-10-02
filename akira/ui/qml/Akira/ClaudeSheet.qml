import QtQuick
import QtQuick.Layouts

/*!
    Claude Opus 5.5, from the chat window: adding its key, what choosing it sends,
    what it has cost this month, and forgetting the key.

    Opened when Claude is chosen in the composer and no key has been added, or
    from the model menu to manage it. The key is held here only until it is
    handed to \c Chat.connectClaude, then cleared.
*/
Sheet {
    id: root
    objectName: "claudeSheet"
    title: "Claude Opus 5.5"
    subtitle: "Anthropic's model, for the chats you send to it"
    sheetWidth: 520

    property string key: ""
    property string notice: ""
    property bool good: false

    onOpenedChanged: if (!opened) { root.key = ""; root.notice = ""; }

    function connect() {
        root.good = false;
        root.notice = Chat.connectClaude(root.key);
        root.key = "";
    }

    Connections {
        target: Chat
        function onClaudeFinished(ok, message) {
            root.good = ok;
            root.notice = message;
            if (ok) root.close();
        }
    }

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md

        Text {
            Layout.fillWidth: true
            text: "With Claude chosen, each message, and what Akira finds for it in your files and on the web, goes to Anthropic. So does work you hand over with Do it. Local keeps everything on this computer."
            textFormat: Text.PlainText
            font: Theme.type.body
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }

        TextBox {
            objectName: "claudeKey"
            visible: !Chat.claudeConnected
            Layout.fillWidth: true
            label: "Anthropic API key"
            placeholder: "sk-ant-…"
            secret: true
            text: root.key
            onEdited: function (value) { root.key = value; }
            onAccepted: if (root.key.trim() !== "" && !Chat.claudeChecking) root.connect()
        }

        Text {
            Layout.fillWidth: true
            visible: !Chat.claudeConnected
            text: "Make one in the Anthropic Console. It is sealed on this computer and never shown to a model."
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textTertiary
            wrapMode: Text.Wrap
        }

        Text {
            objectName: "claudeSpend"
            Layout.fillWidth: true
            visible: Chat.claudeConnected
            text: Chat.claudeSpend
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }
    }

    footer: ColumnLayout {
        width: parent ? parent.width : 0
        spacing: Theme.space.sm

        Text {
            objectName: "claudeNotice"
            Layout.fillWidth: true
            visible: root.notice !== ""
            text: root.notice
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: root.good ? Theme.textSecondary : Theme.danger
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.sm
            ActionButton {
                objectName: "forgetClaude"
                visible: Chat.claudeConnected
                text: "Forget key"
                kind: "danger"
                onClicked: { root.good = true; root.notice = Chat.forgetClaude(); }
            }
            Item { Layout.fillWidth: true }
            ActionButton {
                text: Chat.claudeConnected ? "Done" : "Not now"
                onClicked: root.close()
            }
            ActionButton {
                objectName: "connectClaude"
                visible: !Chat.claudeConnected
                text: Chat.claudeChecking ? "Checking…" : "Connect"
                kind: "primary"
                enabled: root.key.trim() !== "" && !Chat.claudeChecking
                onClicked: root.connect()
            }
        }
    }
}
