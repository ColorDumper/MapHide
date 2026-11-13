"""The main screen's status boxes (OBS LINK, LIVE SCENE, MODE) keep their
text inside them, however long a scene name is."""

import pytest

pytest.importorskip("PySide6")

import PySide6.QtQuick  # noqa: E402,F401
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from test_controller import FakeService  # noqa: E402

from maphide.overlay import CONNECTED, ObsSnapshot, ServiceStatus  # noqa: E402
from maphide.qt.app import Backend, build_window, load_fonts  # noqa: E402

LONG_SCENE = "Gameplay - Fullscreen Main Cam (Ranked)"


@pytest.fixture
def setup(qt_app):
    # Sizes depend on the font, so use the one the app draws in.
    load_fonts()
    service = FakeService()
    backend = Backend(update_checks=False, save=lambda cfg: None, service=service)
    engine, window, warnings = build_window(backend)
    assert window is not None, warnings
    window.show()
    yield backend, service, window
    window.hide()
    del engine


def connect(backend, service, scene, **settings):
    form = {"host": "10.0.0.2", "port": "4455", "scene_item_name": "Overlay", **settings}
    for name, value in form.items():
        backend.setField(name, value)
    backend.save()
    backend.primary()
    service.status = ServiceStatus(CONNECTED, "Connected to OBS.")
    service.snapshot = ObsSnapshot(scene=scene)
    backend.refresh()
    QGuiApplication.processEvents()


def value(window, index):
    # Made by a Repeater, so only the visual tree reaches it.
    pending = [window.contentItem()]
    while pending:
        item = pending.pop(0)
        if item.objectName() == f"statusValue{index}":
            return item
        pending.extend(item.childItems())
    return None


def right_edge(item):
    """Where the drawn text ends, in window coordinates."""
    return item.mapToScene(QPointF(item.property("contentWidth"), 0)).x()


def box_right_edge(item):
    box = item.property("box")
    return box.mapToScene(QPointF(box.width(), 0)).x()


def test_a_long_scene_name_stays_in_its_box(setup):
    backend, service, window = setup
    connect(backend, service, LONG_SCENE)

    scene = value(window, 1)

    assert right_edge(scene) <= box_right_edge(scene)
    # Cut short with "…", so it's clear there is more.
    assert scene.property("truncated")


def test_a_short_scene_name_shows_in_full(setup):
    backend, service, window = setup
    connect(backend, service, "Gameplay")

    scene = value(window, 1)

    assert scene.property("text") == "Gameplay"
    assert not scene.property("truncated")


def test_toggle_mode_with_a_shift_key_fits_without_being_cut(setup):
    backend, service, window = setup
    connect(backend, service, "Gameplay", toggle_mode=True, hotkey="G", hide_hotkey="SHIFT+H")

    mode = value(window, 2)

    assert mode.property("text") == "TOGGLE · G/SHIFT+H"
    assert right_edge(mode) <= box_right_edge(mode)
    assert not mode.property("truncated")


def test_the_link_state_stays_in_its_box(setup):
    backend, service, window = setup
    connect(backend, service, "Gameplay")

    link = value(window, 0)

    assert right_edge(link) <= box_right_edge(link)
