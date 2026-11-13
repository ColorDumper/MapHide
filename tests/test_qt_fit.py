"""The window fits a screen shorter than it was designed for, such as a
1920x1080 display at 150% scaling, with Save still in reach."""

import pytest

pytest.importorskip("PySide6")

import PySide6.QtQuick  # noqa: E402,F401
from PySide6.QtCore import QObject, QPointF  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from maphide.qt.app import (  # noqa: E402
    DEFAULT_FRAME_HEIGHT,
    MIN_WINDOW_HEIGHT,
    Backend,
    ScreenFit,
    build_window,
    fitted_height,
    on_screen_top,
    set_window_height,
)

FULL = 748
TITLE_BAR = 31
# 1920x1080 at 150%: 720 high in the window's units, minus a 48 taskbar.
LAPTOP_AVAILABLE = 672


def test_a_tall_enough_screen_gets_the_full_height():
    assert fitted_height(FULL, 1032, TITLE_BAR) == FULL


def test_a_short_screen_gets_what_fits_under_the_title_bar():
    assert fitted_height(FULL, LAPTOP_AVAILABLE, TITLE_BAR) == LAPTOP_AVAILABLE - TITLE_BAR


def test_a_tiny_screen_still_gets_the_minimum():
    assert fitted_height(FULL, 300, TITLE_BAR) == MIN_WINDOW_HEIGHT


def test_a_window_already_on_screen_stays_put():
    assert on_screen_top(100, 700, 0, 1032) == 100


def test_a_window_hanging_below_the_taskbar_moves_up():
    assert on_screen_top(100, 672, 0, 672) == 0
    assert on_screen_top(200, 600, 0, 672) == 72


def test_a_window_above_the_screen_moves_down():
    assert on_screen_top(-40, 600, 0, 672) == 0


def test_a_window_taller_than_the_screen_keeps_its_title_bar_visible():
    assert on_screen_top(50, 800, 0, 672) == 0


@pytest.fixture
def window(qt_app):
    backend = Backend(update_checks=False, save=lambda cfg: None)
    engine, window, warnings = build_window(backend)
    assert window is not None, warnings
    yield window
    window.hide()
    del engine


def bottom_in_window(item):
    return item.mapToScene(QPointF(0, item.height())).y()


def test_the_window_starts_at_its_full_height_and_holds_it(window):
    assert window.height() == FULL
    assert window.minimumHeight() == window.maximumHeight() == FULL


def test_a_new_height_takes_even_after_the_native_window_exists(window):
    # The app creates the native window early, to colour its title bar.
    window.winId()

    set_window_height(window, 600)
    assert window.height() == 600
    assert window.minimumHeight() == window.maximumHeight() == 600

    set_window_height(window, FULL)
    assert window.height() == FULL
    assert window.minimumHeight() == window.maximumHeight() == FULL


def test_the_window_fits_its_screen(window):
    window.winId()
    available = window.screen().availableGeometry().height()
    set_window_height(window, MIN_WINDOW_HEIGHT)

    ScreenFit(window)

    assert window.height() == fitted_height(FULL, available, DEFAULT_FRAME_HEIGHT)


@pytest.mark.parametrize("height", [LAPTOP_AVAILABLE - TITLE_BAR, MIN_WINDOW_HEIGHT])
def test_save_stays_inside_a_shorter_window(window, height):
    set_window_height(window, height)
    window.setProperty("drawerOpen", True)
    window.show()
    QGuiApplication.processEvents()

    assert window.height() == height
    save = window.findChild(QObject, "saveButton")
    assert bottom_in_window(save) <= height


@pytest.mark.parametrize("height", [LAPTOP_AVAILABLE - TITLE_BAR, MIN_WINDOW_HEIGHT])
def test_the_field_log_shrinks_instead_of_running_off(window, height):
    set_window_height(window, height)
    window.show()
    QGuiApplication.processEvents()

    log = window.findChild(QObject, "fieldLog")
    assert log.height() >= 0
    assert bottom_in_window(log) <= height
