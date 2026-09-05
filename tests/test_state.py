"""Tests for the hold/toggle decision, driven by a fake clock and fake keys."""

from datetime import datetime, timedelta

from maphide.config import AppConfig
from maphide.state import HIDE, SHOW, OverlayState, decide

START = datetime(2026, 1, 1, 12, 0, 0)


def at(ms):
    return START + timedelta(milliseconds=ms)


def hold_config(hide_delay_ms=120):
    return AppConfig(
        host="10.0.0.2",
        port=4455,
        password="",
        scene_item_name="Overlay",
        hotkey="G",
        toggle_mode=False,
        hide_hotkey="H",
        hide_delay_ms=hide_delay_ms,
    )


def toggle_config(hotkey="M", hide_hotkey="M", hide_delay_ms=120):
    return AppConfig(
        host="10.0.0.2",
        port=4455,
        password="",
        scene_item_name="Overlay",
        hotkey=hotkey,
        toggle_mode=True,
        hide_hotkey=hide_hotkey,
        hide_delay_ms=hide_delay_ms,
    )


def drive(cfg, polls, overlay_available=True, state=None):
    """Run a list of (ms, show_key_down, hide_key_down) polls through decide.

    Returns the final state and the (ms, action) pairs it asked for.
    """
    same_key = cfg.show_vk_codes() == cfg.hide_vk_codes()
    state = state if state is not None else OverlayState()
    actions = []
    for ms, show_down, hide_down in polls:
        state, action = decide(
            cfg, state, show_down, hide_down, same_key, overlay_available, at(ms)
        )
        if action is not None:
            actions.append((ms, action))
    return state, actions


# --- hold mode ---------------------------------------------------------------


def test_hold_shows_as_soon_as_the_key_goes_down():
    _, actions = drive(hold_config(), [(0, False, False), (10, True, False)])
    assert actions == [(10, SHOW)]


def test_hold_hides_only_after_the_configured_delay():
    _, actions = drive(
        hold_config(hide_delay_ms=120),
        [
            (0, True, False),
            (100, True, False),
            (200, False, False),  # released; the delay starts here
            (250, False, False),
            (319, False, False),  # 119ms later - still too early
            (321, False, False),  # 121ms later
        ],
    )
    assert actions == [(0, SHOW), (321, HIDE)]


def test_hold_repress_inside_the_delay_cancels_the_pending_hide():
    state, actions = drive(
        hold_config(hide_delay_ms=400),
        [
            (0, True, False),
            (100, False, False),  # released, hide pending for t=500
            (200, True, False),  # map reopened before it fired
            (900, True, False),
        ],
    )
    assert actions == [(0, SHOW)]
    assert state.overlay_visible is True
    assert state.hide_requested_at is None


def test_hold_delay_runs_from_the_release_not_from_the_show():
    # A long hold must not shorten the delay: it is measured from the release.
    _, actions = drive(
        hold_config(hide_delay_ms=120),
        [(0, True, False), (5000, True, False), (5100, False, False), (5221, False, False)],
    )
    assert actions == [(0, SHOW), (5221, HIDE)]


# --- the debounce ------------------------------------------------------------


def test_debounce_delays_a_hide_rather_than_dropping_it():
    # With no hide delay the debounce is the only thing holding the hide back,
    # and it must still land once the window passes.
    _, actions = drive(
        hold_config(hide_delay_ms=0),
        [
            (0, True, False),
            (10, False, False),  # 10ms after the show - inside the 50ms debounce
            (40, False, False),
            (60, False, False),
        ],
    )
    assert actions == [(0, SHOW), (60, HIDE)]


def test_debounce_delays_a_show_rather_than_dropping_it():
    _, actions = drive(
        hold_config(hide_delay_ms=0),
        [
            (0, True, False),
            (10, False, False),
            (60, False, False),  # HIDE lands here
            (70, True, False),  # reopened 10ms later, inside the debounce
            (90, True, False),
            (120, True, False),
        ],
    )
    assert actions == [(0, SHOW), (60, HIDE), (120, SHOW)]


# --- toggle mode, one key for both -------------------------------------------


def test_toggle_same_key_alternates_on_each_press():
    _, actions = drive(
        toggle_config(hotkey="M", hide_hotkey="M"),
        [
            (0, False, False),
            (100, True, True),  # press: show
            (200, True, True),  # still held: no second toggle
            (300, False, False),  # release: nothing
            (400, True, True),  # press again: hide
            (530, False, False),  # after the 120ms delay
        ],
    )
    assert actions == [(100, SHOW), (530, HIDE)]


def test_toggle_same_key_holding_the_key_is_a_single_toggle():
    _, actions = drive(
        toggle_config(hotkey="M", hide_hotkey="M"),
        [(0, True, True), (100, True, True), (500, True, True), (900, True, True)],
    )
    assert actions == [(0, SHOW)]


def test_toggle_same_key_releasing_does_not_toggle():
    state, actions = drive(
        toggle_config(hotkey="M", hide_hotkey="M"),
        [(0, True, True), (100, False, False), (200, False, False)],
    )
    assert actions == [(0, SHOW)]
    assert state.desired_visible is True


# --- toggle mode, separate show and hide keys --------------------------------


def test_toggle_separate_keys_show_then_hide():
    _, actions = drive(
        toggle_config(hotkey="M", hide_hotkey="ESC"),
        [
            (0, True, False),  # M shows
            (100, False, False),
            (200, False, True),  # Esc hides
            (330, False, False),
        ],
    )
    assert actions == [(0, SHOW), (330, HIDE)]


def test_toggle_separate_keys_pressing_show_twice_is_idempotent():
    _, actions = drive(
        toggle_config(hotkey="M", hide_hotkey="ESC"),
        [(0, True, False), (100, False, False), (200, True, False), (300, True, False)],
    )
    assert actions == [(0, SHOW)]


def test_toggle_separate_keys_hide_with_nothing_shown_does_nothing():
    _, actions = drive(
        toggle_config(hotkey="M", hide_hotkey="ESC"),
        [(0, False, True), (100, False, False)],
    )
    assert actions == []


def test_toggle_shift_combo_hides_when_both_edges_land_in_one_poll():
    # Shift+M holds M down too, so the show and hide edges fire together.
    # Hiding has to win, or the combo would show instead of hide.
    cfg = toggle_config(hotkey="M", hide_hotkey="SHIFT+M")
    assert cfg.show_vk_codes() != cfg.hide_vk_codes()
    _, actions = drive(
        cfg,
        [
            (0, True, False),  # M alone shows
            (100, False, False),
            (200, True, True),  # Shift+M: both edges at once
            (330, False, False),
        ],
    )
    assert actions == [(0, SHOW), (330, HIDE)]


# --- the source not being in OBS ---------------------------------------------


def test_hold_sends_nothing_while_the_source_is_missing():
    state, actions = drive(
        hold_config(), [(0, True, False), (100, True, False)], overlay_available=False
    )
    assert actions == []
    # Intent still tracks the key, so the overlay is right the moment the
    # source turns up.
    assert state.desired_visible is True


def test_toggle_ignores_presses_while_the_source_is_missing():
    cfg = toggle_config(hotkey="M", hide_hotkey="M")
    state, actions = drive(
        cfg, [(0, True, True), (100, False, False)], overlay_available=False
    )
    assert actions == []
    assert state.desired_visible is False

    # The press was ignored, not queued: it takes a fresh one once the source
    # exists.
    state, actions = drive(cfg, [(200, False, False)], state=state)
    assert actions == []
    state, actions = drive(cfg, [(300, True, True)], state=state)
    assert actions == [(300, SHOW)]


# --- state carried across a dropped connection -------------------------------


def test_intent_survives_a_reconnect_reset():
    # What the worker keeps when the link drops: the intent and what OBS was
    # last told, but nothing about the keys.
    cfg = hold_config()
    state, _ = drive(cfg, [(0, True, False)])
    assert state.desired_visible is True
    assert state.overlay_visible is True

    from dataclasses import replace

    reconnected = replace(
        state, hide_requested_at=None, show_key_was_down=False, hide_key_was_down=False
    )
    assert reconnected.desired_visible is True
    assert reconnected.overlay_visible is True
