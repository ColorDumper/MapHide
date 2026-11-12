"""The main screen's rules, checked without Qt."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from maphide.config import config_from_form, default_config
from maphide.controller import HistoryEntry
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
    CONNECTING_HINT,
    COVERING_HINT,
    SCREEN_CONNECTED,
    SCREEN_CONNECTING,
    SCREEN_COVERING,
    SCREEN_STOPPED,
    STOPPED_HINT,
    STOPPING_HINT,
    form_values,
    main_view,
    new_entries,
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
