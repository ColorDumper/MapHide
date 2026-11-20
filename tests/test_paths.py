"""Tests for where MapHide keeps its settings."""

from pathlib import Path

import pytest

from maphide.paths import config_dir


def test_settings_live_in_the_appdata_folder():
    folder = config_dir({"APPDATA": r"C:\Users\Someone\AppData\Roaming"})

    assert folder == Path(r"C:\Users\Someone\AppData\Roaming\MapHide")


@pytest.mark.parametrize("environ", [{}, {"APPDATA": ""}])
def test_without_appdata_settings_still_go_to_appdata_roaming(environ):
    folder = config_dir(environ, home=lambda: Path(r"C:\Users\Someone"))

    assert folder == Path(r"C:\Users\Someone\AppData\Roaming\MapHide")
