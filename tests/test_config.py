"""Tests for loading, saving, and sanitising the config file."""

import json

import pytest

from maphide.config import (
    DEFAULT_HIDE_DELAY_MS,
    MAX_HIDE_DELAY_MS,
    MAX_PORT,
    MIN_HIDE_DELAY_MS,
    MIN_PORT,
    AppConfig,
    default_config,
    load_config,
    save_config,
)

BASE = {
    "host": "10.0.0.2",
    "port": 4455,
    "password": "secret",
    "scene_item_name": "Overlay",
}


def test_from_dict_keeps_valid_values():
    cfg = AppConfig.from_dict({**BASE, "hotkey": "M", "hide_hotkey": "ESC", "hide_delay_ms": 200})
    assert (cfg.hotkey, cfg.hide_hotkey, cfg.hide_delay_ms, cfg.port) == (
        "M",
        "ESC",
        200,
        4455,
    )


def test_from_dict_clamps_hide_delay_out_of_range():
    assert AppConfig.from_dict({**BASE, "hide_delay_ms": -50}).hide_delay_ms == MIN_HIDE_DELAY_MS
    assert (
        AppConfig.from_dict({**BASE, "hide_delay_ms": 10_000}).hide_delay_ms == MAX_HIDE_DELAY_MS
    )


def test_from_dict_clamps_out_of_range_port():
    assert AppConfig.from_dict({**BASE, "port": 999_999}).port == MAX_PORT
    assert AppConfig.from_dict({**BASE, "port": 0}).port == MIN_PORT


def test_from_dict_falls_back_on_unusable_hotkeys():
    cfg = AppConfig.from_dict({**BASE, "hotkey": "F13", "hide_hotkey": "CTRL+ALT+DEL"})
    assert (cfg.hotkey, cfg.hide_hotkey) == ("G", "H")


def test_from_dict_accepts_a_lowercase_hotkey():
    assert AppConfig.from_dict({**BASE, "hotkey": "m"}).hotkey == "M"


def test_from_dict_requires_the_core_keys():
    with pytest.raises(KeyError):
        AppConfig.from_dict({"host": "x", "port": 4455, "password": ""})


def test_from_dict_defaults_auto_reconnect_on_for_configs_saved_before_it_existed():
    assert AppConfig.from_dict(BASE).auto_reconnect is True


# --- a hand-edited file must be reported as unreadable, never crash startup ---
# The callers that load the config catch ValueError (and KeyError for a
# missing key) and fall back to the default settings.


@pytest.mark.parametrize("content", [[], None, "text", 5])
def test_a_config_that_is_not_an_object_is_unreadable(content):
    with pytest.raises(ValueError):
        AppConfig.from_dict(content)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("port", None),
        ("port", "abc"),
        ("port", float("inf")),
        ("hide_delay_ms", "abc"),
    ],
)
def test_a_number_that_is_not_a_number_is_unreadable(field, value):
    with pytest.raises(ValueError):
        AppConfig.from_dict({**BASE, field: value})


@pytest.mark.parametrize("field", ["host", "scene_item_name"])
def test_a_required_value_left_null_is_unreadable(field):
    with pytest.raises(ValueError):
        AppConfig.from_dict({**BASE, field: None})


def test_optional_values_left_null_fall_back_to_their_defaults():
    cfg = AppConfig.from_dict(
        {
            **BASE,
            "password": None,
            "hide_delay_ms": None,
            "auto_reconnect": None,
            "hotkey": None,
        }
    )

    assert cfg.password == ""
    assert cfg.hide_delay_ms == DEFAULT_HIDE_DELAY_MS
    assert cfg.auto_reconnect is True
    assert cfg.hotkey == "G"


def test_a_config_file_holding_null_is_unreadable(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("null", encoding="utf-8")

    with pytest.raises(ValueError):
        load_config(path)


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "config.json"
    cfg = AppConfig.from_dict(
        {**default_config().to_dict(), "host": "10.0.0.5", "scene_item_name": "Map"}
    )
    save_config(cfg, path)
    assert load_config(path) == cfg


def test_hand_edited_delay_is_sanitised_on_load(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**BASE, "hide_delay_ms": 99_999}), encoding="utf-8")
    assert load_config(path).hide_delay_ms == MAX_HIDE_DELAY_MS


def test_to_loggable_dict_excludes_the_password_and_the_network_address():
    # host/port are effectively someone's network address, and password is
    # never allowed near the log file - everything else is safe to include
    # so a pasted debug log can be cross-referenced against what was
    # actually configured at the time.
    cfg = AppConfig.from_dict({**BASE, "hotkey": "M"})

    loggable = cfg.to_loggable_dict()

    assert "password" not in loggable
    assert "host" not in loggable
    assert "port" not in loggable
    assert loggable["hotkey"] == "M"
    assert loggable["scene_item_name"] == "Overlay"
