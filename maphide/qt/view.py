"""What the main screen shows, worked out from the controller.

Plain Python with no Qt, so every rule here is tested without a window.
"""

from dataclasses import dataclass

from ..hotkeys import HIDE_KEY_HELP, SHOW_KEY_HELP, is_valid_hide_hotkey, is_valid_show_hotkey
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
# Shown once Reset is clicked, while MapHide is running: the defaults have no
# OBS details, so Reset stops it.
RESET_DISCONNECTS = "Reset disconnects MapHide from OBS."
RESET_STOPS = "Reset stops MapHide."
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
    # What Reset would interrupt, or "" when MapHide isn't running.
    reset_warning: str = ""


def _reset_warning(screen):
    if screen in (SCREEN_CONNECTED, SCREEN_COVERING):
        return RESET_DISCONNECTS
    if screen == SCREEN_CONNECTING:
        return RESET_STOPS
    return ""


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
        reset_warning=_reset_warning(screen),
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
    "check_updates",
)


def form_values(cfg):
    """`cfg` as the settings form holds it: the port as text, as typed."""
    values = {field: getattr(cfg, field) for field in FORM_FIELDS}
    values["port"] = str(cfg.port)
    return values


# Key capture. Qt's key codes for the keys MapHide can use: letters are
# their ASCII codes, as in Qt.Key_A to Qt.Key_Z.
QT_KEY_ESCAPE = 0x01000000
QT_KEY_SHIFT = 0x01000020
CAPTURE_SHOW = "show"
CAPTURE_HIDE = "hide"


def hotkey_from_key(key, shift_held):
    """The hotkey name for a Qt key code - "G", "SHIFT+G", "ESC", "SHIFT" -
    or None for a key MapHide can't use."""
    if ord("A") <= key <= ord("Z"):
        letter = chr(key)
        return f"SHIFT+{letter}" if shift_held else letter
    if key == QT_KEY_ESCAPE:
        return "ESC"
    if key == QT_KEY_SHIFT:
        return "SHIFT"
    return None


def captured_hotkey(target, key, shift_held):
    """(hotkey, None) when the key works for `target` (CAPTURE_SHOW or
    CAPTURE_HIDE), else (None, the help to show)."""
    hotkey = hotkey_from_key(key, shift_held)
    if target == CAPTURE_SHOW:
        if hotkey is not None and is_valid_show_hotkey(hotkey):
            return hotkey, None
        return None, SHOW_KEY_HELP
    if hotkey is not None and is_valid_hide_hotkey(hotkey):
        return hotkey, None
    return None, HIDE_KEY_HELP


def key_label(hotkey):
    """A hotkey as its key cap shows it: "Shift+G", "Esc", "G"."""
    return "+".join(part if len(part) == 1 else part.title() for part in hotkey.split("+"))


# The cover source line in Settings.
SOURCE_UNKNOWN = "Test the link to see which scenes carry it."
SOURCE_FOLLOWS = "MapHide follows it whichever scene is live."


def source_line(count):
    """(text, is_warning) for how many scenes carry the cover source, or
    for None when that isn't known yet."""
    if count is None:
        return SOURCE_UNKNOWN, False
    if count == 0:
        return "Not found in any scene. Check the name matches the source in OBS.", True
    scenes = "scene" if count == 1 else "scenes"
    return f"Found in {count} {scenes}. {SOURCE_FOLLOWS}", False
