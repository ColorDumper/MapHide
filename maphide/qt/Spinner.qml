import QtQuick
import QtQuick.Shapes

// A small turning arc for "working on it".
Shape {
    id: spinner
    property color color: backend.theme.text
    width: 12
    height: 12
    preferredRendererType: Shape.CurveRenderer
    ShapePath {
        strokeColor: spinner.color
        strokeWidth: 2
        capStyle: ShapePath.RoundCap
        fillColor: "transparent"
        PathAngleArc {
            centerX: 6; centerY: 6; radiusX: 4.5; radiusY: 4.5
            startAngle: 0; sweepAngle: 290
        }
    }
    RotationAnimation on rotation {
        running: spinner.visible
        from: 0; to: 360
        duration: 800
        loops: Animation.Infinite
    }
}
