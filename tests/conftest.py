import os

import pytest


@pytest.fixture(scope="session")
def qt_app():
    """One Qt application for every test that needs Qt, drawing off-screen
    so no window appears while the tests run."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.instance() or QGuiApplication([])
