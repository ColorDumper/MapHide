import QtQuick
import QtQuick.Shapes

// The settings drawer's contents: seven numbered sections, then Reset and
// Save. Edits stay in the form, unapplied, until Save.
Item {
    id: settings

    readonly property var t: backend.theme
    readonly property var f: backend.form
    // "show" or "hide" while waiting for a key, else "".
    property string capturing: ""
    // Why the last key pressed can't be used, shown for a moment.
    property string keyProblem: ""
    property bool resetArmed: false
    property string footerProblem: ""
    property bool savedStamp: false
    signal closeRequested()

    function stopCapture() { capturing = "" }

    function startCapture(target) {
        capturing = capturing === target ? "" : target
        keyProblem = ""
        if (capturing !== "")
            keyCatcher.forceActiveFocus()
    }

    function useKey(key, shift) {
        const problem = backend.captureKey(capturing, key, shift)
        keyProblem = problem
        if (problem !== "")
            keyProblemTimer.restart()
        capturing = ""
    }

    Timer { id: keyProblemTimer; interval: 4000; onTriggered: settings.keyProblem = "" }
    Timer { id: resetTimer; interval: 3000; onTriggered: settings.resetArmed = false }
    Timer { id: savedTimer; interval: 2000; onTriggered: settings.savedStamp = false }
    Timer { id: footerTimer; interval: 6000; onTriggered: settings.footerProblem = "" }
    Timer {
        id: testTimer
        interval: backend.testState === "ok" ? 3200 : 8000
        running: backend.testState === "ok" || backend.testState === "failed"
        onTriggered: backend.clearTest()
    }

    Connections {
        target: backend
        function onSaved() {
            settings.footerProblem = ""
            settings.savedStamp = true
            stamp.pop()
            savedTimer.restart()
        }
        function onSaveFailed(reason) {
            settings.savedStamp = false
            settings.footerProblem = reason
            footerTimer.restart()
        }
    }

    // Takes the key press while a key cap is waiting for one.
    Item {
        id: keyCatcher
        property bool shiftAlone: false
        Keys.onPressed: (event) => {
            event.accepted = true
            if (event.isAutoRepeat || settings.capturing === "")
                return
            if (event.key === Qt.Key_Shift) {
                shiftAlone = true
                return
            }
            shiftAlone = false
            settings.useKey(event.key, (event.modifiers & Qt.ShiftModifier) !== 0)
        }
        Keys.onReleased: (event) => {
            event.accepted = true
            // Shift on its own counts once it's let go without a letter.
            if (event.key === Qt.Key_Shift && shiftAlone && settings.capturing !== "") {
                shiftAlone = false
                settings.useKey(Qt.Key_Shift, false)
            }
        }
    }

    // Header
    Item {
        id: header
        x: 18
        y: 14
        width: parent.width - 36
        height: 44
        Condensed {
            anchors.verticalCenter: parent.verticalCenter
            text: "SETTINGS"
            font.pixelSize: 28
            font.weight: Font.Bold
            font.letterSpacing: 28 * 0.08
        }
        PressButton {
            anchors.right: parent.right
            width: 44
            height: 44
            fill: settings.t.panel
            edge: settings.t.border
            onClicked: settings.closeRequested()
            Shape {
                anchors.centerIn: parent
                width: 16
                height: 16
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: settings.t.text
                    strokeWidth: 2.4
                    fillColor: "transparent"
                    capStyle: ShapePath.SquareCap
                    PathSvg { path: "M6 14 L11 8 L6 2" }
                }
            }
        }
    }

    Flickable {
        id: scroller
        objectName: "settingsScroller"
        anchors.top: header.bottom
        anchors.topMargin: 14
        anchors.bottom: footer.top
        width: parent.width
        contentHeight: sections.height + 20
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: sections
            x: 18
            width: scroller.width - 36
            spacing: 22

            // 01 OBS LINK
            Column {
                width: parent.width
                spacing: 10
                Item {
                    width: parent.width
                    height: 32
                    SectionHeading {
                        anchors.verticalCenter: parent.verticalCenter
                        number: "01"
                        title: "OBS LINK"
                    }
                    PressButton {
                        anchors.right: parent.right
                        width: testRow.width + 24
                        height: 32
                        fill: settings.t.panel2
                        edge: settings.t.border2
                        onClicked: backend.testLink()
                        Row {
                            id: testRow
                            anchors.centerIn: parent
                            spacing: 6
                            Spinner {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: backend.testState === "busy"
                            }
                            Condensed {
                                text: ({ busy: "TESTING", ok: "LINK OK", failed: "NO LINK" })[backend.testState] || "TEST LINK"
                                font.pixelSize: 14
                                font.letterSpacing: 14 * 0.08
                                color: ({ ok: settings.t.ok, failed: settings.t.warn })[backend.testState] || settings.t.text
                            }
                        }
                    }
                }
                Row {
                    width: parent.width
                    spacing: 8
                    Field {
                        width: (parent.width - 8) * 2 / 3
                        label: "HOST"
                        secret: true
                        text: settings.f.host
                        onEdited: (text) => backend.setField("host", text)
                    }
                    Field {
                        width: (parent.width - 8) / 3
                        label: "PORT"
                        secret: true
                        digitsOnly: true
                        text: settings.f.port
                        onEdited: (text) => backend.setField("port", text)
                    }
                }
                Field {
                    width: parent.width
                    label: "PASSWORD"
                    secret: true
                    warning: settings.f.password === ""
                    note: settings.f.password === "" ? "Empty: anyone on your network can control OBS" : ""
                    text: settings.f.password
                    onEdited: (text) => backend.setField("password", text)
                }
                Label {
                    width: parent.width
                    visible: backend.testState === "failed"
                    text: backend.testMessage
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                    color: settings.t.warn
                }
            }

            // 02 COVER SOURCE
            Column {
                width: parent.width
                spacing: 8
                SectionHeading { number: "02"; title: "COVER SOURCE" }
                Field {
                    width: parent.width
                    label: "OBS SOURCE NAME"
                    text: settings.f.scene_item_name
                    onEdited: (text) => backend.setField("scene_item_name", text)
                }
                Label {
                    width: parent.width
                    text: backend.sourceText
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                    color: backend.sourceWarning ? settings.t.warn : settings.t.muted
                }
            }

            // 03 HOTKEYS
            Column {
                width: parent.width
                spacing: 10
                SectionHeading { number: "03"; title: "HOTKEYS" }

                // Hold / Toggle, with a highlight that slides between them.
                Rectangle {
                    id: modeSwitch
                    width: parent.width
                    height: 42
                    color: settings.t.panel
                    border.color: settings.t.border
                    readonly property bool toggle: settings.f.toggle_mode
                    Rectangle {
                        y: 3
                        x: modeSwitch.toggle ? modeSwitch.width / 2 : 3
                        width: modeSwitch.width / 2 - 3
                        height: 34
                        color: settings.t.accent
                        Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutBack } }
                    }
                    Row {
                        anchors.fill: parent
                        Repeater {
                            model: [{ label: "HOLD", toggle: false }, { label: "TOGGLE", toggle: true }]
                            delegate: Item {
                                id: modeOption
                                required property var modelData
                                width: modeSwitch.width / 2
                                height: modeSwitch.height
                                Condensed {
                                    anchors.centerIn: parent
                                    text: modeOption.modelData.label
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                    font.letterSpacing: 16 * 0.14
                                    color: modeSwitch.toggle === modeOption.modelData.toggle
                                        ? settings.t.on_accent : settings.t.muted
                                    Behavior on color { ColorAnimation { duration: 200 } }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        settings.stopCapture()
                                        backend.setField("toggle_mode", modeOption.modelData.toggle)
                                    }
                                }
                            }
                        }
                    }
                }

                Row {
                    width: parent.width
                    spacing: 10
                    Repeater {
                        model: settings.f.toggle_mode ? ["show", "hide"] : ["show"]
                        delegate: Column {
                            id: cap
                            required property string modelData
                            readonly property bool waiting: settings.capturing === modelData
                            readonly property string hotkey: modelData === "show"
                                ? settings.f.hotkey : settings.f.hide_hotkey
                            width: settings.f.toggle_mode ? (parent.width - 10) / 2 : parent.width
                            spacing: 4
                            Label {
                                text: cap.modelData === "hide" ? "HIDE KEY"
                                    : settings.f.toggle_mode ? "SHOW KEY" : "HOLD KEY"
                                font.pixelSize: 12
                                font.letterSpacing: 12 * 0.04
                                color: settings.t.muted
                            }
                            PressButton {
                                width: parent.width
                                height: 54
                                base: 5
                                fill: settings.t.panel2
                                edge: settings.t.border2
                                onClicked: settings.startCapture(cap.modelData)
                                Mono {
                                    anchors.centerIn: parent
                                    anchors.verticalCenterOffset: -2
                                    text: cap.waiting ? "Press a key…" : backend.keyLabel(cap.hotkey)
                                    font.pixelSize: cap.waiting ? 13 : cap.hotkey.length > 2 ? 15 : 22
                                    font.weight: Font.Medium
                                }
                                // Pulses while waiting for a key.
                                Rectangle {
                                    anchors.fill: parent
                                    anchors.margins: -3
                                    color: "transparent"
                                    border.width: 2
                                    border.color: settings.t.text
                                    visible: cap.waiting
                                    SequentialAnimation on opacity {
                                        running: cap.waiting
                                        loops: Animation.Infinite
                                        NumberAnimation { from: 0.35; to: 0; duration: 1000; easing.type: Easing.InOutSine }
                                    }
                                }
                            }
                        }
                    }
                }
                Label {
                    width: parent.width
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                    color: settings.keyProblem !== "" ? settings.t.warn : settings.t.muted
                    text: settings.keyProblem !== "" ? settings.keyProblem
                        : settings.f.toggle_mode
                        ? "Press " + backend.keyLabel(settings.f.hotkey) + " to cover the map, "
                            + backend.keyLabel(settings.f.hide_hotkey)
                            + " to uncover. Same key on both flips it each press."
                        : "Cover stays up while " + backend.keyLabel(settings.f.hotkey)
                            + " is held, and drops when you let go."
                }
            }

            // 04 HIDE DELAY
            Column {
                width: parent.width
                spacing: 8
                Item {
                    width: parent.width
                    height: 22
                    SectionHeading { number: "04"; title: "HIDE DELAY" }
                    Mono {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: settings.f.hide_delay_ms + "ms"
                        font.pixelSize: 15
                        font.weight: Font.Medium
                    }
                }
                Slider {
                    width: parent.width
                    from: 0
                    to: 400
                    step: 10
                    value: settings.f.hide_delay_ms
                    onMoved: (value) => backend.setField("hide_delay_ms", value)
                }
                Label {
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: "Keeps the cover up a moment longer so the map's closing animation never flashes on stream."
                    font.pixelSize: 12
                    color: settings.t.muted
                }
            }

            // 05 BEHAVIOR
            Column {
                width: parent.width
                spacing: 6
                SectionHeading { number: "05"; title: "BEHAVIOR" }
                Rectangle {
                    width: parent.width
                    height: behavior.height + 2
                    color: settings.t.panel
                    border.color: settings.t.border
                    Column {
                        id: behavior
                        x: 1
                        y: 1
                        width: parent.width - 2
                        Switch {
                            width: parent.width
                            label: "Connect on startup"
                            description: "Link up with OBS as soon as MapHide opens"
                            checked: settings.f.auto_connect
                            onToggled: (on) => backend.setField("auto_connect", on)
                        }
                        Switch {
                            width: parent.width
                            divider: true
                            label: "Auto reconnect"
                            description: "Retry if OBS closes or the network drops"
                            checked: settings.f.auto_reconnect
                            onToggled: (on) => backend.setField("auto_reconnect", on)
                        }
                        Switch {
                            width: parent.width
                            divider: true
                            label: "Debug log"
                            description: "Write a log file to the config folder"
                            checked: settings.f.log_enabled
                            onToggled: (on) => backend.setField("log_enabled", on)
                        }
                    }
                }
            }

            // 06 THEME
            Column {
                width: parent.width
                spacing: 8
                SectionHeading { number: "06"; title: "THEME" }
                Row {
                    width: parent.width
                    spacing: 8
                    Repeater {
                        model: [
                            { name: "field", label: "FIELD", swatches: ["#13140f", "#24261d", "#d9483b", "#ebe5d3"] },
                            { name: "legacy", label: "LEGACY", swatches: ["#12161d", "#222c3b", "#4da3ff", "#e6edf7"] }
                        ]
                        delegate: PressButton {
                            id: tile
                            required property var modelData
                            width: (parent.width - 8) / 2
                            height: 74
                            fill: settings.t.panel
                            edge: "transparent"
                            onClicked: backend.setField("theme", modelData.name)
                            Rectangle {
                                anchors.fill: parent
                                color: "transparent"
                                border.width: 2
                                border.color: backend.themeName === tile.modelData.name
                                    ? settings.t.accent : settings.t.border
                                Behavior on border.color { ColorAnimation { duration: 200 } }
                            }
                            Column {
                                x: 12
                                y: 12
                                spacing: 8
                                Row {
                                    spacing: 4
                                    Repeater {
                                        model: tile.modelData.swatches
                                        delegate: Rectangle {
                                            required property string modelData
                                            width: 22
                                            height: 22
                                            color: modelData
                                        }
                                    }
                                }
                                Condensed {
                                    text: tile.modelData.label
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                    font.letterSpacing: 16 * 0.12
                                }
                            }
                        }
                    }
                }
            }

            // 07 ABOUT
            Column {
                width: parent.width
                spacing: 8
                SectionHeading { number: "07"; title: "ABOUT" }
                Rectangle {
                    width: parent.width
                    height: 54
                    color: settings.t.panel
                    border.color: settings.t.border
                    Row {
                        x: 12
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 12
                        Image {
                            width: 28
                            height: 28
                            anchors.verticalCenter: parent.verticalCenter
                            source: backend.assets + "/MapHide_Icon_64.png"
                            mipmap: true
                        }
                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2
                            Mono { text: "MapHide " + backend.version; font.pixelSize: 13 }
                            Label {
                                text: "github.com/ColorDumper/MapHide"
                                font.pixelSize: 12
                                font.underline: aboutLink.containsMouse
                                color: settings.t.accent_text
                                MouseArea {
                                    id: aboutLink
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Qt.openUrlExternally("https://github.com/ColorDumper/MapHide")
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // A thin bar showing where in the list you are.
    Rectangle {
        visible: scroller.contentHeight > scroller.height
        anchors.right: parent.right
        anchors.rightMargin: 4
        y: scroller.y + scroller.visibleArea.yPosition * scroller.height
        width: 3
        height: scroller.visibleArea.heightRatio * scroller.height
        color: settings.t.border2
    }

    // Footer: Reset (click twice), Save.
    Item {
        id: footer
        anchors.bottom: parent.bottom
        width: parent.width
        height: 74
        Rectangle { width: parent.width; height: 1; color: settings.t.border }

        PressButton {
            id: resetButton
            x: 18
            y: 12
            width: resetLabel.width + 28
            height: 46
            fill: "transparent"
            edge: settings.resetArmed ? settings.t.warn : settings.t.border2
            onClicked: {
                settings.stopCapture()
                if (settings.resetArmed) {
                    settings.resetArmed = false
                    resetTimer.stop()
                    backend.resetDefaults()
                } else {
                    settings.resetArmed = true
                    resetTimer.restart()
                }
            }
            Condensed {
                id: resetLabel
                anchors.centerIn: parent
                text: settings.resetArmed ? "CLICK AGAIN" : "RESET"
                font.pixelSize: 15
                font.letterSpacing: 15 * 0.1
                color: settings.resetArmed ? settings.t.warn : settings.t.text
            }
        }

        Item {
            anchors.left: resetButton.right
            anchors.right: saveButton.left
            anchors.margins: 10
            y: 12
            height: 46
            Label {
                anchors.fill: parent
                visible: settings.footerProblem !== ""
                text: settings.footerProblem
                wrapMode: Text.Wrap
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 12
                color: settings.t.warn
            }
            Rectangle {
                id: stamp
                anchors.centerIn: parent
                visible: settings.savedStamp
                width: savedText.width + 20
                height: savedText.height
                rotation: -7
                color: "transparent"
                border.width: 3
                border.color: settings.t.ok
                antialiasing: true
                function pop() { stampIn.restart() }
                Condensed {
                    id: savedText
                    anchors.centerIn: parent
                    text: "SAVED"
                    font.pixelSize: 20
                    font.weight: Font.Bold
                    font.letterSpacing: 20 * 0.2
                    color: settings.t.ok
                    renderType: Text.QtRendering
                }
                SequentialAnimation {
                    id: stampIn
                    PropertyAction { target: stamp; property: "scale"; value: 1.9 }
                    PropertyAction { target: stamp; property: "opacity"; value: 0 }
                    ParallelAnimation {
                        NumberAnimation { target: stamp; property: "scale"; to: 0.93; duration: 176; easing.type: Easing.OutCubic }
                        NumberAnimation { target: stamp; property: "opacity"; to: 1; duration: 176 }
                    }
                    NumberAnimation { target: stamp; property: "scale"; to: 1; duration: 144 }
                }
            }
        }

        PressButton {
            id: saveButton
            anchors.right: parent.right
            anchors.rightMargin: 18
            y: 12
            width: 104
            height: 46
            base: 4
            fill: settings.t.accent
            edge: settings.t.accent_deep
            onClicked: {
                settings.stopCapture()
                backend.save()
            }
            Condensed {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -2
                text: "SAVE"
                font.pixelSize: 18
                font.weight: Font.Bold
                font.letterSpacing: 18 * 0.14
                color: settings.t.on_accent
            }
        }
    }
}
