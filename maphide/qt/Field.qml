import QtQuick
import QtQuick.Shapes

// A labelled text field. A `secret` one is masked, with an eye button
// that shows what's in it.
Column {
    id: field
    property string label
    property string text
    property bool secret: false
    property bool revealed: false
    property bool warning: false
    property bool digitsOnly: false
    property alias note: noteText.text
    signal edited(string text)

    readonly property var t: backend.theme
    spacing: 4

    Row {
        spacing: 8
        Label {
            text: field.label
            font.pixelSize: 12
            font.letterSpacing: 12 * 0.04
            color: field.t.muted
        }
        Label {
            id: noteText
            visible: text !== ""
            font.pixelSize: 11
            color: field.t.warn
        }
    }

    Rectangle {
        width: parent.width
        height: 40
        color: field.t.panel
        border.color: input.activeFocus ? field.t.accent
            : field.warning ? field.t.warn : field.t.border

        TextInput {
            id: input
            anchors.fill: parent
            leftPadding: 12
            rightPadding: field.secret ? 40 : 12
            verticalAlignment: TextInput.AlignVCenter
            clip: true
            selectByMouse: true
            text: field.text
            echoMode: field.secret && !field.revealed ? TextInput.Password : TextInput.Normal
            font.family: "IBM Plex Mono"
            font.pixelSize: 13
            color: field.t.text
            selectionColor: field.t.accent_deep
            selectedTextColor: field.t.text
            maximumLength: field.digitsOnly ? 5 : 256
            validator: RegularExpressionValidator {
                regularExpression: field.digitsOnly ? /[0-9]*/ : /.*/
            }
            onTextEdited: field.edited(text)
        }

        // The eye: shows or masks what's typed.
        Item {
            visible: field.secret
            anchors.right: parent.right
            anchors.rightMargin: 2
            anchors.verticalCenter: parent.verticalCenter
            width: 36
            height: 36
            Shape {
                anchors.centerIn: parent
                width: 24
                height: 24
                scale: 17 / 24
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: field.revealed ? field.t.accent_text : field.t.muted
                    strokeWidth: 2
                    fillColor: "transparent"
                    capStyle: ShapePath.RoundCap
                    joinStyle: ShapePath.RoundJoin
                    PathSvg {
                        path: "M2 12 C2 12 5 5 12 5 C19 5 22 12 22 12 C22 12 19 19 12 19 C5 19 2 12 2 12 Z"
                    }
                }
                ShapePath {
                    strokeColor: field.revealed ? field.t.accent_text : field.t.muted
                    strokeWidth: 2
                    fillColor: "transparent"
                    PathAngleArc { centerX: 12; centerY: 12; radiusX: 3; radiusY: 3; sweepAngle: 360 }
                }
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: field.revealed = !field.revealed
            }
        }
    }
}
