import QtQuick

// A flat button that sinks 2px while pressed. `base` is the thickness of
// its bottom edge.
Item {
    id: button
    property color fill
    property color edge
    property int base: 1
    property alias pressed: area.pressed
    default property alias content: face.data
    signal clicked()
    signal down()
    signal up()

    Rectangle {
        id: face
        width: parent.width
        height: parent.height
        y: button.pressed ? 2 : 0
        color: button.fill
        border.color: button.edge
        Behavior on y { NumberAnimation { duration: 80 } }
        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: button.base
            color: button.edge
        }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        enabled: button.enabled
        cursorShape: Qt.PointingHandCursor
        onClicked: button.clicked()
        onPressed: button.down()
        onReleased: button.up()
        onCanceled: button.up()
    }
}
