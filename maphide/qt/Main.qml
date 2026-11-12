import QtQuick
import QtQuick.Effects
import QtQuick.Shapes

Window {
    id: win

    readonly property var t: backend.theme
    readonly property string st: backend.screen
    readonly property bool running: backend.primaryIsStop
    readonly property color coverRed: "#d9483b"
    readonly property color coverRedText: "#ff7a6b"
    property bool drawerOpen: false
    onDrawerOpenChanged: if (!drawerOpen) settings.stopCapture()

    width: 480
    height: 748
    minimumWidth: width
    maximumWidth: width
    minimumHeight: height
    maximumHeight: height
    visible: true
    title: "MapHide"
    color: t.bg

    // Closing stops the worker first, so it can hide the overlay in OBS.
    onClosing: (close) => {
        close.accepted = false
        backend.requestClose()
    }

    // Letter spacing as a fraction of the font size; Qt wants pixels.
    function em(size, amount) { return size * amount }

    Item {
        id: stage
        anchors.fill: parent

        Item {
            id: main
            anchors.fill: parent
            transformOrigin: Item.Left
            scale: win.drawerOpen ? 0.965 : 1
            Behavior on scale { NumberAnimation { duration: 340; easing.type: Easing.Bezier; easing.bezierCurve: [0.2, 0.9, 0.25, 1, 1, 1] } }

            // Faint contour lines behind everything.
            Shape {
                anchors.fill: parent
                opacity: win.t.topo_line_opacity
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: win.t.topo_line
                    strokeWidth: 1.2
                    fillColor: "transparent"
                    PathSvg {
                        path: "M-20 100 C 80 60, 160 140, 260 90 S 420 40, 520 100"
                            + " M-20 130 C 90 90, 170 170, 270 120 S 430 75, 520 130"
                            + " M-20 530 C 60 490, 180 580, 280 530 S 410 470, 520 530"
                            + " M-20 565 C 70 525, 190 615, 290 565 S 420 510, 520 570"
                            + " M-20 600 C 80 560, 200 650, 300 600 S 430 550, 520 610"
                            + " M-20 670 C 90 630, 210 710, 310 670 S 440 620, 520 680"
                    }
                }
            }

            Column {
                id: column
                x: 20
                y: 16
                width: parent.width - 40
                spacing: 14

                // Header
                Item {
                    width: parent.width
                    height: 44
                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 10
                        Condensed {
                            id: title
                            text: "MAPHIDE"
                            font.pixelSize: 32
                            font.weight: Font.Bold
                            font.letterSpacing: win.em(32, 0.08)
                        }
                        Mono {
                            anchors.baseline: title.baseline
                            text: backend.version
                            font.pixelSize: 11
                            color: win.t.muted
                        }
                    }
                    PressButton {
                        anchors.right: parent.right
                        width: settingsRow.width + 28
                        height: 44
                        fill: win.t.glass_button
                        edge: win.t.border
                        onClicked: win.drawerOpen = true
                        Row {
                            id: settingsRow
                            anchors.centerIn: parent
                            spacing: 8
                            Item {
                                width: 16
                                height: 16
                                anchors.verticalCenter: parent.verticalCenter
                                Shape {
                                    width: 24
                                    height: 24
                                    scale: 16 / 24
                                    transformOrigin: Item.TopLeft
                                    preferredRendererType: Shape.CurveRenderer
                                    ShapePath {
                                        strokeColor: win.t.text; strokeWidth: 2; capStyle: ShapePath.RoundCap
                                        fillColor: "transparent"
                                        PathSvg { path: "M4 7 L20 7 M4 17 L20 17" }
                                    }
                                    ShapePath {
                                        strokeColor: win.t.text; strokeWidth: 2; fillColor: win.t.bg
                                        PathAngleArc { centerX: 9; centerY: 7; radiusX: 2.5; radiusY: 2.5; sweepAngle: 360 }
                                    }
                                    ShapePath {
                                        strokeColor: win.t.text; strokeWidth: 2; fillColor: win.t.bg
                                        PathAngleArc { centerX: 15; centerY: 17; radiusX: 2.5; radiusY: 2.5; sweepAngle: 360 }
                                    }
                                }
                            }
                            Condensed {
                                text: "SETTINGS"
                                font.pixelSize: 15
                                font.letterSpacing: win.em(15, 0.1)
                            }
                        }
                    }
                }

                // Status strip
                Rectangle {
                    width: parent.width
                    height: 52
                    color: "transparent"
                    border.color: win.t.border
                    Row {
                        anchors.fill: parent
                        anchors.margins: 1
                        Repeater {
                            model: 3
                            delegate: Rectangle {
                                id: cell
                                required property int index
                                width: parent.width / 3
                                height: parent.height
                                color: win.t.glass
                                Rectangle {
                                    visible: cell.index > 0
                                    width: 1; height: parent.height
                                    color: win.t.border
                                }
                                Column {
                                    x: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 2
                                    Condensed {
                                        text: ["OBS LINK", "LIVE SCENE", "MODE"][cell.index]
                                        font.pixelSize: 12
                                        font.weight: Font.Normal
                                        font.letterSpacing: win.em(12, 0.14)
                                        color: win.t.muted
                                    }
                                    Row {
                                        spacing: 6
                                        Rectangle {
                                            id: dot
                                            visible: cell.index === 0
                                            width: 7; height: 7
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: value.color
                                            SequentialAnimation on opacity {
                                                running: win.st === "connecting"
                                                loops: Animation.Infinite
                                                onRunningChanged: if (!running) dot.opacity = 1
                                                PropertyAction { value: 1 }
                                                PauseAnimation { duration: 500 }
                                                PropertyAction { value: 0.25 }
                                                PauseAnimation { duration: 500 }
                                            }
                                        }
                                        Mono {
                                            id: value
                                            font.pixelSize: 13
                                            text: cell.index === 0
                                                ? ({ stopped: "OFFLINE", connecting: "LINKING" })[win.st] || "ONLINE"
                                                : cell.index === 1 ? backend.scene : backend.mode
                                            color: cell.index !== 0 ? win.t.text
                                                : win.st === "stopped" ? win.t.muted
                                                : win.st === "connecting" ? win.t.warn : win.t.ok
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // Map box
                Rectangle {
                    id: mapBox
                    width: parent.width
                    height: 250
                    color: "#24404a"
                    border.color: win.t.border
                    readonly property bool covering: win.st === "covering"
                    onCoveringChanged: if (covering) coverIn.restart()

                    Item {
                        id: mapArea
                        anchors.fill: parent
                        anchors.margins: 1
                        clip: true

                        Image {
                            id: mapImage
                            anchors.fill: parent
                            source: backend.assets + "/MapBox.webp"
                            fillMode: Image.PreserveAspectCrop
                            visible: false
                        }
                        MultiEffect {
                            anchors.fill: parent
                            source: mapImage
                            saturation: ({ stopped: -1, connecting: -0.7, covering: -0.4 })[win.st] ?? -0.1
                            brightness: ({ stopped: -0.5, connecting: -0.35, covering: -0.18 })[win.st] ?? -0.08
                            contrast: win.st === "stopped" ? 0.1 : 0
                            Behavior on saturation { NumberAnimation { duration: 400 } }
                            Behavior on brightness { NumberAnimation { duration: 400 } }
                        }

                        // 6 x 4 grid: a light line with a dark one beside it.
                        Repeater {
                            model: 5
                            delegate: Item {
                                required property int index
                                x: Math.round(mapArea.width * (index + 1) / 6)
                                width: 2; height: mapArea.height
                                Rectangle { width: 1; height: parent.height; color: "#33ebe5d3" }
                                Rectangle { x: 1; width: 1; height: parent.height; color: "#73000000" }
                            }
                        }
                        Repeater {
                            model: 3
                            delegate: Item {
                                required property int index
                                y: Math.round(mapArea.height * (index + 1) / 4)
                                height: 2; width: mapArea.width
                                Rectangle { height: 1; width: parent.width; color: "#33ebe5d3" }
                                Rectangle { y: 1; height: 1; width: parent.width; color: "#73000000" }
                            }
                        }
                        Repeater {
                            model: ["A", "B", "C", "D", "E", "F"]
                            delegate: Mono {
                                required property int index
                                required property string modelData
                                x: mapArea.width * index / 6 + 5
                                y: 4
                                text: modelData
                                font.pixelSize: 10
                                color: "#bfebe5d3"
                                style: Text.Raised
                                styleColor: "#d9000000"
                            }
                        }

                        // Scan line, only while linked and not covering.
                        Item {
                            id: sweep
                            visible: win.st === "connected"
                            width: parent.width
                            height: 2
                            Rectangle {
                                anchors.centerIn: parent
                                width: parent.width
                                height: 22
                                gradient: Gradient {
                                    GradientStop { position: 0; color: "transparent" }
                                    GradientStop { position: 0.5; color: Qt.alpha(win.t.scan_line, 0.35) }
                                    GradientStop { position: 1; color: "transparent" }
                                }
                            }
                            Rectangle { anchors.fill: parent; color: win.t.scan_line }
                            // Stepped by a timer rather than animated, so it
                            // redraws 30 times a second instead of at the
                            // display's refresh rate - which on a gaming
                            // monitor can be 240 Hz or more. It holds still
                            // while another window is in front, such as the
                            // game: nobody is watching it then.
                            Timer {
                                interval: 33
                                repeat: true
                                running: sweep.visible && win.active
                                onTriggered: sweep.y = -12 + (Date.now() % 3200) / 3200 * 274
                            }
                        }

                        // NO LINK
                        Rectangle {
                            anchors.fill: parent
                            color: "#8c0a0b09"
                            opacity: win.st === "stopped" ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: 150 } }
                            Rectangle {
                                anchors.centerIn: parent
                                width: noLink.width + 32
                                height: noLink.height + 12
                                color: win.t.bg
                                border.color: win.t.border2
                                Condensed {
                                    id: noLink
                                    anchors.centerIn: parent
                                    text: "NO LINK"
                                    font.pixelSize: 22
                                    font.letterSpacing: win.em(22, 0.3)
                                    color: win.t.muted
                                }
                            }
                        }

                        // Covered: dim, the red X draws in, then the stamp.
                        Item {
                            id: cover
                            property real stroke1: 0
                            property real stroke2: 0
                            anchors.fill: parent
                            opacity: mapBox.covering ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: 150 } }

                            Rectangle { anchors.fill: parent; color: "#990a0b09" }
                            Shape {
                                anchors.fill: parent
                                opacity: 0.92
                                preferredRendererType: Shape.CurveRenderer
                                ShapePath {
                                    strokeColor: win.coverRed; strokeWidth: 14
                                    capStyle: ShapePath.RoundCap; fillColor: "transparent"
                                    startX: 100; startY: 30
                                    PathLine { x: 100 + 238 * cover.stroke1; y: 30 + 190 * cover.stroke1 }
                                }
                                ShapePath {
                                    strokeColor: win.coverRed; strokeWidth: 14
                                    capStyle: ShapePath.RoundCap; fillColor: "transparent"
                                    startX: 338; startY: 30
                                    PathLine { x: 338 - 238 * cover.stroke2; y: 30 + 190 * cover.stroke2 }
                                }
                            }
                            Rectangle {
                                id: stamp
                                anchors.centerIn: parent
                                width: stampText.width + 36
                                height: stampText.height + 4
                                rotation: -7
                                color: "#b30a0b09"
                                border.color: win.coverRedText
                                border.width: 4
                                antialiasing: true
                                Condensed {
                                    id: stampText
                                    anchors.centerIn: parent
                                    text: "COVERED"
                                    font.pixelSize: 44
                                    font.weight: Font.Bold
                                    font.letterSpacing: win.em(44, 0.16)
                                    color: win.coverRedText
                                    renderType: Text.QtRendering
                                }
                            }
                        }
                        ParallelAnimation {
                            id: coverIn
                            NumberAnimation { target: cover; property: "stroke1"; from: 0; to: 1; duration: 280; easing.type: Easing.OutQuad }
                            SequentialAnimation {
                                PropertyAction { target: cover; property: "stroke2"; value: 0 }
                                PauseAnimation { duration: 100 }
                                NumberAnimation { target: cover; property: "stroke2"; from: 0; to: 1; duration: 280; easing.type: Easing.OutQuad }
                            }
                            SequentialAnimation {
                                PropertyAction { target: stamp; property: "opacity"; value: 0 }
                                PropertyAction { target: stamp; property: "scale"; value: 1.9 }
                                ParallelAnimation {
                                    NumberAnimation { target: stamp; property: "scale"; to: 0.93; duration: 176; easing.type: Easing.OutCubic }
                                    NumberAnimation { target: stamp; property: "opacity"; to: 1; duration: 176 }
                                }
                                NumberAnimation { target: stamp; property: "scale"; to: 1; duration: 144 }
                            }
                        }
                    }
                }

                // State text
                Column {
                    width: parent.width
                    spacing: 2
                    Condensed {
                        text: ({ stopped: "OFFLINE", connecting: "ACQUIRING LINK", covering: "MAP COVERED" })[win.st] || "STANDBY"
                        font.pixelSize: 26
                        font.weight: Font.Bold
                        font.letterSpacing: win.em(26, 0.06)
                        color: ({ stopped: win.t.muted, connecting: win.t.warn, covering: win.coverRedText })[win.st] || win.t.text
                    }
                    Label {
                        width: parent.width
                        text: backend.hint
                        wrapMode: Text.Wrap
                        font.pixelSize: 13
                        color: win.t.muted
                    }
                }

                // Buttons
                Row {
                    width: parent.width
                    spacing: 10
                    PressButton {
                        width: (parent.width - 10) / 2
                        height: 50
                        base: 4
                        enabled: backend.primaryEnabled
                        opacity: enabled ? 1 : 0.4
                        fill: win.running ? win.t.glass_button : win.t.accent
                        edge: win.running ? win.t.border2 : win.t.accent_deep
                        onClicked: backend.primary()
                        Condensed {
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: -2
                            text: win.running ? "STOP" : "START"
                            font.pixelSize: 19
                            font.weight: Font.Bold
                            font.letterSpacing: win.em(19, 0.14)
                            color: win.running ? win.t.text : win.t.on_accent
                        }
                    }
                    PressButton {
                        width: (parent.width - 10) / 2
                        height: 50
                        base: 4
                        enabled: backend.testEnabled
                        opacity: enabled ? 1 : 0.4
                        fill: win.t.glass_button
                        edge: win.t.border2
                        onDown: backend.holdDown()
                        onUp: backend.holdUp()
                        Row {
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: -2
                            spacing: 8
                            Condensed {
                                anchors.verticalCenter: parent.verticalCenter
                                text: backend.toggleMode ? "PRESS" : "HOLD"
                                font.pixelSize: 17
                                font.letterSpacing: win.em(17, 0.12)
                            }
                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                width: keyCap.width + 16
                                height: keyCap.height + 3
                                color: win.t.bg
                                border.color: win.t.faint
                                Rectangle {
                                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                                    height: 3
                                    color: win.t.faint
                                }
                                Mono {
                                    id: keyCap
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: backend.showKey
                                    font.pixelSize: 13
                                }
                            }
                            Condensed {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "TO TEST"
                                font.pixelSize: 17
                                font.letterSpacing: win.em(17, 0.12)
                            }
                        }
                    }
                }

                // Field log
                Rectangle {
                    width: parent.width
                    height: win.height - y - column.y - 36
                    color: win.t.glass
                    border.color: win.t.border
                    clip: true
                    Column {
                        x: 14
                        y: 10
                        width: parent.width - 28
                        spacing: 5
                        Condensed {
                            text: "FIELD LOG"
                            font.pixelSize: 13
                            font.weight: Font.Normal
                            font.letterSpacing: win.em(13, 0.16)
                            color: win.t.muted
                        }
                        Repeater {
                            model: ListModel { id: logModel }
                            delegate: Item {
                                id: line
                                required property string time
                                required property string text
                                required property string tone
                                property real reveal: 0
                                width: lineRow.width * Math.floor(reveal * 18) / 18
                                height: lineRow.height
                                clip: true
                                NumberAnimation on reveal { from: 0; to: 1; duration: 350 }
                                Row {
                                    id: lineRow
                                    spacing: 10
                                    Mono { text: line.time; font.pixelSize: 12; color: win.t.faint }
                                    Mono {
                                        text: line.text
                                        font.pixelSize: 12
                                        color: ({
                                            linked: win.t.ok,
                                            covered: win.coverRedText,
                                            warning: win.t.warn
                                        })[line.tone] || win.t.text
                                    }
                                }
                            }
                        }
                    }
                    Connections {
                        target: backend
                        function onLineAdded(time, text, tone) {
                            logModel.insert(0, { time: time, text: text, tone: tone })
                            if (logModel.count > 6)
                                logModel.remove(6, logModel.count - 6)
                        }
                    }
                }
            }

            // Watermark
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 14
                spacing: 6
                opacity: 0.6
                Image {
                    width: 14; height: 14
                    anchors.verticalCenter: parent.verticalCenter
                    source: backend.assets + "/MapHide_Watermark.png"
                    smooth: true
                    mipmap: true
                }
                Label {
                    text: "Color Dumper"
                    font.pixelSize: 11
                    font.letterSpacing: win.em(11, 0.04)
                    color: win.t.muted
                }
            }

            // Dims the main screen behind the drawer (55% brightness).
            Rectangle {
                anchors.fill: parent
                color: "black"
                opacity: win.drawerOpen ? 0.45 : 0
                Behavior on opacity { NumberAnimation { duration: 340 } }
            }
        }

        // Backdrop: clicking it closes the drawer.
        Rectangle {
            anchors.fill: parent
            color: "#59000000"
            opacity: win.drawerOpen ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 300 } }
            MouseArea { anchors.fill: parent; onClicked: win.drawerOpen = false }
        }

        // Settings drawer: slides in over the main screen.
        Rectangle {
            id: drawer
            width: 436
            height: parent.height
            x: win.drawerOpen ? parent.width - width : parent.width
            visible: x < parent.width
            color: win.t.bg
            Behavior on x { NumberAnimation { duration: 340; easing.type: Easing.Bezier; easing.bezierCurve: [0.2, 0.9, 0.25, 1, 1, 1] } }
            Rectangle { width: 1; height: parent.height; color: win.t.border2 }
            MouseArea { anchors.fill: parent }

            Settings {
                id: settings
                anchors.fill: parent
                anchors.leftMargin: 1
                onCloseRequested: win.drawerOpen = false
            }
        }
    }
}
