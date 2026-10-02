import QtQuick
import QtQuick.Controls as C

/*!
    A one-line text box: a name, a path, a key.

    \c secret shows what is typed as dots, for a key or a token. What is typed
    reaches the caller through \c edited; the box itself keeps nothing.
*/
Rectangle {
    id: field

    property string text: ""
    /*! Shown as dots, for a key or a token. */
    property bool secret: false
    property string label: placeholder
    property alias placeholder: input.placeholderText
    signal edited(string value)
    signal accepted()

    radius: Theme.radius.sm
    color: Theme.inset
    border.width: 1
    border.color: input.activeFocus ? Theme.accent : Theme.separator
    implicitHeight: 32

    function focusInput() { input.forceActiveFocus(); }

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
        echoMode: field.secret ? TextInput.Password : TextInput.Normal
        Accessible.name: field.label
        onTextEdited: field.edited(text)
        onAccepted: field.accepted()
    }
}
