import QtQuick

// A horizontal slider from `from` to `to` in steps of `step`.
Item {
    id: slider
    property real from: 0
    property real to: 100
    property real step: 1
    property real value: 0
    signal moved(real value)

    readonly property var t: backend.theme
    readonly property real fraction: (value - from) / (to - from)
    height: 24

    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        height: 4
        color: slider.t.border2
        Rectangle {
            width: parent.width * slider.fraction
            height: parent.height
            color: slider.t.accent
        }
    }
    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        x: (slider.width - width) * slider.fraction
        width: 12
        height: 20
        color: slider.t.accent
        border.color: slider.t.accent_deep
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        function pick(x) {
            const fraction = Math.max(0, Math.min(1, x / width))
            const steps = Math.round(fraction * (slider.to - slider.from) / slider.step)
            slider.moved(slider.from + steps * slider.step)
        }
        onPressed: (mouse) => pick(mouse.x)
        onPositionChanged: (mouse) => pick(mouse.x)
    }
}
