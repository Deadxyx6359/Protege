import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Akira

/*!
    Design-system proof sheet.

    Not part of the application — it exists so the tokens can be looked at
    directly, in both appearances, without launching Akira:

        python tools/preview.py akira/ui/qml/Gallery.qml --mode both
*/
Window {
    id: win
    width: 1180
    height: 760
    visible: true
    color: Theme.canvas
    title: "Akira — design system"

    ThemeLink {}

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth

        ColumnLayout {
            width: win.width
            spacing: Theme.space.xxl

            Item { Layout.preferredHeight: Theme.space.sm }

            // -- type ----------------------------------------------------------

            ColumnLayout {
                Layout.leftMargin: Theme.space.xxl
                Layout.rightMargin: Theme.space.xxl
                spacing: Theme.space.md

                SectionLabel { text: "Type — Segoe UI Variable, optically sized" }

                Text {
                    text: "Everything you know"
                    font: Theme.type.hero
                    color: Theme.textPrimary
                }
                Text {
                    text: "Title 1 — the heading of a view"
                    font: Theme.type.title1
                    color: Theme.textPrimary
                }
                Text {
                    text: "Title 2 — a section within it"
                    font: Theme.type.title2
                    color: Theme.textPrimary
                }
                Text {
                    text: "Headline — a card's name"
                    font: Theme.type.headline
                    color: Theme.textPrimary
                }
                Text {
                    Layout.maximumWidth: 640
                    text: "Body. The reading size, set in the Text cut for its wider "
                        + "apertures. Long-form answers, notes and documents all land "
                        + "here, so it is the one size worth being fussy about."
                    font: Theme.type.body
                    color: Theme.textPrimary
                    wrapMode: Text.WordWrap
                    lineHeight: Theme.leading.relaxed
                    lineHeightMode: Text.ProportionalHeight
                }
                Text {
                    text: "Callout — supporting detail"
                    font: Theme.type.callout
                    color: Theme.textSecondary
                }
                Text {
                    text: "CAPTION — TIMESTAMPS AND LABELS"
                    font: Theme.type.caption
                    color: Theme.textTertiary
                }
                Text {
                    text: "const mono = \"Cascadia Mono\";  // code and paths"
                    font: Theme.type.mono
                    color: Theme.textSecondary
                }
            }

            // -- shape ---------------------------------------------------------

            ColumnLayout {
                Layout.leftMargin: Theme.space.xxl
                Layout.rightMargin: Theme.space.xxl
                spacing: Theme.space.md

                SectionLabel { text: "Shape — continuous corners against circular" }

                RowLayout {
                    spacing: Theme.space.xl

                    Repeater {
                        model: [
                            { r: Theme.radius.md, label: "14" },
                            { r: Theme.radius.lg, label: "20" },
                            { r: Theme.radius.xl, label: "28" }
                        ]

                        ColumnLayout {
                            required property var modelData
                            spacing: Theme.space.sm

                            RowLayout {
                                spacing: Theme.space.sm

                                Rectangle {
                                    implicitWidth: 132; implicitHeight: 92
                                    radius: parent.parent.modelData.r
                                    color: Theme.surface
                                    border.color: Theme.separator
                                    border.width: 1

                                    Text {
                                        anchors.centerIn: parent
                                        text: "circular"
                                        font: Theme.type.caption
                                        color: Theme.textTertiary
                                    }
                                }

                                Squircle {
                                    implicitWidth: 132; implicitHeight: 92
                                    radius: parent.parent.modelData.r
                                    fillColor: Theme.surface
                                    borderColor: Theme.separator

                                    Text {
                                        anchors.centerIn: parent
                                        text: "continuous"
                                        font: Theme.type.captionStrong
                                        color: Theme.textSecondary
                                    }
                                }
                            }

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: "radius " + parent.modelData.label
                                textFormat: Text.PlainText
                                font: Theme.type.caption
                                color: Theme.textTertiary
                            }
                        }
                    }
                }
            }

            // -- colour --------------------------------------------------------

            ColumnLayout {
                Layout.leftMargin: Theme.space.xxl
                Layout.rightMargin: Theme.space.xxl
                spacing: Theme.space.md

                SectionLabel { text: "Colour — " + Theme.mode }

                Flow {
                    Layout.fillWidth: true
                    Layout.rightMargin: Theme.space.xxl
                    spacing: Theme.space.sm

                    Repeater {
                        model: [
                            { c: Theme.canvas, n: "canvas" },
                            { c: Theme.surface, n: "surface" },
                            { c: Theme.surfaceHover, n: "hover" },
                            { c: Theme.surfaceActive, n: "active" },
                            { c: Theme.overlay, n: "overlay" },
                            { c: Theme.inset, n: "inset" },
                            { c: Theme.accent, n: "accent" },
                            { c: Theme.accentHover, n: "accent+" },
                            { c: Theme.success, n: "success" },
                            { c: Theme.warning, n: "warning" },
                            { c: Theme.danger, n: "danger" },
                            { c: Theme.info, n: "info" }
                        ]

                        Squircle {
                            required property var modelData
                            width: 108; height: 64
                            radius: Theme.radius.sm
                            fillColor: modelData.c
                            borderColor: Theme.separator

                            Text {
                                anchors.left: parent.left
                                anchors.bottom: parent.bottom
                                anchors.margins: Theme.space.sm
                                text: parent.modelData.n
                                textFormat: Text.PlainText
                                font: Theme.type.caption
                                color: Theme.contrastText(parent.modelData.c)
                            }
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: Theme.space.xxl }
        }
    }

    // Tracked out and upper-cased: at caption size this reads as a label
    // rather than as very small body text. Built with Qt.font() because QML
    // forbids assigning both `font` and `font.<sub>` on the same object.
    component SectionLabel: Text {
        color: Theme.textTertiary
        text: ""
        font: Qt.font({
            family: Theme.font.small,
            pixelSize: 11.5,
            weight: Font.DemiBold,
            capitalization: Font.AllUppercase,
            letterSpacing: 0.8
        })
    }
}
