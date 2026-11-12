"""The version is written once, in maphide/version.py; the exe's file
properties and the build channel come from there."""

import re

import pytest

from maphide.version import (
    APP_VERSION,
    CHANNEL_SOURCE,
    CHANNELS,
    VERSION,
    read_channel,
    version_parts,
)
from tools.version_resource import version_resource


def test_the_version_is_three_numbers():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), VERSION
    assert APP_VERSION == f"v{VERSION}"


def test_version_parts_adds_the_fourth_number_windows_wants():
    assert version_parts("0.3.0") == (0, 3, 0, 0)
    assert version_parts("1.10.2") == (1, 10, 2, 0)


@pytest.mark.parametrize("bad", ["v0.3.0", "0.3", "0.3.0.1", "0.3.x", ""])
def test_version_parts_refuses_anything_else(bad):
    with pytest.raises(ValueError):
        version_parts(bad)


def test_the_exe_properties_carry_the_version():
    resource = version_resource("1.10.2")
    strings = dict((entry.name, entry.val) for entry in resource.kids[0].kids[0].kids)

    assert resource.ffi.fileVersionMS == (1 << 16) | 10
    assert resource.ffi.fileVersionLS == (2 << 16) | 0
    assert strings["FileVersion"] == "1.10.2.0"
    assert strings["ProductVersion"] == "1.10.2.0"
    assert strings["ProductName"] == "MapHide"
    assert strings["OriginalFilename"] == "MapHide.exe"


@pytest.mark.parametrize("channel", CHANNELS)
def test_a_build_reads_its_channel(tmp_path, channel):
    path = tmp_path / "channel.txt"
    path.write_text(f"{channel.upper()}\n", encoding="utf-8")

    assert read_channel(path) == channel


def test_a_copy_without_a_channel_file_is_running_from_source(tmp_path):
    assert read_channel(tmp_path / "channel.txt") == CHANNEL_SOURCE


def test_an_unknown_channel_reads_as_source(tmp_path):
    path = tmp_path / "channel.txt"
    path.write_text("nightly", encoding="utf-8")

    assert read_channel(path) == CHANNEL_SOURCE
