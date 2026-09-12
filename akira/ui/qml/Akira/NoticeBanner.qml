import QtQuick
import QtQuick.Layouts

/*!
    What must reach the person, put on screen as it arrives.

    Two things must not sit waiting in a list: a notice a watch's job puts up
    (\c Monitor.noticed), and a critical finding from the security review
    (\c Schedule.criticalFound). A notice leaves by itself after a while, and
    stays in the Watching view; a critical finding stays until it is dismissed.
    Hovering holds a notice where it is.

    The text is plain (rule 5): a notice can quote a web page or a feed.
*/
Item {
    id: root

    /*! How long a notice stays, in milliseconds. A critical finding stays. */
    property int lingerMs: 10000

    readonly property int count: shown.count
    property int criticalCount: 0

    signal reviewRequested()
    signal noticesRequested()

    implicitWidth: 360
    implicitHeight: stack.implicitHeight

    ListModel { id: shown }

    /*! Put something on screen, newest at the top; at most four at once. */
    function show(heading, body, critical) {
        shown.insert(0, { heading: String(heading), body: String(body), critical: critical === true });
        while (shown.count > 4)
            shown.remove(shown.count - 1);
        root.recount();
    }

    function dismiss(index) {
        if (index >= 0 && index < shown.count)
            shown.remove(index);
        root.recount();
    }

    function recount() {
        var n = 0;
        for (var i = 0; i < shown.count; i++)
            if (shown.get(i).critical)
                n++;
        root.criticalCount = n;
    }

    Column {
        id: stack
        width: parent.width
        spacing: Theme.space.sm

        Repeater {
            model: shown

            Squircle {
                id: banner
                required property int index
                required property string heading
                required property string body
                required property bool critical

                width: stack.width
                height: content.implicitHeight + Theme.space.md * 2
                radius: Theme.radius.md
                fillColor: Theme.surface
                borderColor: critical ? Theme.danger : Theme.separatorStrong

                Accessible.role: Accessible.AlertMessage
                Accessible.name: heading

                HoverHandler { id: hover }

                Timer {
                    running: !banner.critical && !hover.hovered
                    interval: root.lingerMs
                    onTriggered: root.dismiss(banner.index)
                }

                RowLayout {
                    id: content
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: Theme.space.md
                    spacing: Theme.space.sm

                    Icon {
                        Layout.alignment: Qt.AlignTop
                        name: banner.critical ? "shield" : "bell"
                        size: 18
                        color: banner.critical ? Theme.danger : Theme.accent
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            Layout.fillWidth: true
                            text: banner.heading
                            textFormat: Text.PlainText
                            font: Theme.type.bodyStrong
                            color: Theme.textPrimary
                            wrapMode: Text.Wrap
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: banner.body !== ""
                            text: banner.body
                            textFormat: Text.PlainText
                            font: Theme.type.caption
                            color: Theme.textSecondary
                            wrapMode: Text.Wrap
                            maximumLineCount: 5
                            elide: Text.ElideRight
                        }
                        ActionButton {
                            Layout.topMargin: Theme.space.xs
                            text: banner.critical ? "Review permissions" : "See all notices"
                            onClicked: {
                                if (banner.critical)
                                    root.reviewRequested();
                                else
                                    root.noticesRequested();
                                root.dismiss(banner.index);
                            }
                        }
                    }

                    IconButton {
                        Layout.alignment: Qt.AlignTop
                        icon: "close"
                        iconSize: 14
                        onClicked: root.dismiss(banner.index)
                    }
                }
            }
        }
    }
}
