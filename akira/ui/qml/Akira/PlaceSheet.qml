import QtQuick
import QtQuick.Controls as C
import QtQuick.Layouts

/*!
    Where you are, and the weather there.

    The place turns the scenes' seasons the right way round and tells agents
    where they are; with a position it also gets the weather. Setting it grants
    nothing. The weather needs two permissions, offered here beside what they
    are for and taken only when the person presses the button: knowing where
    you are (\c location.read) and fetching from the weather's site
    (\c net.http for \c Place.weatherSite). What is sent is said plainly.

    The grants are always read fresh when changed, never from a cached copy, so
    allowing the weather's site never drops a site allowed since.
*/
Sheet {
    id: root

    title: "Where you are"
    subtitle: "For the seasons, the time zone and the weather"
    sheetWidth: 640

    property int revision: 0
    property string notice: ""

    Connections {
        target: Permissions
        function onGrantsChanged() { root.revision += 1 }
    }

    readonly property bool located: {
        void root.revision;
        return Permissions.describe("location.read").granted === true;
    }
    readonly property bool siteAllowed: {
        void root.revision;
        return (Permissions.describe("net.http").scopes || []).indexOf(Place.weatherSite) >= 0;
    }

    /*! Allow or take away knowing where the person is. Returns "" or why not. */
    function setLocated(on) {
        var why = "";
        if (on)
            why = Permissions.grant("location.read", []);
        else
            Permissions.revoke("location.read");
        root.notice = why;
        return why;
    }

    /*! Add the weather's site to the sites allowed, keeping every other one. */
    function allowSite() {
        var now = Permissions.describe("net.http");
        var held = now.granted ? now.scopes : [];
        if (held.indexOf(Place.weatherSite) >= 0)
            return "";
        root.notice = Permissions.grant("net.http", held.concat([Place.weatherSite]));
        return root.notice;
    }

    /*! Take the weather's site away, keeping every other one. */
    function removeSite() {
        var now = Permissions.describe("net.http");
        var rest = (now.scopes || []).filter(function (s) { return s !== Place.weatherSite; });
        if (rest.length === 0) {
            Permissions.revoke("net.http");
            root.notice = "";
        } else {
            root.notice = Permissions.grant("net.http", rest);
        }
        return root.notice;
    }

    function when(at) { return Qt.formatTime(new Date(at * 1000), "hh:mm"); }

    component Field: Rectangle {
        id: field
        property alias text: input.text
        property alias placeholder: input.placeholderText
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
            font: Theme.type.callout
            color: Theme.textPrimary
            placeholderTextColor: Theme.textTertiary
            selectionColor: Theme.accentSubtle
            selectedTextColor: Theme.textPrimary
            selectByMouse: true
            background: null
            padding: 0
            verticalAlignment: TextInput.AlignVCenter
            onAccepted: field.accepted()
        }
    }

    // -- the place ---------------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "Place" }

        Text {
            objectName: "placeName"
            Layout.fillWidth: true
            text: Place.name !== "" ? Place.name : "Not set"
            textFormat: Text.PlainText
            font: Theme.type.bodyStrong
            color: Place.name !== "" ? Theme.textPrimary : Theme.textTertiary
        }
        Text {
            Layout.fillWidth: true
            visible: Place.hemisphere !== ""
            text: (Place.hasPosition ? Place.latitude.toFixed(2) + ", " + Place.longitude.toFixed(2) + " · " : "")
                  + "the " + Place.hemisphere + "ern hemisphere, where it is " + Place.season + "."
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textSecondary
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.sm
            Field {
                id: lookup
                objectName: "placeLookup"
                Layout.fillWidth: true
                placeholder: "A town or city, such as Bristol"
                onAccepted: find.clicked()
            }
            ActionButton {
                id: find
                text: Place.lookingUp ? "Looking…" : "Find"
                enabled: !Place.lookingUp && lookup.text.trim() !== ""
                onClicked: root.notice = Place.findPlace(lookup.text)
            }
        }

        Text {
            Layout.fillWidth: true
            visible: Place.lookupNote !== ""
            text: Place.lookupNote
            textFormat: Text.PlainText
            font: Theme.type.callout
            color: Theme.danger
            wrapMode: Text.Wrap
        }

        Repeater {
            model: Place.candidates
            RowLayout {
                id: found
                required property var modelData
                required property int index
                Layout.fillWidth: true
                spacing: Theme.space.sm
                Text {
                    Layout.fillWidth: true
                    text: found.modelData.label
                    textFormat: Text.PlainText
                    font: Theme.type.callout
                    color: Theme.textPrimary
                    elide: Text.ElideRight
                }
                ActionButton {
                    text: "Use this"
                    onClicked: {
                        root.notice = Place.choosePlace(found.index);
                        if (root.notice === "")
                            lookup.text = "";
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: "Looking a place up sends its name to " + Place.weatherSite
                  + ", and needs fetching from that site allowed below."
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textTertiary
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ActionButton {
                visible: Place.name !== "" || Place.hasPosition
                text: "Forget this place"
                onClicked: Place.clearPlace()
            }
        }
    }

    // -- the weather ---------------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "Weather" }

        Text {
            objectName: "weatherLine"
            Layout.fillWidth: true
            text: Place.weatherSummary !== ""
                  ? Place.weatherSummary + " · read at " + root.when(Place.weatherAt)
                  : (Place.weatherNote !== "" ? Place.weatherNote : "No reading yet.")
            textFormat: Text.PlainText
            font: Theme.type.body
            color: Place.weatherSummary !== "" ? Theme.textPrimary : Theme.textSecondary
            wrapMode: Text.Wrap
        }

        Text {
            Layout.fillWidth: true
            text: "While both are allowed, your position, to about 11 km, is sent to "
                  + Place.weatherSite + " every half hour. Nothing else is."
            textFormat: Text.PlainText
            font: Theme.type.caption
            color: Theme.textTertiary
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.md
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Text { text: "Know where you are"; font: Theme.type.body; color: Theme.textPrimary }
                Text {
                    Layout.fillWidth: true
                    text: "Agents are told the place, time zone and weather."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                    wrapMode: Text.Wrap
                }
            }
            Toggle {
                objectName: "allowLocation"
                checked: root.located
                onToggled: function (value) {
                    root.setLocated(value);
                    // The switch sets itself when tapped; bind it back to what is true.
                    checked = Qt.binding(function () { return root.located; });
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.md
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Text {
                    text: "Fetch from " + Place.weatherSite
                    textFormat: Text.PlainText
                    font: Theme.type.body
                    color: Theme.textPrimary
                }
                Text {
                    Layout.fillWidth: true
                    text: "The forecast and the place lookup both come from here."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                    wrapMode: Text.Wrap
                }
            }
            ActionButton {
                objectName: "allowWeatherSite"
                text: root.siteAllowed ? "Remove" : "Allow"
                kind: root.siteAllowed ? "secondary" : "primary"
                onClicked: root.siteAllowed ? root.removeSite() : root.allowSite()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                visible: root.notice !== ""
                text: root.notice
                textFormat: Text.PlainText
                font: Theme.type.callout
                color: Theme.danger
                wrapMode: Text.Wrap
            }
            Item { Layout.fillWidth: root.notice === "" }
            ActionButton {
                text: "Read it now"
                enabled: Place.hasPosition && root.located && root.siteAllowed
                onClicked: root.notice = Place.refreshWeather()
            }
        }
    }
}
