"""The settings file: its shape, and reading and writing it."""

import json
import shutil
from dataclasses import dataclass

from .hotkeys import (
    HOTKEY_TO_VK,
    hotkey_to_vk_codes,
    is_valid_hide_hotkey,
    is_valid_show_hotkey,
)
from .paths import CONFIG_PATH, LEGACY_CONFIG_PATH

DEFAULT_HIDE_DELAY_MS = 120
MIN_HIDE_DELAY_MS = 0
MAX_HIDE_DELAY_MS = 400
MIN_PORT = 1
MAX_PORT = 65535


def _clamp(value, low, high):
    return max(low, min(high, value))


@dataclass
class AppConfig:
    host: str
    port: int
    password: str
    scene_item_name: str
    auto_connect: bool = False
    hotkey: str = "G"
    toggle_mode: bool = False
    hide_hotkey: str = "H"
    hide_delay_ms: int = DEFAULT_HIDE_DELAY_MS

    @classmethod
    def from_dict(cls, data):
        required = ("host", "port", "password", "scene_item_name")
        for key in required:
            if key not in data:
                raise KeyError(f"Missing required config key: {key}")
        hotkey = str(data.get("hotkey", "G")).upper()
        hide_hotkey = str(data.get("hide_hotkey", "H")).upper()
        return cls(
            host=str(data["host"]).strip(),
            port=_clamp(int(data["port"]), MIN_PORT, MAX_PORT),
            password=str(data.get("password", "")),
            scene_item_name=str(data["scene_item_name"]).strip(),
            auto_connect=bool(data.get("auto_connect", False)),
            hotkey=hotkey if is_valid_show_hotkey(hotkey) else "G",
            toggle_mode=bool(data.get("toggle_mode", False)),
            hide_hotkey=hide_hotkey if is_valid_hide_hotkey(hide_hotkey) else "H",
            hide_delay_ms=_clamp(
                int(data.get("hide_delay_ms", DEFAULT_HIDE_DELAY_MS)),
                MIN_HIDE_DELAY_MS,
                MAX_HIDE_DELAY_MS,
            ),
        )

    def to_dict(self):
        return {
            "host": self.host,
            "port": self.port,
            "password": self.password,
            "scene_item_name": self.scene_item_name,
            "auto_connect": self.auto_connect,
            "hotkey": self.hotkey,
            "toggle_mode": self.toggle_mode,
            "hide_hotkey": self.hide_hotkey,
            "hide_delay_ms": self.hide_delay_ms,
        }

    def show_vk_codes(self):
        return hotkey_to_vk_codes(self.hotkey, fallback=[HOTKEY_TO_VK["G"]])

    def hide_vk_codes(self):
        return hotkey_to_vk_codes(self.hide_hotkey, fallback=[HOTKEY_TO_VK["H"]])


def default_config():
    return AppConfig(
        host="",
        port=4455,
        password="",
        scene_item_name="",
        auto_connect=False,
        hotkey="G",
        toggle_mode=False,
        hide_hotkey="H",
        hide_delay_ms=DEFAULT_HIDE_DELAY_MS,
    )


def ensure_config_file(path=CONFIG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    if LEGACY_CONFIG_PATH.exists() and LEGACY_CONFIG_PATH.resolve() != path.resolve():
        shutil.copy2(LEGACY_CONFIG_PATH, path)
        return
    with open(path, "w", encoding="utf-8") as file:
        json.dump(default_config().to_dict(), file, indent=2)


def load_config(path=CONFIG_PATH):
    ensure_config_file(path)
    with open(path, "r", encoding="utf-8") as file:
        return AppConfig.from_dict(json.load(file))


def save_config(cfg, path=CONFIG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(cfg.to_dict(), file, indent=2)
