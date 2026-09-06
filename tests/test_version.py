"""version_info.txt must track APP_VERSION, or the exe's file properties drift
from the release. CI also checks the tag against both on a tagged build."""

import re
from pathlib import Path

from maphide.paths import APP_VERSION

VERSION_INFO = Path(__file__).resolve().parent.parent / "version_info.txt"


def test_app_version_is_a_three_part_v_tag():
    assert re.fullmatch(r"v\d+\.\d+\.\d+", APP_VERSION), APP_VERSION


def test_version_info_matches_app_version():
    major, minor, patch = APP_VERSION.lstrip("v").split(".")
    text = VERSION_INFO.read_text(encoding="utf-8")

    tuple_ = f"({major}, {minor}, {patch}, 0)"
    dotted = f"{major}.{minor}.{patch}.0"

    assert f"filevers={tuple_}" in text
    assert f"prodvers={tuple_}" in text
    assert f'StringStruct("FileVersion", "{dotted}")' in text
    assert f'StringStruct("ProductVersion", "{dotted}")' in text
