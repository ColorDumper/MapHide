"""The field log scrolls sideways for a line too long to fit, but only when
you scroll it: a new line never moves it."""

import time

import pytest

pytest.importorskip("PySide6")

import PySide6.QtQuick  # noqa: E402,F401
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QMouseEvent, QWheelEvent  # noqa: E402

from maphide.qt.app import Backend, build_window, load_fonts  # noqa: E402

LONG = "> scene · Gameplay - Fullscreen Main Cam (Ranked) yoyoyoyoyoyoyoyoyoyoyoyoy"


@pytest.fixture
def window(qt_app):
    load_fonts()
    backend = Backend(update_checks=False, save=lambda cfg: None)
    engine, window, warnings = build_window(backend)
    assert window is not None, warnings
    window.show()
    window._backend = backend
    yield window
    window.hide()
    del engine


def find(window, name):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop(0)
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    raise AssertionError(f"{name} not found")


def settle(seconds=0.5):
    """Let the lines finish typing themselves in."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QGuiApplication.processEvents()
        time.sleep(0.01)


def add(window, text):
    window._backend.lineAdded.emit("19:00:49", text, "")
    settle()


def view(window):
    return find(window, "fieldLogView")


def bar(window):
    return find(window, "fieldLogBar")


def scrolled(window):
    return view(window).property("contentX")


def test_short_lines_need_no_scroll_bar(window):
    add(window, "> cover dropped")

    assert not bar(window).isVisible()


def test_a_line_too_long_to_fit_brings_up_the_scroll_bar(window):
    add(window, LONG)

    assert bar(window).isVisible()
    assert scrolled(window) == 0


def test_a_new_line_never_scrolls_the_log(window):
    add(window, LONG)
    view(window).setProperty("contentX", 40)

    add(window, LONG + " more")
    add(window, "> cover dropped")

    assert scrolled(window) == 40


def drag(window, item, dx):
    start = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    end = QPointF(start.x() + dx, start.y())
    left = Qt.MouseButton.LeftButton
    none = Qt.MouseButton.NoButton
    no_keys = Qt.KeyboardModifier.NoModifier
    for kind, point, buttons in (
        (QEvent.Type.MouseButtonPress, start, left),
        (QEvent.Type.MouseMove, QPointF(start.x() + dx / 2, start.y()), left),
        (QEvent.Type.MouseMove, end, left),
        (QEvent.Type.MouseButtonRelease, end, none),
    ):
        QGuiApplication.sendEvent(window, QMouseEvent(kind, point, point, left, buttons, no_keys))
        QGuiApplication.processEvents()


def test_dragging_the_bar_scrolls_the_log(window):
    add(window, LONG)

    drag(window, find(window, "fieldLogHandle"), 60)

    assert scrolled(window) > 0


def test_the_mouse_wheel_scrolls_the_log_sideways(window):
    add(window, LONG)
    log = view(window)
    point = log.mapToScene(QPointF(log.width() / 2, 10))

    QGuiApplication.sendEvent(
        window,
        QWheelEvent(
            point,
            point,
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        ),
    )
    QGuiApplication.processEvents()

    assert scrolled(window) > 0


def test_once_the_long_lines_are_gone_the_log_slides_back(window):
    add(window, LONG)
    view(window).setProperty("contentX", 80)

    for _ in range(6):
        add(window, "> cover dropped")

    assert scrolled(window) == 0
    assert not bar(window).isVisible()
