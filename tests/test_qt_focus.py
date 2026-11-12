"""A text field in the window gives up the keyboard when you're done with
it, so keys pressed afterwards - such as your hotkey - don't land in it."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QMouseEvent  # noqa: E402

from maphide.qt.app import Backend, build_window  # noqa: E402


@pytest.fixture
def window(qt_app):
    backend = Backend()
    engine, window, warnings = build_window(backend)
    assert window is not None, warnings
    window.show()
    window.requestActivate()
    QGuiApplication.processEvents()
    yield window
    window.hide()
    del engine


def text_fields(window):
    found, pending = [], [window.contentItem()]
    while pending:
        item = pending.pop(0)
        if item.inherits("QQuickTextInput"):
            found.append(item)
        pending.extend(item.childItems())
    return found


def click(window, x, y):
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        event = QMouseEvent(
            kind,
            QPointF(x, y),
            QPointF(x, y),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton
            if kind == QEvent.Type.MouseButtonPress
            else Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QGuiApplication.sendEvent(window, event)
    QGuiApplication.processEvents()


def open_drawer_with_a_field_focused(window):
    window.setProperty("drawerOpen", True)
    QGuiApplication.processEvents()
    field = text_fields(window)[0]
    field.forceActiveFocus()
    assert field.hasActiveFocus()
    return field


def test_clicking_away_from_a_field_releases_it(window):
    field = open_drawer_with_a_field_focused(window)

    # The drawer's empty header area, well clear of any field.
    click(window, window.width() - 300, 30)

    assert not field.hasActiveFocus()


def test_clicking_inside_the_field_keeps_it(window):
    field = open_drawer_with_a_field_focused(window)
    inside = field.mapToScene(QPointF(field.width() / 2, field.height() / 2))

    click(window, inside.x(), inside.y())

    assert field.hasActiveFocus()


def test_closing_settings_releases_the_field(window):
    field = open_drawer_with_a_field_focused(window)

    window.setProperty("drawerOpen", False)
    QGuiApplication.processEvents()

    assert not field.hasActiveFocus()


def test_hiding_the_window_releases_the_field(window):
    field = open_drawer_with_a_field_focused(window)

    window.hide()
    QGuiApplication.processEvents()

    assert not field.hasActiveFocus()
