"""Deciding what the overlay should be, apart from the talking to OBS.

This is the whole hold/toggle state machine, as a pure function. It reads no
keys and no clock and sends nothing: the caller polls the keyboard, passes in
the time, and carries out whatever action comes back. That is what makes it
testable without OBS or a keyboard.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

DEBOUNCE_MS = 50

SHOW = "show"
HIDE = "hide"


@dataclass(frozen=True)
class OverlayState:
    """What the decision has to remember between one poll and the next."""

    # What the keys say the overlay should be.
    desired_visible: bool = False
    # What OBS was last told, which is not the same thing while a hide is
    # waiting out its delay.
    overlay_visible: bool = False
    last_action_time: datetime = datetime.min
    hide_requested_at: datetime | None = None
    show_key_was_down: bool = False
    hide_key_was_down: bool = False


def decide(cfg, state, show_key_down, hide_key_down, same_key, overlay_available, now):
    """Return the state after this poll, and SHOW, HIDE or None to act on.

    `same_key` says the show and hide keybinds resolve to the same keys, which
    makes the show key alternate rather than only show.
    """
    desired_visible = state.desired_visible
    previous_desired = desired_visible
    show_key_was_down = state.show_key_was_down
    hide_key_was_down = state.hide_key_was_down

    if cfg.toggle_mode:
        show_pressed = show_key_down and not show_key_was_down
        hide_pressed = hide_key_down and not hide_key_was_down
        if overlay_available:
            if same_key:
                if show_pressed:
                    desired_visible = not desired_visible
            else:
                if show_pressed:
                    desired_visible = True
                if hide_pressed:
                    desired_visible = False
        show_key_was_down = show_key_down
        hide_key_was_down = hide_key_down
    else:
        desired_visible = show_key_down

    # The delay exists to cover a map's closing animation, so it runs from the
    # moment the intent changes, not from whenever OBS is told.
    hide_requested_at = state.hide_requested_at
    if desired_visible != previous_desired:
        hide_requested_at = None if desired_visible else now

    action = None
    overlay_visible = state.overlay_visible
    last_action_time = state.last_action_time
    if overlay_available and desired_visible != overlay_visible:
        settled = (now - last_action_time) >= timedelta(milliseconds=DEBOUNCE_MS)
        if desired_visible and settled:
            action = SHOW
            overlay_visible = True
            last_action_time = now
        elif (
            not desired_visible
            and settled
            and hide_requested_at is not None
            and (now - hide_requested_at) >= timedelta(milliseconds=cfg.hide_delay_ms)
        ):
            action = HIDE
            overlay_visible = False
            last_action_time = now

    return (
        replace(
            state,
            desired_visible=desired_visible,
            overlay_visible=overlay_visible,
            last_action_time=last_action_time,
            hide_requested_at=hide_requested_at,
            show_key_was_down=show_key_was_down,
            hide_key_was_down=hide_key_was_down,
        ),
        action,
    )
