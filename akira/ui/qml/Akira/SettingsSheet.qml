import QtQuick
import QtQuick.Layouts

/*!
    Settings.

    Two sections, because there are currently two things worth deciding: how it
    looks, and what runs. Everything else the application does is either not a
    choice or belongs where it is used.
*/
Sheet {
    id: root

    title: "Settings"
    subtitle: "Permissions, appearance and models"
    sheetWidth: 680

    /*! The person wants to review what Akira may do. */
    signal permissionsRequested()

    // -- permissions --------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "Permissions" }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.md

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Text {
                    text: "What Akira may do"
                    font: Theme.type.body
                    color: Theme.textPrimary
                }
                Text {
                    Layout.fillWidth: true
                    text: "Nothing is allowed until you allow it: folders, sites, accounts, and a record of what was done with them."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                    wrapMode: Text.Wrap
                }
            }

            ActionButton {
                objectName: "reviewPermissions"
                text: "Review"
                onClicked: root.permissionsRequested()
            }
        }
    }

    // -- appearance ---------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md

        SectionLabel { text: "Appearance" }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.md

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Text {
                    text: "Theme"
                    font: Theme.type.body
                    color: Theme.textPrimary
                }
                Text {
                    text: "Auto follows Windows."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                }
            }

            Segmented {
                Layout.preferredWidth: 210
                current: ThemeBridge.mode
                options: [
                    { id: "auto", label: "Auto" },
                    { id: "light", label: "Light" },
                    { id: "dark", label: "Dark" }
                ]
                onSelected: function (id) { ThemeBridge.mode = id }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space.md

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Text {
                    text: "Reduce motion"
                    font: Theme.type.body
                    color: Theme.textPrimary
                }
                Text {
                    text: "Transitions still happen, but instantly."
                    font: Theme.type.caption
                    color: Theme.textTertiary
                }
            }

            Toggle {
                checked: ThemeBridge.reduceMotion
                onToggled: function (value) { ThemeBridge.reduceMotion = value }
            }
        }
    }

    // -- models -------------------------------------------------------------

    ColumnLayout {
        width: parent.width
        spacing: Theme.space.md

        RowLayout {
            Layout.fillWidth: true
            SectionLabel { Layout.fillWidth: true; text: "Models" }
            IconButton {
                icon: "refresh"
                size: 24
                iconSize: 14
                flat: true
                onClicked: Settings.refresh()
            }
        }

        Repeater {
            model: Settings.routes

            RowLayout {
                id: routeRow
                required property var modelData

                Layout.fillWidth: true
                spacing: Theme.space.md

                ColumnLayout {
                    Layout.fillWidth: true
                    // Without a minimum the blurb's implicit width wins the
                    // layout negotiation and shoves the dropdown off the right
                    // edge — which is why these rows were ragged.
                    Layout.minimumWidth: 120
                    spacing: 1

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space.sm

                        Text {
                            text: routeRow.modelData.label
                            textFormat: Text.PlainText
                            font: Theme.type.body
                            color: Theme.textPrimary
                        }

                        // Only shown while a model is actually resident, so
                        // the dot always means "in memory right now".
                        Rectangle {
                            visible: routeRow.modelData.loaded
                            width: 6; height: 6; radius: 3
                            color: Theme.success
                        }

                        Item { Layout.fillWidth: true }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: routeRow.modelData.blurb
                        textFormat: Text.PlainText
                        font: Theme.type.caption
                        color: Theme.textTertiary
                        elide: Text.ElideRight
                    }
                }

                Select {
                    Layout.preferredWidth: 320
                    Layout.alignment: Qt.AlignVCenter
                    current: routeRow.modelData.path
                    placeholder: "Not set"
                    options: Settings.availableModels.map(function (m) {
                        return { value: m.path, label: m.name, detail: m.size };
                    })
                    onPicked: function (value) {
                        Settings.assign(routeRow.modelData.id, value);
                    }
                }
            }
        }

        // -- where models come from -----------------------------------------

        Squircle {
            Layout.fillWidth: true
            Layout.preferredHeight: hint.implicitHeight + Theme.space.lg * 2
            radius: Theme.radius.sm
            fillColor: Theme.inset
            borderColor: Theme.separator

            ColumnLayout {
                id: hint
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: Theme.space.lg
                spacing: Theme.space.xs

                Text {
                    Layout.fillWidth: true
                    text: Settings.availableModels.length === 0
                          ? "No models found."
                          : Settings.availableModels.length + " model"
                            + (Settings.availableModels.length === 1 ? "" : "s") + " found."
                    textFormat: Text.PlainText
                    font: Theme.type.bodyStrong
                    color: Theme.textPrimary
                }

                Text {
                    Layout.fillWidth: true
                    text: "Put .gguf files here, then press refresh:"
                    font: Theme.type.caption
                    color: Theme.textSecondary
                    wrapMode: Text.Wrap
                }

                Text {
                    Layout.fillWidth: true
                    text: Settings.modelsDirectory
                    textFormat: Text.PlainText
                    font: Theme.type.monoSmall
                    color: Theme.textTertiary
                    wrapMode: Text.WrapAnywhere
                }
            }
        }
    }
}
