import QtQuick

/*!
    A small tracked-out label above a group of rows.

    Upper-cased and letter-spaced rather than merely small: at 11px, plain
    sentence case reads as body text that got lost, while tracked capitals read
    as structure.
*/
Text {
    color: Theme.textTertiary
    textFormat: Text.PlainText
    // Built with Qt.font() because QML forbids assigning both `font` and
    // `font.<sub>` on the same object.
    font: Qt.font({
        family: Theme.font.small,
        pixelSize: 11,
        weight: Font.DemiBold,
        capitalization: Font.AllUppercase,
        letterSpacing: 0.7
    })
}
