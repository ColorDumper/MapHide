"""Tests for the color themes and the theme setting."""

from dataclasses import fields

import pytest

from maphide.themes import DEFAULT_THEME, THEMES, Theme, theme_name


def test_the_default_theme_is_one_of_the_themes():
    assert DEFAULT_THEME in THEMES


@pytest.mark.parametrize("name", list(THEMES))
def test_every_theme_gives_every_color_as_hex(name):
    theme = THEMES[name]
    for field in fields(Theme):
        value = getattr(theme, field.name)
        if field.type is str and field.name != "label":
            assert len(value) == 7 and value.startswith("#"), (name, field.name, value)
            int(value[1:], 16)
        if field.type is float:
            assert 0 <= value <= 1, (name, field.name, value)


@pytest.mark.parametrize(
    ("saved", "expected"),
    [("legacy", "legacy"), (" Legacy ", "legacy"), ("FIELD", "field"), ("neon", "field")],
)
def test_a_saved_theme_name_is_read_case_insensitively_with_a_fallback(saved, expected):
    assert theme_name(saved) == expected
