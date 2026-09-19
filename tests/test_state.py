"""Tests for the hold/toggle decision, driven by a fake clock and fake keys."""

from dataclasses import replace
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
    state, actions = drive(cfg, [(0, True, True), (100, False, False)], overlay_available=False)
    assert actions == []
    assert state.desired_visible is False

    # The press was ignored, not queued: it takes a fresh one once the source
    # exists.
    state, actions = drive(cfg, [(200, False, False)], state=state)
    assert actions == []
    state, actions = drive(cfg, [(300, True, True)], state=state)
    assert actions == [(300, SHOW)]


# --- a press the level check alone would miss --------------------------------


def test_toggle_same_key_registers_a_press_already_released_by_this_poll():
    # Simulates a tap that landed entirely inside a blocked OBS call: by the
    # time this poll runs, show_key_down is already back to False, so only
    # show_key_pressed (from hotkeys.poll_hotkey) carries the edge through.
    cfg = toggle_config(hotkey="M", hide_hotkey="M")
    state, action = decide(
        cfg, OverlayState(), False, False, True, True, at(0), show_key_pressed=True
    )
    assert action == SHOW
    assert state.desired_visible is True


def test_toggle_separate_keys_hide_registers_a_press_already_released_by_this_poll():
    cfg = toggle_config(hotkey="M", hide_hotkey="ESC", hide_delay_ms=0)
    state, action = decide(
        cfg,
        OverlayState(desired_visible=True, overlay_visible=True),
        False,
        False,
        False,
        True,
        at(0),
        hide_key_pressed=True,
    )
    assert action == HIDE
    assert state.desired_visible is False


# --- a "pressed since" flicker while the key is still down must not retoggle -


def test_holding_the_key_does_not_retoggle_even_if_pressed_since_flickers():
    # Confirmed against real hardware: Windows' keyboard auto-repeat
    # re-asserts GetAsyncKeyState's "pressed since last check" bit roughly
    # every 30ms for as long as a key is held, even though it never actually
    # releases in between. show_key_pressed/hide_key_pressed must only be
    # trusted while the key currently reads up - the down-state comparison
    # already handles a genuine fresh press reliably on its own.
    cfg = toggle_config(hotkey="M", hide_hotkey="M")
    state, action = decide(cfg, OverlayState(), True, True, True, True, at(0))
    assert action == SHOW
    assert state.show_key_was_down is True

    # M is still held; show_key_pressed flickers True again via auto-repeat.
    state, action = decide(
        cfg,
        state,
        True,
        True,
        True,
        True,
        at(30),
        show_key_pressed=True,
        hide_key_pressed=True,
    )
    assert action is None
    assert state.desired_visible is True


def test_holding_the_hide_key_does_not_rehide_after_a_later_show_even_if_pressed_since_flickers():
    # H bound as a separate hide key (e.g. a sprint key in-game) is already
    # held and already fully registered - then G shows while H stays held
    # the whole time. A later auto-repeat flicker on H must not re-hide
    # something the user just asked to show; H itself never changed.
    cfg = toggle_config(hotkey="G", hide_hotkey="H")
    state = OverlayState()

    # H starts held - registers correctly, but hiding an already-hidden
    # overlay is a no-op (matches a real key that's just bound this way).
    state, action = decide(cfg, state, False, True, False, True, at(0))
    assert action is None
    assert state.hide_key_was_down is True

    # G is pressed while H stays held the whole time - shows.
    state, action = decide(cfg, state, True, True, False, True, at(10))
    assert action == SHOW
    assert state.desired_visible is True

    # H's auto-repeat flicker fires again, though H was never released.
    state, action = decide(cfg, state, False, True, False, True, at(40), hide_key_pressed=True)
    assert action is None
    assert state.desired_visible is True


# --- state carried across a dropped connection -------------------------------


def test_intent_survives_a_reconnect_reset():
    # What the worker keeps when the link drops: the intent, what OBS was
    # last told, and a hide already counting down - only the key-edge
    # tracking (meaningless after a polling gap) is reset. See overlay.py.
    cfg = hold_config()
    state, _ = drive(cfg, [(0, True, False)])
    assert state.desired_visible is True
    assert state.overlay_visible is True

    reconnected = replace(state, show_key_was_down=False, hide_key_was_down=False)
    assert reconnected.desired_visible is True
    assert reconnected.overlay_visible is True


def test_a_hide_already_pending_at_reconnect_still_lands():
    # Release the key so a hide is armed but not yet fired, then apply the
    # same reset overlay.py runs on every (re)connect. The key never comes
    # back down, so nothing else will ever re-arm the hide - if the reset
    # drops it, it is gone for good and the overlay is stuck showing.
    cfg = hold_config(hide_delay_ms=120)
    state, actions = drive(cfg, [(0, True, False), (100, False, False)])
    assert actions == [(0, SHOW)]
    assert state.overlay_visible is True
    assert state.hide_requested_at is not None  # still counting down at reconnect

    # hide_requested_at survives the reset (see overlay.py) - only the
    # key-edge tracking, which is meaningless after a polling gap, is reset.
    reconnected = replace(state, show_key_was_down=False, hide_key_was_down=False)

    # Real time has already passed the hide delay by the time polling
    # resumes - the hide should land on the very next poll, not be lost.
    _, actions = drive(cfg, [(5000, False, False)], state=reconnected)
    assert actions == [(5000, HIDE)]


def test_a_key_held_through_a_reconnect_does_not_toggle_again():
    # Press and hold M: shows once, and holding it doesn't toggle again
    # while connected - same as
    # test_toggle_same_key_holding_the_key_is_a_single_toggle.
    cfg = toggle_config(hotkey="M", hide_hotkey="M", hide_delay_ms=0)
    state, actions = drive(cfg, [(0, True, True), (100, True, True), (500, True, True)])
    assert actions == [(0, SHOW)]
    assert state.desired_visible is True

    # Reconnect: overlay.py seeds the key-edge tracking from a real poll, not
    # a blind False - M is still genuinely held down at this instant, so a
    # fresh read of the key correctly reports it as already down.
    reconnected = replace(state, show_key_was_down=True, hide_key_was_down=True)

    # M is still held on the very next poll after reconnect - nothing the
    # user did should change what MapHide wants, let alone what it tells OBS.
    state, actions = drive(cfg, [(1000, True, True)], state=reconnected)
    assert state.desired_visible is True
    assert actions == []


def test_holding_the_show_key_through_a_reconnect_is_safe_for_separate_keys():
    # Separate show/hide keys: a phantom "press" of the show key just
    # re-asserts show (it doesn't toggle), so this one is a no-op regardless -
    # included as a contrast to the hide-key case below.
    cfg = toggle_config(hotkey="G", hide_hotkey="H", hide_delay_ms=0)
    state, actions = drive(cfg, [(0, True, False)])
    assert actions == [(0, SHOW)]
    assert state.desired_visible is True

    # G is still held at reconnect; H was never touched.
    reconnected = replace(state, show_key_was_down=True, hide_key_was_down=False)

    state, actions = drive(cfg, [(1000, True, False)], state=reconnected)
    assert state.desired_visible is True
    assert actions == []


def test_holding_the_hide_key_through_a_reconnect_falsely_hides_for_separate_keys():
    # H being held doesn't have to mean the user pressed it to hide - it
    # could be bound to something else entirely (Shift for sprint, say) and
    # just happen to be down at the exact moment of a reconnect. A real poll
    # at that instant correctly reports it as already down, not fresh.
    cfg = toggle_config(hotkey="G", hide_hotkey="H", hide_delay_ms=0)
    state, actions = drive(cfg, [(0, True, False)])
    assert actions == [(0, SHOW)]
    assert state.desired_visible is True

    # G was released before the reconnect; H is genuinely held at this instant.
    reconnected = replace(state, show_key_was_down=False, hide_key_was_down=True)

    state, actions = drive(cfg, [(1000, False, True)], state=reconnected)
    assert state.desired_visible is True
    assert actions == []
