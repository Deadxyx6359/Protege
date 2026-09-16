import QtQuick
import QtQuick.Controls as C
import QtQuick.Window

/*!
    A modal panel over the window.

    \qml
    Sheet {
        id: settings
        title: "Settings"
        SettingsPanel { }
    }
    \endqml

    Enters by scaling up slightly and settling, rather than fading in place.
    The movement is what tells you something arrived *on top of* the window
    instead of replacing it — a cross-fade at the same size reads as navigation,
    and navigation implies a back button this has no need for.
*/
Item {
    id: root

    property string title: ""
    property string subtitle: ""

    property int sheetWidth: 640
    property int sheetMaxHeight: Math.round(parent ? parent.height * 0.82 : 600)

    readonly property bool opened: _open

    default property alias content: body.data

    property bool _open: false
    property var returnFocus: null
    readonly property bool ownsFocus: containsFocus(root.Window.window ? root.Window.window.activeFocusItem : null)

    function containsFocus(item) {
        while (item) {
            if (item === panel) return true;
            item = item.parent;
        }
        return false;
    }

    function moveFocus(forward) {
        var item = root.Window.window.activeFocusItem || closeControl;
        const start = item;
        for (var i = 0; i < 1000; i++) {
            item = item.nextItemInFocusChain(forward);
            if (!item || item === start) break;
            if (root.containsFocus(item) && item.visible && item.enabled && item.activeFocusOnTab) {
                item.forceActiveFocus();
                return;
            }
        }
        closeControl.forceActiveFocus();
    }

    anchors.fill: parent
    visible: opacity > 0
    opacity: _open ? 1 : 0
    // Nothing behind a closed sheet should be unclickable.
    enabled: _open

    Behavior on opacity {
        NumberAnimation { duration: Theme.duration.fast }
    }

    function open() {
        if (!root._open) root.returnFocus = root.Window.window ? root.Window.window.activeFocusItem : null;
        root._open = true;
        closeControl.forceActiveFocus();
    }
    function close() {
        root._open = false;
        const target = root.returnFocus;
        root.returnFocus = null;
        if (target && target.visible && target.enabled) target.forceActiveFocus();
    }

    Shortcut { sequence: "Tab"; enabled: root._open && root.ownsFocus; onActivated: root.moveFocus(true) }
    Shortcut { sequence: "Shift+Tab"; enabled: root._open && root.ownsFocus; onActivated: root.moveFocus(false) }

    // -- scrim --------------------------------------------------------------

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim

        /*  Swallows every click that misses the panel, both to dismiss and to
            stop presses landing on the window underneath.

            A MouseArea rather than a TapHandler: a handler here takes a passive
            grab, which a press on a control inside the panel never takes away,
            so every tap on a segmented control or a button in a sheet dismissed
            the sheet as well as doing its own work. Only one item accepts a
            press, and the panel's own area, below, is above this one.  */
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: root.close()
        }
        WheelHandler {}
    }

    // -- panel --------------------------------------------------------------

    FocusScope {
        id: panel
        anchors.centerIn: parent
        width: Math.min(root.sheetWidth, root.width - Theme.space.xxl * 2)
        // Both of the content's margins, top and bottom: counting one left
        // every sheet short by the other and cut off its last row.
        height: Math.min(root.sheetMaxHeight,
                         header.height + Theme.space.lg + body.implicitHeight + Theme.space.xl)

        scale: root._open ? 1.0 : 0.96
        y: root._open ? 0 : Theme.space.lg

        Behavior on scale {
            NumberAnimation {
                duration: Theme.duration.normal
                easing.type: Easing.Bezier
                easing.bezierCurve: Theme.easing.enter
            }
        }

        Keys.onEscapePressed: root.close()

        Squircle {
            anchors.fill: parent
            radius: Theme.radius.lg
            fillColor: Theme.overlay
            borderColor: Theme.separatorStrong
        }

        // Presses inside the panel must not reach the scrim behind it. It sits
        // under the header and the content, so a control still gets its own.
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
        }

        // -- header ---------------------------------------------------------

        Item {
            id: header
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: root.subtitle === "" ? 56 : 68

            Column {
                anchors.left: parent.left
                anchors.leftMargin: Theme.space.xl
                anchors.right: closeControl.left
                anchors.rightMargin: Theme.space.md
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2

                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: root.title
                    textFormat: Text.PlainText
                    font: Theme.type.title3
                    color: Theme.textPrimary
                }
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    visible: root.subtitle !== ""
                    text: root.subtitle
                    textFormat: Text.PlainText
                    font: Theme.type.caption
                    color: Theme.textTertiary
                }
            }

            IconButton {
                id: closeControl
                objectName: "sheetClose"
                anchors.right: parent.right
                anchors.rightMargin: Theme.space.md
                anchors.verticalCenter: parent.verticalCenter
                icon: "close"
                label: "Close " + root.title
                iconSize: 16
                onClicked: root.close()
            }

            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: 1
                color: Theme.separator
            }
        }

        // -- content ----------------------------------------------------------

        C.ScrollView {
            anchors.top: header.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: Theme.space.xl
            anchors.topMargin: Theme.space.lg
            contentWidth: availableWidth
            clip: true

            Column {
                id: body
                width: parent.width
                spacing: Theme.space.xl
            }
        }
    }
}
