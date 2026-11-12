import QtQuick

// "01  OBS LINK": a numbered section heading.
Row {
    id: heading
    property string number
    property string title
    spacing: 10
    Mono {
        anchors.baseline: titleText.baseline
        text: heading.number
        font.pixelSize: 12
        color: backend.theme.accent_text
    }
    Condensed {
        id: titleText
        text: heading.title
        font.pixelSize: 17
        font.letterSpacing: 17 * 0.12
    }
}
