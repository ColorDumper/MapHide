"""The settings file: its shape, and reading and writing it."""

import json
import os
import shutil
from dataclasses import dataclass, replace

from .hotkeys import (
    HIDE_KEY_HELP,
    HOTKEY_TO_VK,
    SHOW_KEY_HELP,
    hotkey_to_vk_codes,
    is_valid_hide_hotkey,
    is_valid_show_hotkey,
)
from .paths import CONFIG_PATH, LEGACY_CONFIG_PATH
from .themes import DEFAULT_THEME, theme_name

DEFAULT_PORT = 4455
DEFAULT_HOTKEY = "G"
DEFAULT_HIDE_HOTKEY = "H"
DEFAULT_HIDE_DELAY_MS = 120
MIN_HIDE_DELAY_MS = 0
MAX_HIDE_DELAY_MS = 400
MIN_PORT = 1
MAX_PORT = 65535
# Settings only the window uses. Changing these never needs the worker
# restarted, so saving them leaves the OBS connection and the overlay alone.
WINDOW_ONLY_FIELDS = frozenset({"auto_connect", "theme", "check_updates"})


def clamp(value, low, high):
    return max(low, min(high, value))


def _whole_number(value, name):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Config value {name} must be a number.") from exc


def _flag(data, key, default):
    value = data.get(key)
    return default if value is None else bool(value)


@dataclass
class AppConfig:
    host: str
    port: int
    password: str
    scene_item_name: str
    auto_connect: bool = False
    auto_reconnect: bool = True
    hotkey: str = DEFAULT_HOTKEY
    toggle_mode: bool = False
    hide_hotkey: str = DEFAULT_HIDE_HOTKEY
    hide_delay_ms: int = DEFAULT_HIDE_DELAY_MS
    log_enabled: bool = False
    theme: str = DEFAULT_THEME
    check_updates: bool = True

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("The config file must hold a JSON object.")
        required = ("host", "port", "password", "scene_item_name")
        for key in required:
            if key not in data:
                raise KeyError(f"Missing required config key: {key}")
        for key in ("host", "scene_item_name"):
            if data[key] is None:
                raise ValueError(f"Config value {key} must not be empty.")
        hotkey = str(data.get("hotkey", DEFAULT_HOTKEY)).upper()
        hide_hotkey = str(data.get("hide_hotkey", DEFAULT_HIDE_HOTKEY)).upper()
        password = data["password"]
        hide_delay = data.get("hide_delay_ms")
        return cls(
            host=str(data["host"]).strip(),
            port=clamp(_whole_number(data["port"], "port"), MIN_PORT, MAX_PORT),
            password="" if password is None else str(password),
            scene_item_name=str(data["scene_item_name"]).strip(),
            auto_connect=_flag(data, "auto_connect", False),
            auto_reconnect=_flag(data, "auto_reconnect", True),
            hotkey=hotkey if is_valid_show_hotkey(hotkey) else DEFAULT_HOTKEY,
            toggle_mode=_flag(data, "toggle_mode", False),
            hide_hotkey=(
                hide_hotkey if is_valid_hide_hotkey(hide_hotkey) else DEFAULT_HIDE_HOTKEY
            ),
            hide_delay_ms=clamp(
                DEFAULT_HIDE_DELAY_MS
                if hide_delay is None
                else _whole_number(hide_delay, "hide_delay_ms"),
                MIN_HIDE_DELAY_MS,
                MAX_HIDE_DELAY_MS,
            ),
            log_enabled=_flag(data, "log_enabled", False),
            theme=theme_name(data.get("theme") or DEFAULT_THEME),
            check_updates=_flag(data, "check_updates", True),
        )

    def to_dict(self):
        return {
            "host": self.host,
            "port": self.port,
            "password": self.password,
            "scene_item_name": self.scene_item_name,
            "auto_connect": self.auto_connect,
            "auto_reconnect": self.auto_reconnect,
            "hotkey": self.hotkey,
            "toggle_mode": self.toggle_mode,
            "hide_hotkey": self.hide_hotkey,
            "hide_delay_ms": self.hide_delay_ms,
            "log_enabled": self.log_enabled,
            "theme": self.theme,
            "check_updates": self.check_updates,
        }

    def to_loggable_dict(self):
        """Everything except the password and the OBS host/port - the
        password never belongs near the log file, and host/port are
        effectively someone's network address. Safe to put in the debug
        log or anywhere else a user might end up sharing verbatim."""
        excluded = {"password", "host", "port"}
        return {key: value for key, value in self.to_dict().items() if key not in excluded}

    def show_vk_codes(self):
        return hotkey_to_vk_codes(self.hotkey, fallback=[HOTKEY_TO_VK[DEFAULT_HOTKEY]])

    def hide_vk_codes(self):
        return hotkey_to_vk_codes(self.hide_hotkey, fallback=[HOTKEY_TO_VK[DEFAULT_HIDE_HOTKEY]])


def default_config():
    return AppConfig(host="", port=DEFAULT_PORT, password="", scene_item_name="")


def worker_settings_differ(old, new):
    """Whether going from `old` to `new` changes anything the worker uses -
    and so whether a running worker needs restarting to pick it up."""
    old_values, new_values = old.to_dict(), new.to_dict()
    return any(
        old_values[key] != new_values[key] for key in old_values if key not in WINDOW_ONLY_FIELDS
    )


def clamp_hide_delay(value):
    """A hide delay from a slider or text field, as a whole number of
    milliseconds within the allowed range."""
    try:
        delay = int(float(value))
    except (TypeError, ValueError, OverflowError):
        delay = DEFAULT_HIDE_DELAY_MS
    return clamp(delay, MIN_HIDE_DELAY_MS, MAX_HIDE_DELAY_MS)


def form_ready(cfg):
    """`cfg` with anything a settings form can't show replaced by its
    default: an unsupported key name, or a hide delay out of range."""
    return replace(
        cfg,
        hotkey=cfg.hotkey if is_valid_show_hotkey(cfg.hotkey) else DEFAULT_HOTKEY,
        hide_hotkey=(
            cfg.hide_hotkey if is_valid_hide_hotkey(cfg.hide_hotkey) else DEFAULT_HIDE_HOTKEY
        ),
        hide_delay_ms=clamp_hide_delay(cfg.hide_delay_ms),
    )


def connection_from_form(host, port):
    """The OBS host and port from a settings form, as typed: (host, port).

    Raises ValueError with a message fit to show the user when either is
    missing, or the port isn't a number from MIN_PORT to MAX_PORT.
    """
    host = str(host).strip()
    port_text = str(port).strip()
    if not host:
        raise ValueError("OBS Host is required.")
    if not port_text:
        raise ValueError("OBS Port is required.")
    try:
        port_number = int(port_text)
    except ValueError as exc:
        raise ValueError("OBS Port must be a number.") from exc
    if not MIN_PORT <= port_number <= MAX_PORT:
        raise ValueError(f"OBS Port must be between {MIN_PORT} and {MAX_PORT}.")
    return host, port_number


def config_from_form(
    *,
    host,
    port,
    password,
    scene_item_name,
    hotkey,
    toggle_mode,
    hide_hotkey,
    hide_delay_ms,
    auto_connect,
    auto_reconnect,
    log_enabled,
    theme=DEFAULT_THEME,
    check_updates=True,
):
    """Build an AppConfig from what a settings form holds, as typed.

    Raises ValueError with a message fit to show the user when something
    required is missing or a key or number can't be used.
    """
    host, port_number = connection_from_form(host, port)
    scene_item_name = str(scene_item_name).strip()
    hotkey = str(hotkey).strip().upper()
    hide_hotkey = str(hide_hotkey).strip().upper()

    if not scene_item_name:
        raise ValueError("Overlay Source is required.")
    if not is_valid_show_hotkey(hotkey):
        raise ValueError(SHOW_KEY_HELP)
    if toggle_mode and not is_valid_hide_hotkey(hide_hotkey):
        raise ValueError(HIDE_KEY_HELP)

    return AppConfig(
        host=host,
        port=port_number,
        password=password,
        scene_item_name=scene_item_name,
        auto_connect=bool(auto_connect),
        auto_reconnect=bool(auto_reconnect),
        hotkey=hotkey,
        toggle_mode=bool(toggle_mode),
        hide_hotkey=hide_hotkey,
        hide_delay_ms=clamp_hide_delay(hide_delay_ms),
        log_enabled=bool(log_enabled),
        theme=theme_name(theme),
        check_updates=bool(check_updates),
    )


def ensure_config_file(path=CONFIG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    if LEGACY_CONFIG_PATH.exists() and LEGACY_CONFIG_PATH.resolve() != path.resolve():
        shutil.copy2(LEGACY_CONFIG_PATH, path)
        return
    save_config(default_config(), path)


def load_config(path=CONFIG_PATH):
    ensure_config_file(path)
    with open(path, "r", encoding="utf-8") as file:
        return AppConfig.from_dict(json.load(file))


def save_config(cfg, path=CONFIG_PATH):
    """Write `cfg` to a temporary file next to `path`, then swap it in, so a
    crash or power cut mid-save leaves the old settings, never half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(cfg.to_dict(), file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
