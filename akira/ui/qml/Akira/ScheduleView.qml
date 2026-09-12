import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

/*!
    What runs on its own: every scheduled job, what each did last, and the
    security review's findings.

    Jobs run one at a time, and each run gets only what its job allows *and*
    the person still holds at that moment, so nothing here grants anything.
    The security review can be run now but neither paused nor removed from
    here: it is what notices a permission that should not be there. Removing
    any other job asks twice.

    Findings are shown worst first. When one names a capability, the way to
    act on it is the permission screen, where it can be narrowed or taken
    away; the review never changes anything itself.
*/
Item {
    id: root

    /*! The review's action, which may be run but not paused or removed. */
    readonly property string reviewAction: "security_review"
    readonly property bool reviewing: Schedule.jobs.some(function (j) {
        return j.action === root.reviewAction && j.running;
    })

    property string notice: ""

    signal permissionsRequested()

    function job(id) {
        var jobs = Schedule.jobs;
        for (var i = 0; i < jobs.length; i++)
            if (jobs[i].id === id)
                return jobs[i];
        return null;
    }

    function protectedJob(j) { return j.action === root.reviewAction; }

    function when(at) {
        var d = new Date(at * 1000);
        var today = new Date();
        var tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
        var time = Qt.formatTime(d, "hh:mm");
        if (d.toDateString() === today.toDateString())
            return "today at " + time;
        if (d.toDateString() === tomorrow.toDateString())
            return "tomorrow at " + time;
        return Qt.formatDate(d, "ddd d MMM") + " at " + time;
    }

    readonly property var statusWords: ({
        ok: "done", failed: "failed", skipped: "skipped",
        overlap: "skipped, still running from before", cancelled: "stopped when Akira closed"
    })

    function said(status) { return root.statusWords[status] || status; }

    function next(j) {
        if (j.done)
            return "Finished.";
        if (!j.enabled)
            return j.pausedReason !== "" ? j.pausedReason : "Paused.";
        if (j.running)
            return "Running now.";
        return j.nextRun ? "Next " + root.when(j.nextRun) + "." : "";
    }

    function last(j) {
        if (!j.lastRun)
            return "Has not run yet.";
        return "Last ran " + root.when(j.lastRun) + (j.lastStatus ? ": " + root.said(j.lastStatus) : "") + ".";
    }

    function icon(action) {
        return ({ team: "team", agent: "user", notify: "bell", security_review: "shield",
                  distil_memory: "document" })[action] || "clock";
    }

    function pauseJob(id) {
        var j = root.job(id);
        root.notice = !j ? "That job is not there any more."
                    : root.protectedJob(j) ? "The security review is not paused from here: it is what notices a permission that should not be there."
                    : "";
        if (root.notice === "")
            Schedule.pause(id);
        return root.notice;
    }

    function resumeJob(id) {
        Schedule.resume(id);
        root.notice = "";
        return "";
    }

    function removeJob(id) {
        var j = root.job(id);
        root.notice = !j ? "That job is not there any more."
                    : root.protectedJob(j) ? "The security review cannot be removed. It runs every day so that nothing allowed goes unnoticed."
                    : "";
        if (root.notice === "")
            Schedule.remove(id);
        return root.notice;
    }

    // -- pieces ------------------------------------------------------------------

    component Card: Squircle {
        default property alias content: inner.data
        property int pad: Theme.space.lg
        Layout.fillWidth: true
        implicitHeight: inner.implicitHeight + pad * 2
        radius: Theme.radius.md
        fillColor: Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.94)
        borderColor: Theme.separator
        ColumnLayout {
            id: inner
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: parent.pad
            spacing: Theme.space.md
        }
    }

    // -- the page --------------------------------------------------------------------

    C.ScrollView {
        id: scroller
        anchors.fill: parent
        anchors.topMargin: Theme.space.lg
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: Math.min(820, scroller.availableWidth - Theme.space.xxl * 2)
            x: (scroller.availableWidth - width) / 2
            spacing: Theme.space.lg

            Card {
                RowLayout {
                    Layout.fillWidth: true
                    Icon { name: "calendar"; size: 18; color: Theme.accent }
                    Text {
                        Layout.fillWidth: true
                        text: "Schedule"
                        font: Theme.type.title3
                        color: Theme.textPrimary
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: "What Akira does on its own, one job at a time. A job may use only what it was given and what you still allow when it runs."
                    font: Theme.type.caption
                    color: Theme.textSecondary
                    wrapMode: Text.Wrap
                }
                Text {
                    Layout.fillWidth: true
                    visible: root.notice !== ""
                    text: root.notice
                    textFormat: Text.PlainText
                    font: Theme.type.callout
                    color: Theme.danger
                    wrapMode: Text.Wrap
                }
            }

            // -- the review ------------------------------------------------------------
            Card {
                objectName: "reviewCard"
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space.sm
                    Icon {
                        name: "shield"
                        size: 18
                        color: Schedule.criticalCount > 0 ? Theme.danger : Theme.accent
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text { text: "Security review"; font: Theme.type.headline; color: Theme.textPrimary }
                        Text {
                            Layout.fillWidth: true
                            text: Schedule.reviewSummary
                                  + (Schedule.lastReviewAt ? " · " + root.when(Schedule.lastReviewAt) : "")
                            textFormat: Text.PlainText
                            font: Theme.type.caption
                            color: Schedule.criticalCount > 0 ? Theme.danger : Theme.textSecondary
                        }
                    }
                    ActionButton {
                        text: root.reviewing ? "Reviewing…" : "Review now"
                        enabled: !root.reviewing
                        onClicked: Schedule.runReview()
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: "Every day Akira looks at what it has been allowed and what it has done with it, and says what looks wrong. It never changes anything itself."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                    wrapMode: Text.Wrap
                }
                Text {
                    Layout.fillWidth: true
                    visible: Schedule.lastReviewAt > 0 && Schedule.findings.length === 0
                    text: "Nothing found."
                    font: Theme.type.callout
                    color: Theme.success
                }
                Repeater {
                    model: Schedule.findings
                    RowLayout {
                        id: finding
                        required property var modelData
                        readonly property var f: modelData
                        Layout.fillWidth: true
                        spacing: Theme.space.sm
                        Rectangle {
                            Layout.alignment: Qt.AlignTop
                            Layout.topMargin: 6
                            implicitWidth: 8
                            implicitHeight: 8
                            radius: 4
                            color: finding.f.severity === "critical" ? Theme.danger
                                 : finding.f.severity === "warn" ? Theme.warning : Theme.textTertiary
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text {
                                Layout.fillWidth: true
                                text: finding.f.title
                                textFormat: Text.PlainText
                                font: Theme.type.bodyStrong
                                color: Theme.textPrimary
                                wrapMode: Text.Wrap
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: finding.f.detail !== ""
                                text: finding.f.detail
                                textFormat: Text.PlainText
                                font: Theme.type.caption
                                color: Theme.textSecondary
                                wrapMode: Text.Wrap
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: finding.f.suggestion !== ""
                                text: finding.f.suggestion
                                textFormat: Text.PlainText
                                font: Theme.type.caption
                                color: Theme.textPrimary
                                wrapMode: Text.Wrap
                            }
                        }
                        ActionButton {
                            Layout.alignment: Qt.AlignTop
                            visible: finding.f.capability !== ""
                            text: "Permissions"
                            onClicked: root.permissionsRequested()
                        }
                    }
                }
            }

            // -- the jobs --------------------------------------------------------------
            Card {
                objectName: "jobList"
                SectionLabel { text: "Jobs" }
                Repeater {
                    model: Schedule.warnings
                    Text {
                        required property var modelData
                        Layout.fillWidth: true
                        text: modelData
                        textFormat: Text.PlainText
                        font: Theme.type.callout
                        color: Theme.danger
                        wrapMode: Text.Wrap
                    }
                }
                Text {
                    Layout.fillWidth: true
                    visible: Schedule.jobs.length === 0
                    text: "No jobs yet. Watches, memory and the security review add their own."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                    wrapMode: Text.Wrap
                }
                Repeater {
                    model: Schedule.jobs
                    ColumnLayout {
                        id: row
                        required property var modelData
                        readonly property var j: modelData
                        readonly property bool guarded: root.protectedJob(j)
                        property bool open: false
                        property bool armed: false
                        readonly property var runs: {
                            void Schedule.jobs;
                            return row.open ? Schedule.history(row.j.id).slice(0, 5) : [];
                        }
                        Layout.fillWidth: true
                        spacing: Theme.space.xs

                        Timer { running: row.armed; interval: 4000; onTriggered: row.armed = false }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.space.md
                            Icon {
                                Layout.alignment: Qt.AlignTop
                                name: root.icon(row.j.action)
                                size: 18
                                color: row.j.pausedReason !== "" ? Theme.danger
                                     : row.j.enabled && !row.j.done ? Theme.accent : Theme.textTertiary
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text {
                                    Layout.fillWidth: true
                                    text: row.j.name
                                    textFormat: Text.PlainText
                                    font: Theme.type.bodyStrong
                                    color: Theme.textPrimary
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: row.j.when + (root.next(row.j) !== "" ? " · " + root.next(row.j) : "")
                                    textFormat: Text.PlainText
                                    font: Theme.type.caption
                                    color: row.j.pausedReason !== "" ? Theme.danger : Theme.textSecondary
                                    wrapMode: Text.Wrap
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: root.last(row.j)
                                    textFormat: Text.PlainText
                                    font: Theme.type.caption
                                    color: row.j.lastStatus === "failed" ? Theme.danger : Theme.textTertiary
                                }
                            }
                            ActionButton {
                                text: row.open ? "Hide runs" : "Runs"
                                onClicked: row.open = !row.open
                            }
                            ActionButton {
                                text: "Run now"
                                enabled: !row.j.running && !row.j.done
                                onClicked: Schedule.runNow(row.j.id)
                            }
                            ActionButton {
                                visible: !row.guarded && !row.j.done
                                text: row.j.enabled ? "Pause" : "Resume"
                                onClicked: row.j.enabled ? root.pauseJob(row.j.id) : root.resumeJob(row.j.id)
                            }
                            ActionButton {
                                visible: !row.guarded
                                text: row.armed ? "Remove it" : "Remove"
                                kind: row.armed ? "danger" : "secondary"
                                onClicked: {
                                    if (row.armed)
                                        root.removeJob(row.j.id);
                                    else
                                        row.armed = true;
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            Layout.leftMargin: 18 + Theme.space.md
                            visible: row.open && row.runs.length === 0
                            text: "No runs yet."
                            font: Theme.type.caption
                            color: Theme.textTertiary
                        }
                        Repeater {
                            model: row.runs
                            RowLayout {
                                id: run
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.leftMargin: 18 + Theme.space.md
                                spacing: Theme.space.sm
                                Text {
                                    Layout.alignment: Qt.AlignTop
                                    Layout.preferredWidth: 150
                                    text: root.when(run.modelData.started)
                                    textFormat: Text.PlainText
                                    font: Theme.type.caption
                                    color: Theme.textTertiary
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: root.said(run.modelData.status)
                                          + (run.modelData.trigger === "manual" ? ", by hand"
                                             : run.modelData.trigger === "event" ? ", on an event" : "")
                                          + (run.modelData.late ? ", late" : "")
                                          + (run.modelData.summary ? ": " + run.modelData.summary : "")
                                    textFormat: Text.PlainText
                                    font: Theme.type.caption
                                    color: run.modelData.status === "failed" ? Theme.danger : Theme.textSecondary
                                    wrapMode: Text.Wrap
                                    maximumLineCount: 3
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: Theme.space.xxl }
        }
    }
}
