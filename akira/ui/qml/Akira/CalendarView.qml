import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts
import QtQuick.Window

/*!
    The calendar kept in Akira, on this computer and nowhere else (`Planner`).

    A month or a week, and beside it the day chosen. Everything shown is asked
    for again whenever `Planner.revision` moves, so an event the chat or an
    agent added appears without anything here noticing it.

    What the person does here is their own act and needs no grant. The one
    line under the header says what Akira's chat and agents may not do yet,
    with the way to allow it, and nothing when they may.

    Titles, places and notes are text people wrote, and are shown as plain text.
*/
Item {
    id: root

    signal permissionsRequested()
    signal setupRequested()

    /*! "month" or "week". */
    property string mode: "month"
    property int year: _todayDate().getFullYear()
    property int month: _todayDate().getMonth() + 1
    /*! The day the week is shown around, and the day listed beside. */
    property string focusDay: Planner.today
    property string selectedDay: Planner.today
    property string notice: ""
    /*! The last event added from the quick-add line, for Undo. */
    property string lastAdded: ""

    readonly property bool sundayFirst: Qt.locale().firstDayOfWeek === Locale.Sunday
    readonly property bool wide: width >= 900
    /*! Room for the header on one line: the heading, the ways to move, and adding. */
    readonly property bool roomy: width >= 1160
    readonly property var monthDays: { Planner.revision; return Planner.month(root.year, root.month, root.sundayFirst); }
    readonly property var weekDays: { Planner.revision; return Planner.week(root.focusDay, root.sundayFirst); }
    readonly property var selectedEvents: { Planner.revision; return Planner.day(root.selectedDay); }

    readonly property var _monthNames: ["January", "February", "March", "April", "May", "June", "July",
                                        "August", "September", "October", "November", "December"]

    function _todayDate() { return _parse(Planner.today); }
    // Local midday, so no time zone can move the day.
    function _parse(iso) { return new Date(parseInt(iso.substring(0, 4), 10), parseInt(iso.substring(5, 7), 10) - 1, parseInt(iso.substring(8, 10), 10), 12); }
    function _iso(d) {
        return d.getFullYear() + "-" + (d.getMonth() < 9 ? "0" : "") + (d.getMonth() + 1) + "-"
             + (d.getDate() < 10 ? "0" : "") + d.getDate();
    }
    function _shift(iso, days) { var d = _parse(iso); d.setDate(d.getDate() + days); return _iso(d); }
    function _pad(n) { return (n < 10 ? "0" : "") + n; }

    readonly property string heading: {
        if (mode === "month")
            return _monthNames[month - 1] + " " + year;
        if (!weekDays.length) return "";
        var first = _parse(weekDays[0].date), last = _parse(weekDays[6].date);
        var a = first.getDate() + " " + _monthNames[first.getMonth()].substring(0, 3);
        var b = last.getDate() + " " + _monthNames[last.getMonth()].substring(0, 3) + " " + last.getFullYear();
        return a + " – " + b;
    }

    function previous() {
        if (mode === "month") {
            if (month === 1) { month = 12; year -= 1; } else month -= 1;
        } else {
            focusDay = _shift(focusDay, -7);
        }
    }
    function next() {
        if (mode === "month") {
            if (month === 12) { month = 1; year += 1; } else month += 1;
        } else {
            focusDay = _shift(focusDay, 7);
        }
    }
    function goToday() {
        var d = _todayDate();
        year = d.getFullYear(); month = d.getMonth() + 1;
        focusDay = Planner.today; selectedDay = Planner.today;
    }
    function setMode(id) {
        if (id === mode) return;
        if (id === "week") {
            // The week of the day chosen, if it is in the month shown.
            var chosen = _parse(selectedDay);
            focusDay = (chosen.getFullYear() === year && chosen.getMonth() + 1 === month)
                     ? selectedDay : _iso(new Date(year, month - 1, 1, 12));
        } else {
            var d = _parse(focusDay);
            year = d.getFullYear(); month = d.getMonth() + 1;
        }
        mode = id;
    }
    function selectDay(iso) {
        selectedDay = iso;
        var d = _parse(iso);
        if (mode === "month" && (d.getFullYear() !== year || d.getMonth() + 1 !== month)) {
            year = d.getFullYear(); month = d.getMonth() + 1;
        }
    }
    function newEvent(day, time) { editor.openNew(day || selectedDay, time || ""); }
    function openEvent(id) { editor.openEvent(id); }

    /*! The quick-add line: added at once when it says when, else the editor. */
    function quickAdd(text) {
        var line = text.trim();
        if (line === "") return "";
        var read = Planner.read(line);
        if (!read.start) {
            editor.openRead(read, selectedDay);
            return "editor";
        }
        var why = Planner.add({ title: read.title, start: read.start, end: read.end });
        if (why !== "") { notice = why; lastAdded = ""; return why; }
        notice = "Added: " + read.title + ", " + read.when + ".";
        selectDay(read.start.substring(0, 10));
        if (mode === "week") focusDay = selectedDay;
        quickWide.text = ""; quickNarrow.text = "";
        return "";
    }
    function undoAdd() {
        if (lastAdded !== "") Planner.remove(lastAdded);
        lastAdded = ""; notice = "";
    }
    /*! Dropped on a day, or a day and a time: the event moves there. */
    function moveTo(id, start) {
        var why = Planner.move(id, start);
        notice = why;
        return why;
    }

    Connections {
        target: Planner
        function onAdded(id) { root.lastAdded = id; }
    }

    // -- pieces --------------------------------------------------------------------------

    component Chip: Rectangle {
        id: chip
        property var event: ({})
        property bool compact: true
        signal activated()
        radius: Theme.radius.xs
        color: event.allDay ? Theme.accentSubtle : (hover.hovered ? Theme.surfaceActive : "transparent")
        implicitHeight: 20
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 4
            anchors.rightMargin: 4
            spacing: 4
            Rectangle {
                visible: !chip.event.allDay
                width: 6; height: 6; radius: 3
                color: Theme.accent
            }
            Text {
                Layout.fillWidth: true
                text: (chip.event.time ? chip.event.time + " " : "") + chip.event.title
                textFormat: Text.PlainText
                elide: Text.ElideRight
                font: Theme.type.caption
                color: Theme.textPrimary
            }
        }
        HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
        TapHandler { gesturePolicy: TapHandler.WithinBounds; onTapped: chip.activated() }
    }

    component QuickAdd: Rectangle {
        property alias text: input.text
        implicitHeight: 32
        radius: Theme.radius.sm
        color: Theme.inset
        border.width: 1
        border.color: input.activeFocus ? Theme.accent : Theme.separator
        C.TextField {
            id: input
            objectName: "calendarQuickAdd"
            anchors.fill: parent
            anchors.leftMargin: Theme.space.sm
            anchors.rightMargin: Theme.space.sm
            placeholderText: "Add: Dentist Friday 3pm"
            font: Theme.type.callout
            color: Theme.textPrimary
            placeholderTextColor: Theme.textTertiary
            selectionColor: Theme.accentSubtle
            selectedTextColor: Theme.textPrimary
            selectByMouse: true
            background: null
            padding: 0
            verticalAlignment: TextInput.AlignVCenter
            onAccepted: root.quickAdd(text)
        }
    }

    // What follows the pointer while an event is dragged.
    Rectangle {
        id: ghost
        property string eventId: ""
        property string label: ""
        property bool allDay: false
        z: 100
        visible: eventId !== ""
        width: 160; height: 22
        radius: Theme.radius.xs
        color: Theme.accent
        opacity: 0.9
        Text {
            anchors.fill: parent
            anchors.leftMargin: 6
            verticalAlignment: Text.AlignVCenter
            text: ghost.label
            textFormat: Text.PlainText
            elide: Text.ElideRight
            font: Theme.type.caption
            color: Theme.textOnAccent
        }
    }

    // -- the page ------------------------------------------------------------------------

    ColumnLayout {
        // Nothing here takes a click while the editor is open. Its Save, pressed
        // over a day, was also taken by the day, which the release then chose.
        enabled: !editor.opened
        anchors.fill: parent
        anchors.leftMargin: Theme.space.xl
        anchors.rightMargin: Theme.space.xl
        anchors.topMargin: Theme.space.md
        anchors.bottomMargin: Theme.space.lg
        spacing: Theme.space.md

        // The header: where, which way, and adding.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.sm

            Text {
                textFormat: Text.PlainText
                objectName: "calendarHeading"
                text: root.heading
                font: Theme.type.title2
                color: Theme.textPrimary
                elide: Text.ElideRight
                Layout.fillWidth: !root.roomy
                Layout.maximumWidth: 320
            }
            IconButton {
                objectName: "calendarPrevious"
                icon: "chevronRight"; label: root.mode === "month" ? "Previous month" : "Previous week"
                rotation: 180
                onClicked: root.previous()
            }
            IconButton {
                objectName: "calendarNext"
                icon: "chevronRight"; label: root.mode === "month" ? "Next month" : "Next week"
                onClicked: root.next()
            }
            ActionButton { objectName: "calendarToday"; text: "Today"; onClicked: root.goToday() }
            Item { Layout.fillWidth: true; visible: root.roomy }
            Segmented {
                objectName: "calendarMode"
                Layout.preferredWidth: 160
                Layout.preferredHeight: 30
                options: [{id: "month", label: "Month"}, {id: "week", label: "Week"}]
                current: root.mode
                onSelected: function (id) { root.setMode(id); }
            }
            QuickAdd {
                id: quickWide
                visible: root.roomy
                Layout.preferredWidth: 240
            }
            ActionButton {
                objectName: "calendarNew"
                visible: root.roomy
                text: "New event"; icon: "plus"; kind: "primary"
                onClicked: root.newEvent(root.selectedDay, "")
            }
        }

        // Narrow, adding goes on a line of its own.
        RowLayout {
            Layout.fillWidth: true
            visible: !root.roomy
            spacing: Theme.space.sm
            QuickAdd {
                id: quickNarrow
                Layout.fillWidth: true
            }
            ActionButton {
                objectName: "calendarNew"
                text: "New event"; icon: "plus"; kind: "primary"
                onClicked: root.newEvent(root.selectedDay, "")
            }
        }

        // What Akira may not do yet, and what was just done.
        RowLayout {
            Layout.fillWidth: true
            visible: hint.text !== "" || root.notice !== ""
            spacing: Theme.space.sm
            Text {
                id: hint
                objectName: "calendarHint"
                visible: root.notice === "" && text !== ""
                Layout.fillWidth: true
                Layout.preferredWidth: 100   // wraps, rather than pushing the buttons out
                text: !Planner.agentsRead ? "Akira's chat and agents can't see this calendar yet. Adding from the chat still works."
                    : !Planner.noticesAllowed ? "Reminders will wait until notices are allowed."
                    : ""
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
            ActionButton {
                objectName: "calendarAllow"
                visible: hint.visible
                text: "Allow…"
                onClicked: !Planner.agentsRead ? root.setupRequested() : root.permissionsRequested()
            }
            Text {
                objectName: "calendarNotice"
                visible: root.notice !== ""
                Layout.fillWidth: true
                Layout.preferredWidth: 100   // wraps, rather than pushing the buttons out
                text: root.notice
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: root.notice.indexOf("Added: ") === 0 ? Theme.textSecondary : Theme.danger
                wrapMode: Text.Wrap
            }
            ActionButton {
                objectName: "calendarUndo"
                visible: root.notice.indexOf("Added: ") === 0 && root.lastAdded !== ""
                text: "Undo"
                onClicked: root.undoAdd()
            }
            IconButton {
                visible: root.notice !== ""
                icon: "close"; label: "Dismiss"; size: 24; iconSize: 14
                onClicked: root.notice = ""
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.space.lg

            // -- a month --------------------------------------------------------------
            Item {
                id: monthView
                objectName: "calendarMonth"
                visible: root.mode === "month"
                Layout.fillWidth: true
                Layout.fillHeight: true

                Row {
                    id: weekdayRow
                    width: parent.width
                    height: 22
                    Repeater {
                        model: root.monthDays.slice(0, 7)
                        Text {
                            textFormat: Text.PlainText
                            required property var modelData
                            width: weekdayRow.width / 7
                            text: modelData.weekday
                            horizontalAlignment: Text.AlignHCenter
                            font: Theme.type.captionStrong
                            color: Theme.textSecondary
                        }
                    }
                }

                Grid {
                    id: monthGrid
                    anchors.top: weekdayRow.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    columns: 7
                    readonly property real cellWidth: width / 7
                    readonly property real cellHeight: height / 6

                    function dayAt(scene) {
                        var p = monthGrid.mapFromItem(null, scene.x, scene.y);
                        if (p.x < 0 || p.y < 0 || p.x >= width || p.y >= height) return "";
                        var i = Math.floor(p.y / cellHeight) * 7 + Math.floor(p.x / cellWidth);
                        return i >= 0 && i < root.monthDays.length ? root.monthDays[i].date : "";
                    }

                    Repeater {
                        model: root.monthDays
                        Rectangle {
                            id: cell
                            required property var modelData
                            required property int index
                            objectName: "calendarDay_" + modelData.date
                            width: monthGrid.cellWidth
                            height: monthGrid.cellHeight
                            readonly property bool chosen: modelData.date === root.selectedDay
                            readonly property int room: Math.max(0, Math.floor((height - 30) / 21))
                            // Days outside the month are the shaded ones.
                            color: chosen ? Theme.surfaceActive
                                 : dayHover.hovered ? Theme.surfaceHover
                                 : modelData.inMonth ? "transparent"
                                 : Qt.rgba(Theme.inset.r, Theme.inset.g, Theme.inset.b, 0.7)
                            border.width: 1
                            border.color: Theme.separator

                            HoverHandler { id: dayHover }
                            TapHandler {
                                gesturePolicy: TapHandler.WithinBounds
                                onTapped: root.selectDay(cell.modelData.date)
                                onDoubleTapped: root.newEvent(cell.modelData.date, "")
                            }

                            Rectangle {
                                x: 6; y: 5
                                width: 22; height: 22; radius: 11
                                color: cell.modelData.today ? Theme.accent : "transparent"
                                Text {
                                    textFormat: Text.PlainText
                                    anchors.centerIn: parent
                                    text: cell.modelData.day
                                    font: cell.modelData.today ? Theme.type.captionStrong : Theme.type.caption
                                    color: cell.modelData.today ? Theme.textOnAccent
                                         : cell.modelData.inMonth ? Theme.textPrimary : Theme.textTertiary
                                }
                            }

                            Column {
                                x: 3; y: 29
                                width: cell.width - 6
                                spacing: 1
                                Repeater {
                                    model: cell.modelData.events.length > cell.room
                                           ? cell.modelData.events.slice(0, Math.max(0, cell.room - 1))
                                           : cell.modelData.events
                                    Chip {
                                        id: monthChip
                                        required property var modelData
                                        objectName: "calendarChip_" + modelData.id + "_" + cell.modelData.date
                                        width: parent.width
                                        event: modelData
                                        opacity: ghost.eventId === modelData.id ? 0.4 : 1
                                        onActivated: root.openEvent(modelData.id)
                                        DragHandler {
                                            target: null
                                            onActiveChanged: {
                                                if (active) {
                                                    ghost.eventId = monthChip.modelData.id;
                                                    ghost.label = monthChip.modelData.title;
                                                    ghost.allDay = monthChip.modelData.allDay;
                                                } else {
                                                    var day = monthGrid.dayAt(centroid.scenePosition);
                                                    var id = ghost.eventId;
                                                    ghost.eventId = "";
                                                    if (day !== "" && day !== cell.modelData.date)
                                                        root.moveTo(id, day);
                                                }
                                            }
                                            onCentroidChanged: {
                                                var p = root.mapFromItem(null, centroid.scenePosition.x, centroid.scenePosition.y);
                                                ghost.x = p.x - 20; ghost.y = p.y - 11;
                                            }
                                        }
                                    }
                                }
                                Text {
                                    textFormat: Text.PlainText
                                    visible: cell.modelData.events.length > cell.room
                                    text: "+" + (cell.modelData.events.length - Math.max(0, cell.room - 1)) + " more"
                                    font: Theme.type.caption
                                    color: Theme.textSecondary
                                    leftPadding: 4
                                }
                            }
                        }
                    }
                }
            }

            // -- a week ---------------------------------------------------------------
            Item {
                id: weekView
                objectName: "calendarWeek"
                visible: root.mode === "week"
                Layout.fillWidth: true
                Layout.fillHeight: true

                readonly property int gutter: 48
                readonly property real hourHeight: 44
                readonly property real columnWidth: (width - gutter) / 7
                readonly property int allDayRows: {
                    var most = 0;
                    for (var i = 0; i < root.weekDays.length; i++) {
                        var n = root.weekDays[i].events.filter(function (e) { return e.allDay; }).length;
                        most = Math.max(most, n);
                    }
                    return Math.min(4, most);
                }

                /*! Timed events of a day, each with its lane and how many lanes it shares. */
                function laid(events) {
                    var timed = events.filter(function (e) { return !e.allDay; })
                                      .sort(function (a, b) { return a.startMinute - b.startMinute; });
                    var lanes = [], placed = [];
                    var cluster = [], clusterEnd = -1;
                    function close() {
                        var width = 0;
                        cluster.forEach(function (p) { width = Math.max(width, p.lane + 1); });
                        cluster.forEach(function (p) { p.lanes = width; });
                        cluster = []; lanes = [];
                    }
                    timed.forEach(function (e) {
                        if (e.startMinute >= clusterEnd && cluster.length) close();
                        var lane = 0;
                        while (lane < lanes.length && lanes[lane] > e.startMinute) lane++;
                        lanes[lane] = Math.max(e.endMinute, e.startMinute + 20);
                        var p = { event: e, lane: lane, lanes: 1 };
                        placed.push(p); cluster.push(p);
                        clusterEnd = Math.max(clusterEnd, lanes[lane]);
                    });
                    if (cluster.length) close();
                    return placed;
                }

                function slotAt(scene) {
                    var p = hours.contentItem.mapFromItem(null, scene.x, scene.y);
                    var column = Math.floor((p.x - gutter) / columnWidth);
                    if (column < 0 || column > 6 || p.y < 0 || p.y > hourHeight * 24) return "";
                    var minutes = Math.max(0, Math.min(23 * 60 + 45, Math.round(p.y / hourHeight * 4) * 15));
                    return root.weekDays[column].date + "T" + root._pad(Math.floor(minutes / 60)) + ":" + root._pad(minutes % 60);
                }
                function dayAt(scene) {
                    var p = weekView.mapFromItem(null, scene.x, scene.y);
                    var column = Math.floor((p.x - gutter) / columnWidth);
                    return column >= 0 && column <= 6 && p.y >= 0 && p.y < weekView.height
                           ? root.weekDays[column].date : "";
                }

                // The days, across the top.
                Row {
                    id: weekHeader
                    x: weekView.gutter
                    width: parent.width - weekView.gutter
                    height: 40
                    Repeater {
                        model: root.weekDays
                        Item {
                            required property var modelData
                            width: weekView.columnWidth
                            height: weekHeader.height
                            Column {
                                anchors.centerIn: parent
                                Text {
                                    textFormat: Text.PlainText
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: modelData.weekday
                                    font: Theme.type.caption
                                    color: modelData.today ? Theme.accent : Theme.textSecondary
                                }
                                Text {
                                    textFormat: Text.PlainText
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: modelData.day
                                    font: Theme.type.headline
                                    color: modelData.today ? Theme.accent : Theme.textPrimary
                                }
                            }
                            TapHandler { onTapped: root.selectDay(modelData.date) }
                        }
                    }
                }

                // All-day events, in a strip under the days.
                Row {
                    id: allDayStrip
                    anchors.top: weekHeader.bottom
                    x: weekView.gutter
                    width: parent.width - weekView.gutter
                    height: Math.max(1, weekView.allDayRows) * 22 + 6
                    Repeater {
                        model: root.weekDays
                        Rectangle {
                            id: allDayCell
                            required property var modelData
                            width: weekView.columnWidth
                            height: allDayStrip.height
                            color: modelData.date === root.selectedDay ? Theme.surfaceActive : "transparent"
                            border.width: 1
                            border.color: Theme.separator
                            Column {
                                x: 2; y: 3
                                width: parent.width - 4
                                spacing: 2
                                Repeater {
                                    model: allDayCell.modelData.events.filter(function (e) { return e.allDay; }).slice(0, 4)
                                    Chip {
                                        required property var modelData
                                        objectName: "calendarChip_" + modelData.id + "_" + allDayCell.modelData.date
                                        width: parent.width
                                        event: modelData
                                        onActivated: root.openEvent(modelData.id)
                                    }
                                }
                            }
                            TapHandler {
                                gesturePolicy: TapHandler.WithinBounds
                                onDoubleTapped: root.newEvent(allDayCell.modelData.date, "")
                            }
                        }
                    }
                }
                Text {
                    anchors.verticalCenter: allDayStrip.verticalCenter
                    width: weekView.gutter - 6
                    horizontalAlignment: Text.AlignRight
                    text: "all day"
                    font: Theme.type.caption
                    color: Theme.textTertiary
                }

                // The hours.
                Flickable {
                    id: hours
                    objectName: "calendarHours"
                    anchors.top: allDayStrip.bottom
                    anchors.topMargin: 4
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    contentHeight: weekView.hourHeight * 24
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    C.ScrollBar.vertical: C.ScrollBar {}
                    Component.onCompleted: contentY = weekView.hourHeight * 7

                    Repeater {
                        model: 24
                        Item {
                            required property int index
                            y: index * weekView.hourHeight
                            width: hours.width
                            height: weekView.hourHeight
                            Text {
                                textFormat: Text.PlainText
                                width: weekView.gutter - 8
                                y: -7
                                visible: index > 0
                                horizontalAlignment: Text.AlignRight
                                text: root._pad(index) + ":00"
                                font: Theme.type.caption
                                color: Theme.textTertiary
                            }
                            Rectangle {
                                x: weekView.gutter
                                width: parent.width - weekView.gutter
                                height: 1
                                color: Theme.separator
                            }
                        }
                    }

                    Repeater {
                        model: root.weekDays
                        Item {
                            id: dayColumn
                            required property var modelData
                            required property int index
                            x: weekView.gutter + index * weekView.columnWidth
                            width: weekView.columnWidth
                            height: hours.contentHeight

                            Rectangle {
                                anchors.fill: parent
                                color: dayColumn.modelData.today ? Theme.accentSubtle : "transparent"
                                opacity: 0.35
                                border.width: 0
                            }
                            Rectangle { width: 1; height: parent.height; color: Theme.separator }

                            TapHandler {
                                gesturePolicy: TapHandler.WithinBounds
                                onDoubleTapped: function (point) {
                                    var hour = Math.max(0, Math.min(23, Math.floor(point.position.y / weekView.hourHeight)));
                                    root.newEvent(dayColumn.modelData.date, root._pad(hour) + ":00");
                                }
                                onTapped: root.selectDay(dayColumn.modelData.date)
                            }

                            Repeater {
                                model: weekView.laid(dayColumn.modelData.events)
                                Rectangle {
                                    id: block
                                    required property var modelData
                                    readonly property var e: modelData.event
                                    objectName: "calendarBlock_" + e.id + "_" + dayColumn.modelData.date
                                    x: 2 + (dayColumn.width - 4) * modelData.lane / modelData.lanes
                                    width: (dayColumn.width - 4) / modelData.lanes - 2
                                    y: e.startMinute / 60 * weekView.hourHeight
                                    height: Math.max(20, (e.endMinute - e.startMinute) / 60 * weekView.hourHeight - 2)
                                    radius: Theme.radius.xs
                                    color: blockHover.hovered ? Theme.surfaceActive : Theme.surface
                                    border.width: 1
                                    border.color: Theme.accent
                                    opacity: ghost.eventId === e.id ? 0.4 : 1
                                    Rectangle { width: 3; height: parent.height; radius: 1; color: Theme.accent }
                                    Column {
                                        x: 7; y: 2
                                        width: parent.width - 10
                                        Text {
                                            width: parent.width
                                            text: block.e.title
                                            textFormat: Text.PlainText
                                            elide: Text.ElideRight
                                            font: Theme.type.captionStrong
                                            color: Theme.textPrimary
                                        }
                                        Text {
                                            width: parent.width
                                            visible: block.height > 34
                                            text: (block.e.time || "…") + "–" + block.e.endTime + (block.e.where ? ", " + block.e.where : "")
                                            textFormat: Text.PlainText
                                            elide: Text.ElideRight
                                            font: Theme.type.caption
                                            color: Theme.textSecondary
                                        }
                                    }
                                    HoverHandler { id: blockHover; cursorShape: Qt.PointingHandCursor }
                                    TapHandler { gesturePolicy: TapHandler.WithinBounds; onTapped: root.openEvent(block.e.id) }
                                    DragHandler {
                                        target: null
                                        onActiveChanged: {
                                            if (active) {
                                                ghost.eventId = block.e.id;
                                                ghost.label = block.e.title;
                                                ghost.allDay = false;
                                            } else {
                                                var slot = weekView.slotAt(centroid.scenePosition);
                                                var id = ghost.eventId;
                                                ghost.eventId = "";
                                                if (slot !== "" && slot !== block.e.start)
                                                    root.moveTo(id, slot);
                                            }
                                        }
                                        onCentroidChanged: {
                                            var p = root.mapFromItem(null, centroid.scenePosition.x, centroid.scenePosition.y);
                                            ghost.x = p.x - 20; ghost.y = p.y - 11;
                                        }
                                    }
                                }
                            }

                            // Now, as a line across today.
                            Rectangle {
                                visible: dayColumn.modelData.today
                                width: parent.width
                                height: 2
                                color: Theme.danger
                                y: nowTimer.minutes / 60 * weekView.hourHeight
                            }
                        }
                    }
                }

                Timer {
                    id: nowTimer
                    property int minutes: new Date().getHours() * 60 + new Date().getMinutes()
                    interval: 60000; repeat: true; running: weekView.visible
                    onTriggered: minutes = new Date().getHours() * 60 + new Date().getMinutes()
                }
            }

            // -- the day chosen -------------------------------------------------------
            Squircle {
                objectName: "calendarDayPanel"
                visible: root.wide
                Layout.preferredWidth: 280
                Layout.fillHeight: true
                radius: Theme.radius.md
                fillColor: Theme.surface
                borderColor: Theme.separator

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.space.lg
                    spacing: Theme.space.sm

                    Text {
                        textFormat: Text.PlainText
                        objectName: "calendarDayLabel"
                        Layout.fillWidth: true
                        text: {
                            var d = root._parse(root.selectedDay);
                            var names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
                            return (root.selectedDay === Planner.today ? "Today, " : "") + names[d.getDay()] + " "
                                 + d.getDate() + " " + root._monthNames[d.getMonth()];
                        }
                        font: Theme.type.headline
                        color: Theme.textPrimary
                        wrapMode: Text.Wrap
                    }

                    Text {
                        visible: root.selectedEvents.length === 0
                        Layout.fillWidth: true
                        text: "Nothing on this day."
                        font: Theme.type.callout
                        color: Theme.textSecondary
                    }

                    C.ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        contentWidth: availableWidth
                        clip: true
                        Column {
                            width: parent.width
                            spacing: Theme.space.sm
                            Repeater {
                                model: root.selectedEvents
                                Rectangle {
                                    id: row
                                    required property var modelData
                                    objectName: "calendarListed_" + modelData.id
                                    width: parent.width
                                    height: listed.implicitHeight + Theme.space.sm * 2
                                    radius: Theme.radius.sm
                                    color: rowHover.hovered ? Theme.surfaceHover : "transparent"
                                    ColumnLayout {
                                        id: listed
                                        x: Theme.space.sm; y: Theme.space.sm
                                        width: parent.width - Theme.space.sm * 2
                                        spacing: 2
                                        Text {
                                            textFormat: Text.PlainText
                                            text: row.modelData.allDay ? "All day"
                                                : (row.modelData.first ? row.modelData.time : "…") + " – " + (row.modelData.last ? row.modelData.endTime : "…")
                                            font: Theme.type.caption
                                            color: Theme.textSecondary
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: row.modelData.title
                                            textFormat: Text.PlainText
                                            font: Theme.type.bodyStrong
                                            color: Theme.textPrimary
                                            wrapMode: Text.Wrap
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            visible: row.modelData.where !== "" || row.modelData.repeats
                                            text: [row.modelData.where, row.modelData.repeatWords].filter(function (s) { return s; }).join(" · ")
                                            textFormat: Text.PlainText
                                            font: Theme.type.caption
                                            color: Theme.textSecondary
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                    HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                                    TapHandler { onTapped: root.openEvent(row.modelData.id) }
                                }
                            }
                        }
                    }

                    ActionButton {
                        objectName: "calendarAddToDay"
                        Layout.fillWidth: true
                        text: "Add to this day"
                        icon: "plus"
                        onClicked: root.newEvent(root.selectedDay, "")
                    }
                }
            }
        }
    }

    CalendarEventSheet {
        id: editor
        // Over the whole window, as every other sheet is.
        parent: root.Window.window ? root.Window.window.contentItem : root
        z: 12
        onSaved: root.notice = ""
    }
}
