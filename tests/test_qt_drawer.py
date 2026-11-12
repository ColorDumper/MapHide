"""Settings in the real window: closing it without Save puts back what's
saved, in the fields you see as well as underneath, and the footer says
when there are changes Save hasn't kept."""

import time

import pytest

pytest.importorskip("PySide6")

import PySide6.QtQuick  # noqa: E402,F401
from PySide6.QtCore import QEvent, QObject, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402

from maphide.qt.app import Backend, build_window  # noqa: E402

SAVED = {"host": "10.0.0.2", "port": "4455", "scene_item_name": "Overlay"}


@pytest.fixture
def setup(qt_app):
    saved = []
    backend = Backend(update_checks=False, save=saved.append)
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
