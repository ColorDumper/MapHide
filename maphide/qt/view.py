"""What the main screen shows, worked out from the controller.

Plain Python with no Qt, so every rule here is tested without a window.
"""

from dataclasses import dataclass

from ..overlay import CONNECTED, CONNECTING, IDLE, RECONNECTING, STOPPED, STOPPED_MESSAGE

# The four looks of the main screen.
SCREEN_STOPPED = "stopped"
SCREEN_CONNECTING = "connecting"
SCREEN_CONNECTED = "connected"
SCREEN_COVERING = "covering"

STOPPED_HINT = "Start MapHide to link up with OBS."
CONNECTING_HINT = "Looking for OBS on the streaming PC."
COVERING_HINT = "Viewers see the cover, not your map."
APPLYING_HINT = "Applying settings…"
STOPPING_HINT = "Stopping…"
# What a service that has never run, or stopped normally, says about itself.
_QUIET_STOP_MESSAGES = ("Idle", STOPPED_MESSAGE)


@dataclass(frozen=True)
class MainView:
    screen: str
    hint: str
    scene: str
    mode: str
    show_key: str
    toggle_mode: bool
    primary_is_stop: bool
    primary_enabled: bool
    test_enabled: bool


def standby_hint(cfg):
    if cfg.toggle_mode:
        return f"Press {cfg.hotkey} in game to cover the map."
    return f"Hold {cfg.hotkey} in game and the map is covered."


def mode_text(cfg):
    if cfg.toggle_mode:
        return f"TOGGLE · {cfg.hotkey}/{cfg.hide_hotkey}"
    return f"HOLD · {cfg.hotkey}"


def _screen_and_hint(status, snapshot, restart_pending, cfg):
    if restart_pending:
        return SCREEN_CONNECTING, APPLYING_HINT
    if status.state in (IDLE, STOPPED):
        # A stop that came from a failure keeps saying why until the next start.
        if status.message in _QUIET_STOP_MESSAGES:
            return SCREEN_STOPPED, STOPPED_HINT
        return SCREEN_STOPPED, status.message
    if status.state == CONNECTING:
        return SCREEN_CONNECTING, CONNECTING_HINT
    if status.state == RECONNECTING:
        # The worker's own line: why it dropped and the retry countdown.
        return SCREEN_CONNECTING, status.message
    if status.state == CONNECTED:
        if snapshot.covered:
            return SCREEN_COVERING, COVERING_HINT
        return SCREEN_CONNECTED, standby_hint(cfg)
    # Stopping: on its way to offline, and can't be started again yet.
    return SCREEN_STOPPED, STOPPING_HINT


def main_view(controller):
    """The main screen's MainView for the controller's current state."""
    service = controller.service
    cfg = controller.running_config
    screen, hint = _screen_and_hint(
        service.status, controller.snapshot, controller.restart_pending, cfg
    )
    if controller.snapshot.scene:
        scene = controller.snapshot.scene
    else:
        scene = "—" if screen == SCREEN_STOPPED else "…"
    primary_is_stop = screen != SCREEN_STOPPED
    return MainView(
        screen=screen,
        hint=hint,
        scene=scene,
        mode=mode_text(cfg),
        show_key=cfg.hotkey,
        toggle_mode=cfg.toggle_mode,
        primary_is_stop=primary_is_stop,
        primary_enabled=controller.can_stop if primary_is_stop else controller.can_start,
        test_enabled=controller.can_test,
    )


def new_entries(history, last_shown):
    """The entries in `history` after `last_shown` (an entry from an earlier
    look at it), oldest first. The history drops old entries as new ones
    arrive, so this goes by identity, not position. If `last_shown` has
    dropped off the end, everything is new."""
    fresh = []
    for entry in reversed(history):
        if entry is last_shown:
            break
        fresh.append(entry)
    fresh.reverse()
    return fresh


# The settings form's fields, as config_from_form takes them.
FORM_FIELDS = (
    "host",
    "port",
    "password",
    "scene_item_name",
    "hotkey",
    "toggle_mode",
    "hide_hotkey",
    "hide_delay_ms",
    "auto_connect",
    "auto_reconnect",
    "log_enabled",
    "theme",
)


def form_values(cfg):
    """`cfg` as the settings form holds it: the port as text, as typed."""
    values = {field: getattr(cfg, field) for field in FORM_FIELDS}
    values["port"] = str(cfg.port)
    return values
