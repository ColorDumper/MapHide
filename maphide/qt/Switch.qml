import QtQuick

// An on/off switch with a label and a one-line description.
Item {
    id: row
    property string label
    property string description
    property bool checked: false
    property bool divider: false
    signal toggled(bool checked)

    readonly property var t: backend.theme
    height: 58

    Rectangle {
        visible: row.divider
        width: parent.width
        height: 1
        color: row.t.border
    }
    Column {
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.right: track.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 1
        Label { text: row.label; font.pixelSize: 14; font.weight: Font.Medium }
        Label { text: row.description; font.pixelSize: 12; color: row.t.muted }
    }
    Rectangle {
        id: track
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        width: 44
        height: 24
        color: row.checked ? row.t.accent : row.t.switch_off
        Behavior on color { ColorAnimation { duration: 200 } }
        Rectangle {
            y: 4
            x: row.checked ? 24 : 4
            width: 16
            height: 16
            color: row.t.text
            Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutBack } }
        }
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: row.toggled(!row.checked)
    }
}
