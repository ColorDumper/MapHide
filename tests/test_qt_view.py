"""The main screen's rules, checked without Qt."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from maphide.config import config_from_form, default_config
from maphide.controller import HistoryEntry
from maphide.hotkeys import HIDE_KEY_HELP, SHOW_KEY_HELP
from maphide.overlay import (
    CONNECTED,
    CONNECTING,
    IDLE,
    RECONNECTING,
    STOPPED,
    STOPPED_MESSAGE,
    STOPPING,
    ObsSnapshot,
    ServiceStatus,
)
from maphide.qt.view import (
    APPLYING_HINT,
    CAPTURE_HIDE,
    CAPTURE_SHOW,
    CONNECTING_HINT,
    COVERING_HINT,
    QT_KEY_ESCAPE,
    QT_KEY_SHIFT,
    RESET_DISCONNECTS,
    RESET_STOPS,
    SCREEN_CONNECTED,
    SCREEN_CONNECTING,
    SCREEN_COVERING,
    SCREEN_STOPPED,
    SOURCE_FOLLOWS,
    SOURCE_UNKNOWN,
    STOPPED_HINT,
    STOPPING_HINT,
    captured_hotkey,
    form_values,
    hotkey_from_key,
    key_label,
    main_view,
    new_entries,
    source_line,
)


def controller(
    state=IDLE,
    message="Idle",
    snapshot=None,
    restart_pending=False,
    cfg=None,
    can_start=True,
    can_stop=False,
    can_test=False,
):
    return SimpleNamespace(
        service=SimpleNamespace(status=ServiceStatus(state, message)),
        snapshot=snapshot or ObsSnapshot(),
        restart_pending=restart_pending,
        running_config=cfg or default_config(),
        can_start=can_start,
        can_stop=can_stop,
        can_test=can_test,
    )


@pytest.mark.parametrize("message", ["Idle", STOPPED_MESSAGE])
def test_a_quiet_stop_invites_a_start(message):
    view = main_view(controller(STOPPED, message))

    assert view.screen == SCREEN_STOPPED
    assert view.hint == STOPPED_HINT
    assert view.scene == "—"
    assert not view.primary_is_stop
    assert view.primary_enabled


def test_a_stop_after_a_failure_keeps_saying_why():
    reason = "Failed to connect to OBS. The OBS WebSocket password appears to be incorrect."

    view = main_view(controller(STOPPED, reason))

    assert view.screen == SCREEN_STOPPED
    assert view.hint == reason


def test_connecting_looks_for_obs():
    view = main_view(
        controller(CONNECTING, "Connecting to OBS...", can_start=False, can_stop=True)
    )

    assert view.screen == SCREEN_CONNECTING
    assert view.hint == CONNECTING_HINT
    assert view.scene == "…"
    assert view.primary_is_stop
    assert view.primary_enabled


def test_reconnecting_shows_the_workers_own_countdown():
    view = main_view(controller(RECONNECTING, "Reconnecting... 2s"))

    assert view.screen == SCREEN_CONNECTING
    assert view.hint == "Reconnecting... 2s"


def test_connected_names_the_live_scene_and_how_to_cover():
    view = main_view(
        controller(
            CONNECTED,
            "Connected to OBS.",
            snapshot=ObsSnapshot(scene="Gameplay"),
            can_start=False,
            can_stop=True,
            can_test=True,
        )
    )

    assert view.screen == SCREEN_CONNECTED
    assert view.scene == "Gameplay"
    assert view.hint == "Hold G in game and the map is covered."
    assert view.test_enabled


def test_toggle_mode_says_press_and_names_both_keys():
    cfg = replace(default_config(), toggle_mode=True, hotkey="M", hide_hotkey="ESC")

    view = main_view(controller(CONNECTED, "Connected to OBS.", cfg=cfg))

    assert view.hint == "Press M in game to cover the map."
    assert view.mode == "TOGGLE · M/ESC"
    assert view.toggle_mode
    assert view.show_key == "M"


def test_hold_mode_names_its_key():
    assert main_view(controller()).mode == "HOLD · G"


def test_a_covered_map_shows_as_covering():
    snapshot = ObsSnapshot(scene="Gameplay", covered=True)

    view = main_view(controller(CONNECTED, "Connected to OBS.", snapshot))

    assert view.screen == SCREEN_COVERING
    assert view.hint == COVERING_HINT


def test_a_settings_restart_reads_as_connecting_and_cant_be_stopped_midway():
    view = main_view(controller(STOPPING, "Stopping...", restart_pending=True, can_start=False))

    assert view.screen == SCREEN_CONNECTING
    assert view.hint == APPLYING_HINT
    assert view.primary_is_stop
    assert not view.primary_enabled


def test_stopping_reads_as_offline_but_cant_be_started_yet():
    view = main_view(controller(STOPPING, "Stopping...", can_start=False))

    assert view.screen == SCREEN_STOPPED
    assert view.hint == STOPPING_HINT
    assert not view.primary_is_stop
    assert not view.primary_enabled


# What Reset warns about, once clicked.


@pytest.mark.parametrize(
    ("ctrl", "warning"),
    [
        (controller(), ""),
        (controller(STOPPED, "Failed to connect to OBS."), ""),
        (controller(STOPPING, "Stopping..."), ""),
        (controller(CONNECTING, "Connecting to OBS..."), RESET_STOPS),
        (controller(RECONNECTING, "Reconnecting... 2s"), RESET_STOPS),
        (controller(STOPPING, "Stopping...", restart_pending=True), RESET_STOPS),
        (controller(CONNECTED, "Connected to OBS."), RESET_DISCONNECTS),
        (
            controller(CONNECTED, "Connected to OBS.", ObsSnapshot(covered=True)),
            RESET_DISCONNECTS,
        ),
    ],
    ids=[
        "never started",
        "stopped after a failure",
        "stopping",
        "connecting",
        "reconnecting",
        "applying settings",
        "connected",
        "covering",
    ],
)
def test_reset_warns_when_it_would_stop_maphide(ctrl, warning):
    assert main_view(ctrl).reset_warning == warning


# The field log's catch-up.


def entries(*messages):
    return [HistoryEntry("t", message) for message in messages]


def test_everything_is_new_the_first_time():
    history = entries("a", "b")

    assert new_entries(history, None) == history


def test_only_entries_after_the_last_shown_are_new():
    history = entries("a", "b", "c")

    assert new_entries(history, history[0]) == history[1:]
    assert new_entries(history, history[-1]) == []


def test_identical_entries_are_told_apart():
    # Two "Overlay shown." lines in the same second are equal as values.
    history = entries("shown", "shown")

    assert new_entries(history, history[0]) == [history[1]]


def test_a_last_shown_entry_that_dropped_off_means_all_are_new():
    history = entries("x", "y")

    assert new_entries(history, HistoryEntry("t", "gone")) == history


# The settings form.


def test_the_form_round_trips_a_config():
    cfg = replace(default_config(), host="10.0.0.2", port=4456, scene_item_name="Overlay")

    values = form_values(cfg)

    assert values["port"] == "4456"
    assert config_from_form(**values) == cfg


# Key capture.


@pytest.mark.parametrize(
    ("key", "shift", "hotkey"),
    [
        (ord("G"), False, "G"),
        (ord("G"), True, "SHIFT+G"),
        (QT_KEY_ESCAPE, False, "ESC"),
        (QT_KEY_SHIFT, False, "SHIFT"),
        (ord("1"), False, None),
        (0x01000004, False, None),  # Return
    ],
)
def test_qt_keys_become_hotkey_names(key, shift, hotkey):
    assert hotkey_from_key(key, shift) == hotkey


@pytest.mark.parametrize(
    ("key", "shift", "result"),
    [
        (ord("M"), False, ("M", None)),
        (ord("M"), True, (None, SHOW_KEY_HELP)),
        (QT_KEY_ESCAPE, False, (None, SHOW_KEY_HELP)),
        (QT_KEY_SHIFT, False, (None, SHOW_KEY_HELP)),
    ],
)
def test_the_show_key_takes_letters_only(key, shift, result):
    assert captured_hotkey(CAPTURE_SHOW, key, shift) == result


@pytest.mark.parametrize(
    ("key", "shift", "result"),
    [
        (ord("H"), False, ("H", None)),
        (ord("H"), True, ("SHIFT+H", None)),
        (QT_KEY_ESCAPE, False, ("ESC", None)),
        (QT_KEY_SHIFT, False, ("SHIFT", None)),
        (ord("5"), False, (None, HIDE_KEY_HELP)),
    ],
)
def test_the_hide_key_also_takes_esc_and_shift(key, shift, result):
    assert captured_hotkey(CAPTURE_HIDE, key, shift) == result


@pytest.mark.parametrize(
    ("hotkey", "label"), [("G", "G"), ("SHIFT+G", "Shift+G"), ("ESC", "Esc"), ("SHIFT", "Shift")]
)
def test_key_caps_read_naturally(hotkey, label):
    assert key_label(hotkey) == label


# The cover source line.


@pytest.mark.parametrize(
    ("count", "text", "warning"),
    [
        (None, SOURCE_UNKNOWN, False),
        (1, f"Found in 1 scene. {SOURCE_FOLLOWS}", False),
        (4, f"Found in 4 scenes. {SOURCE_FOLLOWS}", False),
    ],
)
def test_the_source_line_counts_scenes(count, text, warning):
    assert source_line(count) == (text, warning)


def test_a_source_in_no_scene_is_a_warning():
    text, warning = source_line(0)

    assert text.startswith("Not found in any scene.")
    assert warning
