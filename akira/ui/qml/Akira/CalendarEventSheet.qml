import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

/*!
    Adding or changing one event in the calendar kept in Akira (`Planner`).

    The person's own act: nothing here asks for a grant or a confirmation,
    except removing, which has no undo and so asks once, in place. What the
    bridge refuses comes back in words and is shown as it is.

    Dates and times are typed as the bridge takes them, 2026-10-02 and 15:00:
    no JavaScript dates, which carry a time zone the calendar does not have.
*/
Sheet {
    id: root
    objectName: "calendarEventSheet"
    sheetWidth: 560

    /*! The event being changed, or "" for a new one. */
    property string eventId: ""
    property string eventTitle: ""
    property bool allDay: false
    property string startDate: ""
    property string startTime: "09:00"
    property string endDate: ""
    property string endTime: "10:00"
    property string repeat: ""
    property string until: ""
    property string remind: "-1"
    property string where: ""
    property string notes: ""
    property string notice: ""
    property bool confirmingRemove: false

    signal saved(string id)
    signal removed()

    title: eventId === "" ? "New event" : "Event"
    subtitle: "Kept in your calendar on this computer."

    function _date(text) { return text.length >= 10 ? text.substring(0, 10) : text; }
    function _time(text) { return text.length > 10 ? text.substring(11, 16) : ""; }

    function _reset() {
        notice = ""; confirmingRemove = false;
        repeat = ""; until = ""; remind = "-1"; where = ""; notes = "";
    }

    /*! A new event on \a day (2026-10-02), at \a time (15:00) or all day for "". */
    function openNew(day, time, title) {
        _reset();
        eventId = "";
        eventTitle = title || "";
        allDay = !time;
        startDate = day; endDate = day;
        startTime = time || "09:00";
        var hour = parseInt(startTime.substring(0, 2), 10);
        endTime = (hour >= 23 ? "23:59" : (hour + 1 < 10 ? "0" : "") + (hour + 1) + startTime.substring(2));
        open();
    }

    /*! A new event from a line read by `Planner.read`: title, start, end, allDay. */
    function openRead(read, fallbackDay) {
        if (!read.start) { openNew(fallbackDay, "", read.title); return; }
        _reset();
        eventId = "";
        eventTitle = read.title;
        allDay = read.allDay;
        startDate = _date(read.start); endDate = _date(read.end || read.start);
        startTime = _time(read.start) || "09:00"; endTime = _time(read.end) || "10:00";
        open();
    }

    /*! The event \a id, as it is. */
    function openEvent(id) {
        var e = Planner.event(id);
        if (!e.id) return;
        _reset();
        eventId = e.id; eventTitle = e.title; allDay = e.allDay;
        startDate = _date(e.start); endDate = _date(e.end);
        startTime = _time(e.start) || "09:00"; endTime = _time(e.end) || "10:00";
        repeat = e.repeat; until = e.until; remind = String(e.remind);
        where = e.where; notes = e.notes;
        open();
    }

    function fields() {
        return {
            title: eventTitle,
            start: allDay ? startDate : startDate + "T" + startTime,
            end: allDay ? endDate : endDate + "T" + endTime,
            repeat: repeat, until: repeat === "" ? "" : until,
            remind: parseInt(remind, 10), where: where, notes: notes
        };
    }

    function save() {
        var why = eventId === "" ? Planner.add(fields()) : Planner.change(eventId, fields());
        notice = why;
        if (why !== "") return why;
        saved(eventId);
        close();
        return "";
    }

    function removeEvent() {
        if (!confirmingRemove) { confirmingRemove = true; return "confirm"; }
        var why = Planner.remove(eventId);
        notice = why;
        confirmingRemove = false;
        if (why !== "") return why;
        removed();
        close();
        return "";
    }

    component Field: Rectangle {
        id: field
        property string text: ""
        property alias placeholder: input.placeholderText
        property alias inputObjectName: input.objectName
        signal edited(string value)
        signal accepted()
        radius: Theme.radius.sm
        color: Theme.inset
        border.width: 1
        border.color: input.activeFocus ? Theme.accent : Theme.separator
        implicitHeight: 32
        C.TextField {
            id: input
            anchors.fill: parent
            anchors.leftMargin: Theme.space.sm
            anchors.rightMargin: Theme.space.sm
            text: field.text
            font: Theme.type.callout
            color: Theme.textPrimary
            placeholderTextColor: Theme.textTertiary
            selectionColor: Theme.accentSubtle
            selectedTextColor: Theme.textPrimary
            selectByMouse: true
            background: null
            padding: 0
            verticalAlignment: TextInput.AlignVCenter
            onTextEdited: field.edited(text)
            onAccepted: field.accepted()
        }
    }

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "What" }
        Field {
            objectName: "eventTitle"
            inputObjectName: "eventTitleInput"
            Layout.fillWidth: true
            text: root.eventTitle
            placeholder: "Such as Dentist, or Lunch with Sam"
            onEdited: function (value) { root.eventTitle = value; }
            onAccepted: root.save()
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space.xs
            spacing: Theme.space.sm
            SectionLabel { text: "When"; Layout.fillWidth: true }
            Text {
                text: "All day"
                font: Theme.type.caption
                color: Theme.textSecondary
            }
            Toggle {
                objectName: "eventAllDay"
                label: "All day"
                checked: root.allDay
                onToggled: function (value) {
                    root.allDay = value;
                    checked = Qt.binding(function () { return root.allDay; });
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 3
            columnSpacing: Theme.space.sm
            rowSpacing: Theme.space.sm

            Text { text: "Starts"; font: Theme.type.callout; color: Theme.textSecondary; Layout.preferredWidth: 56 }
            Field {
                objectName: "eventStartDate"
                Layout.fillWidth: true
                text: root.startDate
                placeholder: "2026-10-02"
                onEdited: function (value) {
                    // Moving the start moves the end with it, when they were the same day.
                    if (root.endDate === root.startDate) root.endDate = value;
                    root.startDate = value;
                }
            }
            Field {
                objectName: "eventStartTime"
                visible: !root.allDay
                Layout.preferredWidth: 90
                text: root.startTime
                placeholder: "15:00"
                onEdited: function (value) { root.startTime = value; }
            }
            Item { visible: root.allDay; Layout.preferredWidth: 90 }

            Text { text: "Ends"; font: Theme.type.callout; color: Theme.textSecondary; Layout.preferredWidth: 56 }
            Field {
                objectName: "eventEndDate"
                Layout.fillWidth: true
                text: root.endDate
                placeholder: root.allDay ? "The last day" : "2026-10-02"
                onEdited: function (value) { root.endDate = value; }
            }
            Field {
                objectName: "eventEndTime"
                visible: !root.allDay
                Layout.preferredWidth: 90
                text: root.endTime
                placeholder: "16:00"
                onEdited: function (value) { root.endTime = value; }
            }
            Item { visible: root.allDay; Layout.preferredWidth: 90 }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space.xs
            spacing: Theme.space.md

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.space.xs
                SectionLabel { text: "Repeats" }
                Select {
                    objectName: "eventRepeat"
                    Layout.fillWidth: true
                    label: "Repeats"
                    options: Planner.repeats.map(function (r) { return { value: r.id, label: r.label }; })
                    current: root.repeat
                    onPicked: function (value) { root.repeat = value; }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.space.xs
                SectionLabel { text: "Reminder" }
                Select {
                    objectName: "eventRemind"
                    Layout.fillWidth: true
                    label: "Reminder"
                    options: Planner.reminders.map(function (r) { return { value: String(r.minutes), label: r.label }; })
                    current: root.remind
                    onPicked: function (value) { root.remind = value; }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: root.repeat !== ""
            spacing: Theme.space.sm
            Text { text: "Until"; font: Theme.type.callout; color: Theme.textSecondary; Layout.preferredWidth: 56 }
            Field {
                objectName: "eventUntil"
                Layout.fillWidth: true
                text: root.until
                placeholder: "The last day it repeats on, or leave empty for no end"
                onEdited: function (value) { root.until = value; }
            }
        }

        Text {
            Layout.fillWidth: true
            visible: root.remind !== "-1" && !Planner.noticesAllowed
            text: "Reminders are shown as notices, which are not allowed yet: this one will wait until they are (Settings, Permissions, Send notifications)."
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textSecondary
            wrapMode: Text.Wrap
        }

        SectionLabel { text: "Where"; Layout.topMargin: Theme.space.xs }
        Field {
            objectName: "eventWhere"
            Layout.fillWidth: true
            text: root.where
            placeholder: "Optional"
            onEdited: function (value) { root.where = value; }
        }

        SectionLabel { text: "Notes"; Layout.topMargin: Theme.space.xs }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 72
            radius: Theme.radius.sm
            color: Theme.inset
            border.width: 1
            border.color: notesInput.activeFocus ? Theme.accent : Theme.separator
            C.ScrollView {
                anchors.fill: parent
                anchors.margins: Theme.space.xs
                C.TextArea {
                    id: notesInput
                    objectName: "eventNotes"
                    text: root.notes
                    textFormat: TextEdit.PlainText
                    font: Theme.type.callout
                    color: Theme.textPrimary
                    placeholderText: "Optional"
                    placeholderTextColor: Theme.textTertiary
                    selectionColor: Theme.accentSubtle
                    selectedTextColor: Theme.textPrimary
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    background: null
                    onTextChanged: if (activeFocus) root.notes = text
                }
            }
        }

        Text {
            objectName: "eventNotice"
            Layout.fillWidth: true
            visible: root.notice !== ""
            text: root.notice
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.danger
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space.sm
            spacing: Theme.space.sm
            ActionButton {
                objectName: "eventRemove"
                visible: root.eventId !== ""
                text: root.confirmingRemove ? "Remove it" : "Remove"
                kind: root.confirmingRemove ? "danger" : "secondary"
                onClicked: root.removeEvent()
            }
            Text {
                Layout.fillWidth: true
                visible: root.confirmingRemove
                text: root.repeat !== "" ? "Every time it repeats is removed." : "There is no undo."
                textFormat: Text.PlainText
                font: Theme.type.caption
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
            Item { Layout.fillWidth: true; visible: !root.confirmingRemove }
            ActionButton { objectName: "eventCancel"; text: "Cancel"; onClicked: root.close() }
            ActionButton {
                objectName: "eventSave"
                text: root.eventId === "" ? "Add" : "Save"
                kind: "primary"
                enabled: root.eventTitle.trim() !== "" && root.startDate !== ""
                onClicked: root.save()
            }
        }
    }
}
