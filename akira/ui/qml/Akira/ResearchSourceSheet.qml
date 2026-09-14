import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

Sheet {
    id: root
    title: Agents.sourcePreview.title || "Source preview"
    subtitle: Agents.sourcePreview.kind || "Saved reference"
    sheetWidth: 800
    property string notice: ""
    function present(error) { notice = error; open(); }
    onOpenedChanged: if (!opened) Agents.clearSource()
    ColumnLayout {
        width: parent.width
        height: Math.max(260, root.sheetMaxHeight - 125)
        spacing: 14
        Text {
            Layout.fillWidth: true
            text: Agents.sourcePreview.locator || ""
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textSecondary
            wrapMode: Text.WrapAnywhere
        }
        Text {
            Layout.fillWidth: true
            text: root.notice || (Agents.sourcePreview.kind === "Search result" ? "Search snippet only. The page was not read by this tool call."
                  : Agents.sourcePreview.body ? "Text returned during the investigation. No new source is opened by this preview." : "This preview is no longer available under the current project or permissions.")
            textFormat: Text.PlainText
            font: Theme.type.callout
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }
        C.ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            C.TextArea {
                objectName: "researchSourceBody"
                text: Agents.sourcePreview.body || ""
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                font: Theme.type.body
                color: Theme.textPrimary
                background: null
                Accessible.name: "Gathered source text"
            }
        }
        Text { visible: Agents.sourcePreview.truncated === true; text: "Preview shortened. The source reader or display limit was reached."; font: Theme.type.caption; color: Theme.textSecondary }
    }
}
