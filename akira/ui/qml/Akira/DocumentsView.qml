import QtQuick
import QtQuick.Controls as C
import QtQuick.Dialogs
import QtQuick.Layouts

// Local files stay behind the live permission policy. Every preview and search
// excerpt is plain text, including strings that look like HTML or Markdown.
Rectangle {
    id: root
    color: Theme.canvas
    signal permissionsRequested()
    property string searchMode: "names"
    property string notice: ""
    property string lastFolder: ""
    readonly property bool wide: width >= 880
    readonly property bool hasPreview: !!Documents.selected.path || Documents.operation === "preview"
    readonly property bool hasWork: !!Documents.folder || hasPreview
    readonly property var project: Projects.projects.find(function (p) { return p.current; }) || ({})
    readonly property var rows: Documents.query ? Documents.passages : Documents.entries.filter(function (entry) {
        return root.searchMode !== "names" || entry.name.toLowerCase().indexOf(searchBox.text.trim().toLowerCase()) >= 0;
    })

    function activate(entry) {
        root.notice = "";
        if (entry.folder) Documents.openFolder(entry.path);
        else Documents.previewFile(entry.path);
    }
    function runSearch() {
        if (root.searchMode === "contents" && searchBox.text.trim()) Documents.search(searchBox.text);
    }
    Connections {
        target: Documents
        function onChanged() {
            if (root.lastFolder !== Documents.folder) {
                searchBox.text = "";
                root.notice = "";
                root.lastFolder = Documents.folder;
            }
        }
    }
    Timer { id: copiedTimer; interval: 2400; onTriggered: root.notice = "" }
    FolderDialog {
        id: folderPicker
        title: "Choose a document folder"
        onAccepted: Documents.openFolder(selectedFolder.toString())
    }
    FileDialog {
        id: filePicker
        title: "Preview a document"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Documents (*.docx *.xlsx *.pptx *.pdf *.md *.txt *.doc *.xls *.ppt)"]
        onAccepted: Documents.previewFile(selectedFile.toString())
    }

    component Caption: Text {
        textFormat: Text.PlainText
        font: Theme.type.callout
        color: Theme.textSecondary
        elide: Text.ElideRight
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.wide ? 32 : 20
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            Layout.minimumHeight: 54
            spacing: 12
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Caption { text: "Documents"; font: Theme.type.title2; color: Theme.textPrimary }
                Caption {
                    Layout.fillWidth: true
                    text: Projects.currentName ? "Files for " + Projects.currentName : "Your files, with room to focus."
                }
            }
            ActionButton { text: "Open file"; onClicked: filePicker.open() }
            ActionButton { text: "Choose folder"; kind: "primary"; onClicked: folderPicker.open() }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: feedback.implicitHeight + 24
            visible: !!Documents.error
            radius: Theme.radius.md
            color: Theme.surface
            border.color: Theme.separatorStrong
            RowLayout {
                id: feedback
                anchors.fill: parent
                anchors.margins: 12
                spacing: 12
                Icon { name: "shield"; size: 18; color: Theme.warning }
                Caption {
                    Layout.fillWidth: true
                    objectName: "documentError"
                    text: Documents.error
                    wrapMode: Text.Wrap
                    elide: Text.ElideNone
                }
                IconButton { icon: "shield"; label: "Review permissions"; onClicked: root.permissionsRequested() }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: Documents.busy
            spacing: 10
            Rectangle {
                width: 6; height: 6; radius: 3; color: Theme.accent
                SequentialAnimation on opacity {
                    running: Documents.busy && root.visible && Theme.motionScale > 0
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.35; duration: 650 }
                    NumberAnimation { to: 1; duration: 650 }
                }
            }
            Caption {
                Layout.fillWidth: true
                text: Documents.operation === "folder" ? "Reading folder…"
                    : Documents.operation === "search" ? "Searching document contents…" : "Preparing text preview…"
            }
            ActionButton { text: "Cancel"; onClicked: Documents.cancel() }
        }

        // First visit: a small, practical invitation rather than an empty dashboard.
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !root.hasWork
            C.ScrollView {
                anchors.fill: parent
                contentWidth: availableWidth
                clip: true
                ColumnLayout {
                    width: parent.width
                    spacing: 20
                    Item { Layout.preferredHeight: Math.max(12, (root.height - 570) / 2) }
                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        width: 68; height: 68; radius: 20
                        color: Theme.accentSubtle
                        Icon { anchors.centerIn: parent; name: "document"; size: 30; color: Theme.accent }
                    }
                    ColumnLayout {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.maximumWidth: 460
                        spacing: 10
                        Caption {
                            Layout.fillWidth: true
                            text: "Bring your work into view."
                            font: Theme.type.title2; color: Theme.textPrimary
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                        }
                        Caption {
                            Layout.fillWidth: true
                            text: "Browse a folder, find a passage, or settle into a text preview. Your originals stay as they are."
                            wrapMode: Text.Wrap
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Caption {
                            Layout.fillWidth: true
                            text: "Word · Excel · PowerPoint · PDF · Markdown · Text"
                            font: Theme.type.caption
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                        }
                    }
                    ColumnLayout {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: Math.min(400, root.width - 72)
                        Layout.maximumWidth: 400
                        spacing: 6
                        NavRow {
                            Layout.fillWidth: true
                            visible: !!root.project.folder
                            icon: "folder"; label: "Open project folder"
                            detail: Projects.currentName
                            onClicked: Documents.openFolder(root.project.folder)
                        }
                        Repeater {
                            model: Documents.roots.slice(0, 4)
                            NavRow {
                                required property var modelData
                                Layout.fillWidth: true
                                icon: "folder"; label: modelData.name
                                onClicked: Documents.openFolder(modelData.path)
                            }
                        }
                    }
                    ColumnLayout {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.maximumWidth: 440
                        spacing: 10
                        Caption {
                            Layout.fillWidth: true
                            text: "Choosing a location uses your existing read permissions."
                            font: Theme.type.caption; wrapMode: Text.Wrap
                            horizontalAlignment: Text.AlignHCenter
                        }
                        ActionButton {
                            Layout.alignment: Qt.AlignHCenter
                            text: "Review permissions"; onClicked: root.permissionsRequested()
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.hasWork
            spacing: 20

            ColumnLayout {
                Layout.fillHeight: true
                Layout.fillWidth: !root.wide
                Layout.preferredWidth: root.wide ? 310 : -1
                Layout.minimumWidth: root.wide ? 310 : 0
                visible: !!Documents.folder && (root.wide || !root.hasPreview)
                spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    Icon { name: "folder"; size: 18; color: Theme.accent }
                    Caption {
                        Layout.fillWidth: true
                        text: Documents.folder.replace(/\\/g, "/").split("/").pop() || Documents.folder
                        color: Theme.textPrimary; font: Theme.type.headline
                    }
                    ActionButton { text: "Up"; implicitWidth: 44; enabled: Documents.canGoUp && !Documents.busy; onClicked: Documents.goUp() }
                    IconButton { icon: "refresh"; label: "Refresh folder"; enabled: !Documents.busy; onClicked: Documents.refresh() }
                }
                Caption { Layout.fillWidth: true; text: Documents.folder; elide: Text.ElideMiddle; font: Theme.type.caption }
                RowLayout {
                    Layout.fillWidth: true
                    Select {
                        Layout.fillWidth: true
                        current: root.searchMode
                        options: [{value: "names", label: "Filter file names"}, {value: "contents", label: "Search contents"}]
                        onPicked: function (value) {
                            root.searchMode = value;
                            Documents.search("");
                        }
                    }
                    IconButton { icon: "shield"; label: "Review document permissions"; onClicked: root.permissionsRequested() }
                }
                RowLayout {
                    Layout.fillWidth: true
                    SearchField {
                        id: searchBox
                        objectName: "documentSearch"
                        Layout.fillWidth: true
                        placeholder: root.searchMode === "names" ? "Find a file in this folder" : "Find a passage in this folder"
                        onAccepted: root.runSearch()
                        onTextChanged: if (!text.trim() && Documents.query) Documents.search("")
                    }
                    IconButton {
                        icon: "search"; label: "Search document contents"
                        visible: root.searchMode === "contents"
                        enabled: !!searchBox.text.trim() && !Documents.busy
                        onClicked: root.runSearch()
                    }
                }
                Caption {
                    Layout.fillWidth: true
                    text: Documents.query ? root.rows.length + (root.rows.length === 1 ? " passage · “" : " passages · “") + Documents.query + "”"
                        : root.rows.length + " items" + (root.searchMode === "contents" ? " · Press Enter to search subfolders" : " · This folder")
                    font: Theme.type.caption
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Theme.surface
                    border.color: Theme.separator
                    radius: Theme.radius.md
                    clip: true
                    ListView {
                        id: files
                        objectName: "documentList"
                        anchors.fill: parent
                        anchors.margins: 6
                        model: root.rows
                        spacing: 4
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        activeFocusOnTab: true
                        keyNavigationEnabled: true
                        C.ScrollBar.vertical: C.ScrollBar {}
                        Keys.onReturnPressed: if (currentIndex >= 0 && currentIndex < root.rows.length) root.activate(root.rows[currentIndex])
                        Keys.onEnterPressed: if (currentIndex >= 0 && currentIndex < root.rows.length) root.activate(root.rows[currentIndex])
                        delegate: Rectangle {
                            id: row
                            required property var modelData
                            required property int index
                            readonly property bool chosen: Documents.selected.path === modelData.path
                            width: files.width
                            height: rowContent.implicitHeight + 24
                            radius: Theme.radius.sm
                            color: chosen ? Theme.accentSubtle : rowHover.hovered ? Theme.surfaceHover : "transparent"
                            border.color: (files.activeFocus && files.currentIndex === index) ? Theme.accent : "transparent"
                            Accessible.role: Accessible.ListItem
                            Accessible.name: modelData.name
                            Accessible.onPressAction: root.activate(modelData)
                            HoverHandler { id: rowHover }
                            TapHandler { onTapped: { files.currentIndex = row.index; files.forceActiveFocus(); root.activate(row.modelData) } }
                            RowLayout {
                                id: rowContent
                                anchors.left: parent.left; anchors.right: parent.right
                                anchors.top: parent.top; anchors.margins: 12
                                spacing: 10
                                Icon {
                                    Layout.alignment: Qt.AlignTop
                                    name: row.modelData.folder ? "folder" : "document"
                                    size: 18
                                    color: row.chosen || row.modelData.folder ? Theme.accent : Theme.textSecondary
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 4
                                    Caption { Layout.fillWidth: true; text: row.modelData.name; color: Theme.textPrimary }
                                    Caption {
                                        Layout.fillWidth: true
                                        text: row.modelData.section || [row.modelData.kind, row.modelData.size].filter(Boolean).join(" · ")
                                        font: Theme.type.caption
                                    }
                                    Caption {
                                        Layout.fillWidth: true
                                        visible: !!row.modelData.text
                                        text: row.modelData.text || ""
                                        font: Theme.type.caption
                                        wrapMode: Text.Wrap; maximumLineCount: 3
                                    }
                                }
                            }
                        }
                    }
                    ColumnLayout {
                        anchors.centerIn: parent
                        width: parent.width - 40
                        visible: !root.rows.length && !Documents.busy
                        spacing: 8
                        Caption {
                            Layout.fillWidth: true
                            text: Documents.query ? "No passages found" : searchBox.text ? "No matching names" : "No documents here"
                            color: Theme.textPrimary; horizontalAlignment: Text.AlignHCenter
                        }
                        Caption {
                            Layout.fillWidth: true
                            text: Documents.query ? "Try a shorter phrase. Only readable files are searched."
                                : "Try another folder or clear your filter."
                            wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }
                Caption {
                    Layout.fillWidth: true
                    visible: Documents.limited
                    text: "Showing a limited folder listing. Open a subfolder to narrow it down."
                    wrapMode: Text.Wrap; font: Theme.type.caption
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: root.wide || root.hasPreview
                radius: Theme.radius.lg
                color: Theme.surface
                border.color: Theme.separator
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: root.wide ? 24 : 16
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.hasPreview
                        ActionButton {
                            visible: !root.wide && !!Documents.folder
                            text: "Back to files"
                            onClicked: { Documents.clearPreview(); files.forceActiveFocus() }
                        }
                        Caption {
                            Layout.fillWidth: true
                            text: Documents.selected.name || "Text preview"
                            font: Theme.type.headline; color: Theme.textPrimary
                        }
                        IconButton {
                            icon: "copy"; label: "Copy file path"; enabled: !!Documents.selected.path
                            onClicked: { root.notice = Documents.copyPath() || "File path copied"; copiedTimer.restart() }
                        }
                        IconButton { icon: "close"; label: "Close preview"; onClicked: Documents.clearPreview() }
                    }
                    Caption {
                        Layout.fillWidth: true
                        visible: !!Documents.selected.path
                        text: [Documents.selected.kind, Documents.selected.size, Documents.selected.modified].filter(Boolean).join(" · ")
                        font: Theme.type.caption
                    }
                    Caption {
                        Layout.fillWidth: true
                        visible: !!Documents.selected.path
                        text: Documents.selected.path || ""
                        font: Theme.type.caption; elide: Text.ElideMiddle
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.separator; visible: root.hasPreview }
                    C.ScrollView {
                        objectName: "documentPreviewScroll"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: !!Documents.preview
                        clip: true
                        contentWidth: availableWidth
                        C.TextArea {
                            objectName: "documentPreviewText"
                            text: Documents.preview
                            textFormat: TextEdit.PlainText
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                            font: Theme.type.body
                            color: Theme.textPrimary
                            selectionColor: Theme.accentSubtle
                            selectedTextColor: Theme.textPrimary
                            background: null
                            padding: 0
                            Accessible.name: "Document text preview"
                        }
                    }
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: !Documents.preview
                        ColumnLayout {
                            anchors.centerIn: parent
                            width: Math.min(300, parent.width)
                            spacing: 14
                            Icon { Layout.alignment: Qt.AlignHCenter; name: "document"; size: 28; color: Theme.accent }
                            Caption {
                                Layout.fillWidth: true
                                text: Documents.operation === "preview" ? "Opening your document…" : "A little space to read."
                                color: Theme.textPrimary
                                font: Theme.type.headline; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                            }
                            Caption {
                                Layout.fillWidth: true
                                text: "Select a file to preview its text here."
                                horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                            }
                        }
                    }
                    Caption {
                        Layout.fillWidth: true
                        visible: root.hasPreview || !!root.notice
                        text: root.notice || "Text preview · Original formatting isn’t shown"
                        font: Theme.type.caption
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }
}
