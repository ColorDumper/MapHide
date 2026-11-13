"""Settings in the real window: closing it without Save puts back what's
saved, in the fields you see as well as underneath, and the footer says
when there are changes Save hasn't kept."""

import time

import pytest

pytest.importorskip("PySide6")

import PySide6.QtQuick  # noqa: E402,F401
from PySide6.QtCore import QEvent, QObject, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent  # noqa: E402
from test_controller import FakeService  # noqa: E402

from maphide.overlay import CONNECTED, RECONNECTING, ServiceStatus  # noqa: E402
from maphide.qt.app import Backend, build_window  # noqa: E402
from maphide.qt.view import RESET_DISCONNECTS, RESET_STOPS  # noqa: E402

SAVED = {"host": "10.0.0.2", "port": "4455", "scene_item_name": "Overlay"}


@pytest.fixture
def service():
    return FakeService()


@pytest.fixture
def setup(qt_app, service):
    saved = []
    backend = Backend(update_checks=False, save=saved.append, service=service)
    engine, window, warnings = build_window(backend)
    assert window is not None, warnings
    for name, value in SAVED.items():
        backend.setField(name, value)
    backend.save()
    # As if the SAVED stamp's two seconds were up.
    window.findChild(QObject, "settings").setProperty("savedStamp", False)
    window.show()
    open_settings(window)
    yield backend, window
    window.hide()
    del engine


def text_inputs(window):
    found, pending = [], [window.contentItem()]
    while pending:
        item = pending.pop(0)
        if item.inherits("QQuickTextInput"):
            found.append(item)
        pending.extend(item.childItems())
    return found


def type_into(window, field, text):
    field.forceActiveFocus()
    for char in text:
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(
                window, QKeyEvent(kind, 0, Qt.KeyboardModifier.NoModifier, char)
            )
    QGuiApplication.processEvents()


def host_field(window):
    return next(f for f in text_inputs(window) if f.property("text") == SAVED["host"])


def open_settings(window):
    """Open the drawer and wait for it to finish sliding in: until then it
    counts as hidden, and so does everything in it."""
    window.setProperty("drawerOpen", True)
    drawer = window.findChild(QObject, "drawer")
    deadline = time.monotonic() + 3
    while drawer.property("openness") < 1 and time.monotonic() < deadline:
        QGuiApplication.processEvents()
        time.sleep(0.01)
    assert drawer.property("openness") == 1


def close_settings(window):
    window.setProperty("drawerOpen", False)
    QGuiApplication.processEvents()


def test_typing_in_a_field_changes_the_form(setup):
    backend, window = setup

    type_into(window, host_field(window), "9")

    assert backend.form["host"] == "10.0.0.29"


def test_closing_settings_puts_the_typed_field_back(setup):
    backend, window = setup
    field = host_field(window)
    type_into(window, field, "9")

    close_settings(window)

    assert backend.form["host"] == SAVED["host"]
    assert field.property("text") == SAVED["host"]


def test_reset_shows_the_defaults_in_a_typed_field(setup):
    backend, window = setup
    field = host_field(window)
    type_into(window, field, "9")

    backend.resetDefaults()
    QGuiApplication.processEvents()

    assert field.property("text") == ""


def unsaved_note(window):
    return window.findChild(QObject, "unsavedNote")


def test_the_footer_says_when_changes_are_unsaved(setup):
    backend, window = setup
    assert not unsaved_note(window).property("visible")

    type_into(window, host_field(window), "9")

    assert unsaved_note(window).property("visible")


def test_the_saved_stamp_shows_instead_of_the_note(setup):
    backend, window = setup
    type_into(window, host_field(window), "9")

    backend.save()
    QGuiApplication.processEvents()

    assert not unsaved_note(window).property("visible")


def test_the_unsaved_note_goes_once_settings_close(setup):
    backend, window = setup
    type_into(window, host_field(window), "9")

    close_settings(window)
    open_settings(window)

    assert not unsaved_note(window).property("visible")
    assert backend.hasUnsavedChanges is False


# What a clicked Reset would interrupt.


def reset_warning(window):
    return window.findChild(QObject, "resetWarning")


def arm_reset(window):
    """Reset's first click: it now waits for a second."""
    window.findChild(QObject, "settings").setProperty("resetArmed", True)
    QGuiApplication.processEvents()


def run(backend, service, state, message):
    backend.primary()
    service.status = ServiceStatus(state, message)
    backend.refresh()
    QGuiApplication.processEvents()


def test_reset_warns_it_disconnects_while_connected(setup, service):
    backend, window = setup
    run(backend, service, CONNECTED, "Connected to OBS.")

    arm_reset(window)

    assert reset_warning(window).property("visible")
    assert reset_warning(window).property("text") == RESET_DISCONNECTS


def test_reset_warns_it_stops_maphide_while_still_connecting(setup, service):
    backend, window = setup
    run(backend, service, RECONNECTING, "Reconnecting... 2s")

    arm_reset(window)

    assert reset_warning(window).property("text") == RESET_STOPS


def test_reset_warns_nothing_until_clicked(setup, service):
    backend, window = setup
    run(backend, service, CONNECTED, "Connected to OBS.")

    assert not reset_warning(window).property("visible")


def test_reset_warns_nothing_while_stopped(setup):
    backend, window = setup

    arm_reset(window)

    assert not reset_warning(window).property("visible")


def test_the_reset_warning_shows_instead_of_the_unsaved_note(setup, service):
    backend, window = setup
    run(backend, service, CONNECTED, "Connected to OBS.")
    type_into(window, host_field(window), "9")

    arm_reset(window)

    assert reset_warning(window).property("visible")
    assert not unsaved_note(window).property("visible")


# Host, Port and Password go back to hidden.


def secret_fields(window):
    found, pending = [], [window.contentItem()]
    while pending:
        item = pending.pop(0)
        if item.property("secret") is True:
            found.append(item)
        pending.extend(item.childItems())
    return found


def reveal_all(window):
    fields = secret_fields(window)
    assert len(fields) == 3
    for field in fields:
        field.setProperty("revealed", True)
    QGuiApplication.processEvents()
    return fields


def test_closing_settings_hides_host_port_and_password_again(setup):
    backend, window = setup
    fields = reveal_all(window)

    close_settings(window)

    assert [field.property("revealed") for field in fields] == [False, False, False]


def test_hiding_maphide_to_the_tray_hides_them_too(setup):
    backend, window = setup
    fields = reveal_all(window)

    window.hide()
    QGuiApplication.processEvents()

    assert [field.property("revealed") for field in fields] == [False, False, False]


# Dragging the hide delay slider.


def hide_delay_slider(window):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop(0)
        if item.property("fraction") is not None and item.property("step") is not None:
            return item
        pending.extend(item.childItems())
    raise AssertionError("no slider")


def test_dragging_the_slider_off_course_never_scrolls_the_list(setup):
    backend, window = setup
    scroller = window.findChild(QObject, "settingsScroller")
    slider = hide_delay_slider(window)
    # Bring the slider into view, with room to drift up.
    scroller.setProperty("contentY", 0)
    QGuiApplication.processEvents()
    top = slider.mapToItem(scroller, QPointF(0, 0)).y()
    scroller.setProperty("contentY", max(0, top - scroller.height() / 2))
    QGuiApplication.processEvents()
    scrolled_to = scroller.property("contentY")
    before = backend.form["hide_delay_ms"]

    start = slider.mapToScene(QPointF(slider.width() * 0.3, slider.height() / 2))
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    keys = Qt.KeyboardModifier.NoModifier
    QGuiApplication.sendEvent(
        window, QMouseEvent(QEvent.Type.MouseButtonPress, start, start, left, left, keys)
    )
    # Along the slider, drifting well up: the list would take that over.
    for step in range(1, 21):
        point = QPointF(start.x() + step * 6, start.y() - step * 8)
        QGuiApplication.sendEvent(
            window, QMouseEvent(QEvent.Type.MouseMove, point, point, left, left, keys)
        )
        QGuiApplication.processEvents()
    QGuiApplication.sendEvent(
        window, QMouseEvent(QEvent.Type.MouseButtonRelease, point, point, left, none, keys)
    )
    QGuiApplication.processEvents()

    assert scroller.property("contentY") == scrolled_to
    assert backend.form["hide_delay_ms"] > before
