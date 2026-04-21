"""
map_hider.py

Low-resource OBS map hider with two modes:
- GUI mode for simple setup/start/stop control
- Headless mode for the original lightweight workflow

The OBS polling work runs on a background thread so a GUI event loop does not
interfere with the websocket or key polling behavior.
"""

import ctypes
import json
import logging
import os
import queue
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except Exception:
    tk = None
    ttk = None
    messagebox = None

try:
    import pystray
    from PIL import Image, ImageDraw, ImageTk
except Exception:
    pystray = None
    Image = None
    ImageDraw = None
    ImageTk = None

try:
    from obsws_python import ReqClient
except Exception as e:
    print("ERROR: obsws_python not installed or import failed:", e)
    print("Install in your venv: pip install obsws-python")
    sys.exit(1)

logging.getLogger("obsws_python").setLevel(logging.CRITICAL)


APP_DIR = Path(__file__).resolve().parent
APP_NAME = "MapHide"
APP_VERSION = "v0.2.1"
CONFIG_DIR = Path(os.getenv("APPDATA", APP_DIR)) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"
LEGACY_CONFIG_PATH = APP_DIR / "config.json"
ICON_ICO_PATH = APP_DIR / "MapHide.ico"
ICON_RUNTIME_PNG_PATH = APP_DIR / "assets" / "MapHide_Icon.png"
ICON_WINDOW_PNG_PATH = APP_DIR / "assets" / "MapHide_Icon_32.png"
ICON_TRAY_PNG_PATH = APP_DIR / "assets" / "MapHide_Icon_64.png"
ICON_PNG_PATH = APP_DIR / "MapHide_Master.png"
WATERMARK_PNG_PATH = APP_DIR / "PaintTwo.png"
APP_USER_MODEL_ID = "MapHide.App"
TOGGLE_KEY_VK = 0x47
POLL_INTERVAL = 0.005
DEBOUNCE_MS = 50
DEFAULT_HIDE_DELAY_MS = 120
MIN_HIDE_DELAY_MS = 0
MAX_HIDE_DELAY_MS = 400
KEY_BUTTON_WIDTH = 16
STATUS_AREA_WIDTH = 300
STATUS_AREA_HEIGHT = 72
HELP_AREA_WIDTH = 340
HELP_AREA_HEIGHT = 44
WINDOW_EXTRA_WIDTH = 32
WINDOW_EXTRA_HEIGHT = 56
WATERMARK_MAX_SIZE = (64, 40)
SCENE_REFRESH_INTERVAL = 0.25
RECONNECT_DELAY = 2.0
SHOW_KEY_HELP = "Show key supports A-Z."
HIDE_KEY_HELP = "Hide key supports A-Z, Shift, or Shift+A-Z."
WINDOW_TITLE = "MapHide"
COLOR_BG = "#12161d"
COLOR_PANEL = "#1b2330"
COLOR_PANEL_ALT = "#222c3b"
COLOR_BORDER = "#2d3748"
COLOR_TEXT = "#e6edf7"
COLOR_MUTED = "#9fb0c7"
COLOR_ACCENT = "#4da3ff"
COLOR_ACCENT_ACTIVE = "#78b8ff"
COLOR_INPUT = "#111923"
COLOR_DISABLED = "#5a6472"
HOTKEY_OPTIONS = [
    *[(chr(code), code) for code in range(ord("A"), ord("Z") + 1)],
    ("SHIFT", 0x10),
]
HOTKEY_TO_VK = dict(HOTKEY_OPTIONS)
SHOW_KEY_LABELS = tuple(chr(code) for code in range(ord("A"), ord("Z") + 1))
MODIFIER_LABELS = ("SHIFT",)
MODIFIER_KEYSYMS = {
    "SHIFT_L": "SHIFT",
    "SHIFT_R": "SHIFT",
}
EVENT_STATE_MODIFIERS = (
    ("SHIFT", 0x0001),
)


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
        return cls(
            host=str(data["host"]).strip(),
            port=int(data["port"]),
            password=str(data.get("password", "")),
            scene_item_name=str(data["scene_item_name"]).strip(),
            auto_connect=bool(data.get("auto_connect", False)),
            hotkey=str(data.get("hotkey", "G")).upper(),
            toggle_mode=bool(data.get("toggle_mode", False)),
            hide_hotkey=str(data.get("hide_hotkey", "H")).upper(),
            hide_delay_ms=int(data.get("hide_delay_ms", DEFAULT_HIDE_DELAY_MS)),
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

    def hotkey_vk_code(self):
        return hotkey_to_vk_codes(self.hotkey, fallback=[TOGGLE_KEY_VK])

    def hide_hotkey_vk_code(self):
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


def describe_obs_connection_error(exc):
    message = str(exc).lower()
    auth_markers = ("auth", "authentication", "password", "identify", "4009")
    connection_markers = (
        "connection refused",
        "actively refused",
        "timed out",
        "timeout",
        "10061",
        "10060",
        "network name is no longer available",
    )

    if any(marker in message for marker in auth_markers):
        return "Failed to connect to OBS. The OBS WebSocket password appears to be incorrect."
    if any(marker in message for marker in connection_markers):
        return "Failed to connect to OBS. Make sure OBS is open and the WebSocket server is available."
    return "Failed to connect to OBS. Check that OBS is open and your connection settings are correct."


def is_auth_error_message(message):
    normalized = message.lower()
    return "password appears to be incorrect" in normalized or "password is incorrect" in normalized


def describe_obs_request_error(exc):
    message = str(exc).lower()
    connection_markers = (
        "connection refused",
        "actively refused",
        "timed out",
        "timeout",
        "10061",
        "10060",
        "closed",
        "reset by peer",
    )
    if any(marker in message for marker in connection_markers):
        return "The connection to OBS was lost. Reconnect after OBS is available again."
    return "OBS returned an error while reading the current scene."


def connect_obs(host, port, password, timeout=3):
    try:
        client = ReqClient(host=host, port=port, password=password, timeout=timeout)
        try:
            client.get_version()
        except Exception:
            pass
        return client
    except Exception as exc:
        raise ConnectionError(describe_obs_connection_error(exc)) from exc


def find_scene_item_id_raw(client, scene_name, source_name):
    try:
        resp = client.send("GetSceneItemList", {"sceneName": scene_name}, raw=True)
    except Exception as exc:
        raise RuntimeError(describe_obs_request_error(exc)) from exc

    items = resp.get("sceneItems") or resp.get("scene_items") or []
    for item in items:
        name = item.get("sourceName") or item.get("source_name")
        item_id = item.get("sceneItemId") or item.get("scene_item_id")
        if name == source_name:
            return item_id
    return None


def get_current_program_scene_raw(client):
    try:
        resp = client.send("GetCurrentProgramScene", raw=True)
    except Exception as exc:
        raise RuntimeError(describe_obs_request_error(exc)) from exc
    return resp.get("currentProgramSceneName") or resp.get("current_program_scene_name")


def set_scene_item_enabled_raw(client, scene_name, scene_item_id, enabled):
    payload = {
        "sceneName": scene_name,
        "sceneItemId": scene_item_id,
        "sceneItemEnabled": bool(enabled),
    }
    return client.send("SetSceneItemEnabled", payload, raw=True)


def normalize_hotkey_label(value):
    label = str(value).strip().upper()
    return label


def hotkey_to_vk_codes(hotkey, fallback=None):
    labels = [normalize_hotkey_label(part) for part in str(hotkey).split("+") if part.strip()]
    codes = []
    for label in labels:
        code = HOTKEY_TO_VK.get(label)
        if code is None:
            return fallback or []
        if code not in codes:
            codes.append(code)
    return codes or (fallback or [])


def hotkey_labels(hotkey):
    return [normalize_hotkey_label(part) for part in str(hotkey).split("+") if part.strip()]


def is_valid_hide_hotkey(hotkey):
    labels = hotkey_labels(hotkey)
    if len(labels) == 1:
        return labels[0] in SHOW_KEY_LABELS or labels[0] == "SHIFT"
    if len(labels) == 2:
        return labels[0] == "SHIFT" and labels[1] in SHOW_KEY_LABELS
    return False


def is_valid_show_hotkey(hotkey):
    labels = hotkey_labels(hotkey)
    return len(labels) == 1 and labels[0] in SHOW_KEY_LABELS


def normalize_event_key(keysym):
    key = str(keysym).strip().upper()
    if key in MODIFIER_KEYSYMS:
        return MODIFIER_KEYSYMS[key]
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return key if key in SHOW_KEY_LABELS else None
    return None


def is_key_down(vk_code):
    state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
    return (state & 0x8000) != 0


def is_hotkey_down(vk_codes):
    return bool(vk_codes) and all(is_key_down(code) for code in vk_codes)


def human_ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def set_windows_app_id():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


class MapHideService:
    def __init__(
        self,
        show_vk_codes=None,
        show_hotkey_label="G",
        toggle_mode=False,
        hide_vk_codes=None,
        hide_hotkey_label="H",
    ):
        self.show_vk_codes = show_vk_codes or [TOGGLE_KEY_VK]
        self.show_hotkey_label = show_hotkey_label
        self.toggle_mode = toggle_mode
        self.hide_vk_codes = hide_vk_codes or [HOTKEY_TO_VK["H"]]
        self.hide_hotkey_label = hide_hotkey_label
        self._thread = None
        self._stop_event = threading.Event()
        self._events = queue.Queue()
        self._running = False

    @property
    def events(self):
        return self._events

    @property
    def is_running(self):
        return self._running

    def start(self, cfg):
        if self._running:
            raise RuntimeError("Service is already running.")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(cfg,),
            name="MapHideWorker",
            daemon=True,
        )
        self._running = True
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def wait(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _emit(self, kind, message, **extra):
        self._events.put(
            {
                "kind": kind,
                "message": message,
                "timestamp": human_ts(),
                **extra,
            }
        )

    def _run(self, cfg):
        client = None
        overlay_visible = False
        item_id = None
        active_scene_name = None
        last_action_time = datetime.min
        hide_requested_at = None
        last_scene_refresh = datetime.min
        announced_connection_failure = False
        final_status_message = "MapHide stopped."
        had_successful_connection = False
        show_key_was_down = False
        hide_key_was_down = False

        try:
            while not self._stop_event.is_set():
                if client is None:
                    try:
                        self._emit("status", "Connecting to OBS...")
                        client = connect_obs(cfg.host, cfg.port, cfg.password)
                        overlay_visible = False
                        item_id = None
                        active_scene_name = None
                        last_scene_refresh = datetime.min
                        hide_requested_at = None
                        show_key_was_down = False
                        hide_key_was_down = False
                        announced_connection_failure = False
                        had_successful_connection = True
                        self._emit("status", "Connected to OBS.")
                    except Exception as exc:
                        error_message = str(exc)
                        if not announced_connection_failure:
                            self._emit("error", error_message)
                            announced_connection_failure = True
                        if is_auth_error_message(error_message) or not had_successful_connection:
                            final_status_message = error_message
                            break
                        time.sleep(RECONNECT_DELAY)
                        continue

                now = datetime.now()
                try:
                    if (now - last_scene_refresh) >= timedelta(seconds=SCENE_REFRESH_INTERVAL):
                        latest_scene_name = get_current_program_scene_raw(client)
                        if latest_scene_name != active_scene_name:
                            active_scene_name = latest_scene_name
                            item_id = find_scene_item_id_raw(client, active_scene_name, cfg.scene_item_name)
                            overlay_visible = False
                            hide_requested_at = None
                            if item_id is None:
                                self._emit(
                                    "status",
                                    f"Scene: {active_scene_name}. "
                                    f"Source '{cfg.scene_item_name}' not found.",
                                )
                            else:
                                if self.toggle_mode:
                                    status_message = (
                                        f"Scene: {active_scene_name}. "
                                        f"{self.show_hotkey_label} shows '{cfg.scene_item_name}', "
                                        f"{self.hide_hotkey_label} hides it."
                                    )
                                else:
                                    status_message = (
                                        f"Scene: {active_scene_name}. "
                                        f"Hold {self.show_hotkey_label} for '{cfg.scene_item_name}'."
                                    )
                                self._emit(
                                    "status",
                                    status_message,
                                    scene_item_id=item_id,
                                )
                        last_scene_refresh = now

                    show_key_down = is_hotkey_down(self.show_vk_codes)

                    if self.toggle_mode:
                        hide_key_down = is_hotkey_down(self.hide_vk_codes)
                        same_key_toggle = self.show_vk_codes == self.hide_vk_codes

                        if same_key_toggle:
                            if show_key_down and not show_key_was_down and item_id is not None:
                                if overlay_visible:
                                    hide_requested_at = now
                                else:
                                    hide_requested_at = None
                                    if (now - last_action_time) >= timedelta(milliseconds=DEBOUNCE_MS):
                                        set_scene_item_enabled_raw(client, active_scene_name, item_id, True)
                                        overlay_visible = True
                                        last_action_time = now
                                        self._emit("overlay", "Overlay shown.", visible=True)
                        elif show_key_down and not show_key_was_down and item_id is not None:
                            hide_requested_at = None
                            if (
                                not overlay_visible
                                and (now - last_action_time) >= timedelta(milliseconds=DEBOUNCE_MS)
                            ):
                                set_scene_item_enabled_raw(client, active_scene_name, item_id, True)
                                overlay_visible = True
                                last_action_time = now
                                self._emit("overlay", "Overlay shown.", visible=True)

                        if (
                            not same_key_toggle
                            and hide_key_down
                            and not hide_key_was_down
                            and overlay_visible
                            and item_id is not None
                        ):
                            hide_requested_at = now

                        if (
                            hide_requested_at is not None
                            and overlay_visible
                            and item_id is not None
                            and (now - hide_requested_at) >= timedelta(milliseconds=cfg.hide_delay_ms)
                            and (now - last_action_time) >= timedelta(milliseconds=DEBOUNCE_MS)
                        ):
                            set_scene_item_enabled_raw(client, active_scene_name, item_id, False)
                            overlay_visible = False
                            hide_requested_at = None
                            last_action_time = now
                            self._emit("overlay", "Overlay hidden.", visible=False)

                        show_key_was_down = show_key_down
                        hide_key_was_down = hide_key_down
                    else:
                        if show_key_down and not overlay_visible and item_id is not None:
                            hide_requested_at = None
                            if (now - last_action_time) >= timedelta(milliseconds=DEBOUNCE_MS):
                                set_scene_item_enabled_raw(client, active_scene_name, item_id, True)
                                overlay_visible = True
                                last_action_time = now
                                self._emit("overlay", "Overlay shown.", visible=True)

                        elif not show_key_down and overlay_visible and item_id is not None:
                            if hide_requested_at is None:
                                hide_requested_at = now
                            if (
                                (now - hide_requested_at) >= timedelta(milliseconds=cfg.hide_delay_ms)
                                and (now - last_action_time) >= timedelta(milliseconds=DEBOUNCE_MS)
                            ):
                                set_scene_item_enabled_raw(client, active_scene_name, item_id, False)
                                overlay_visible = False
                                hide_requested_at = None
                                last_action_time = now
                                self._emit("overlay", "Overlay hidden.", visible=False)
                        else:
                            hide_requested_at = None

                    time.sleep(POLL_INTERVAL)
                except Exception as exc:
                    self._emit("error", str(exc))
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                    client = None
                    overlay_visible = False
                    item_id = None
                    active_scene_name = None
                    hide_requested_at = None
                    show_key_was_down = False
                    hide_key_was_down = False
                    time.sleep(RECONNECT_DELAY)
        finally:
            if client is not None and item_id is not None and active_scene_name is not None:
                try:
                    set_scene_item_enabled_raw(client, active_scene_name, item_id, False)
                except Exception:
                    pass
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass

            self._running = False
            self._emit("stopped", final_status_message)


class MapHideApp:
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.resizable(False, False)
        self.service = MapHideService()
        self.tray_icon = None
        self.tray_thread = None
        self.exit_requested = False
        self.is_hidden_to_tray = False
        self.settings_visible = False
        self.restart_pending = False
        self.pending_restart_config = None
        self.restart_service_ref = None
        self.reset_confirm_pending = False
        self.collapsed_width = 0
        self.expanded_width = 0
        self.window_height = 0

        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.item_var = tk.StringVar()
        self.hotkey_var = tk.StringVar(value="G")
        self.hide_hotkey_var = tk.StringVar(value="H")
        self.toggle_mode_var = tk.BooleanVar(value=False)
        self.hotkey_label_var = tk.StringVar(value="Hotkey")
        self.hide_delay_var = tk.IntVar(value=DEFAULT_HIDE_DELAY_MS)
        self.hide_delay_label_var = tk.StringVar(value=f"{DEFAULT_HIDE_DELAY_MS} ms")
        self.show_host_var = tk.BooleanVar(value=False)
        self.show_port_var = tk.BooleanVar(value=False)
        self.show_password_var = tk.BooleanVar(value=False)
        self.auto_connect_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle")
        self.help_text_var = tk.StringVar(value="Hold G to show the overlay. Release G to hide it.")
        self.active_hotkey_label = "G"
        self.active_hide_hotkey_label = "H"
        self.active_toggle_mode = False
        self.key_capture_target = None

        self._configure_styles()
        self._build_ui()
        self._apply_window_background()
        self._apply_window_icon()
        self._apply_footer_watermark()
        self._load_initial_config()
        self._measure_window_sizes()
        self._apply_window_size(self.collapsed_width)
        self.root.bind_all("<Button-1>", self._handle_global_click, add="+")
        self.root.bind_all("<KeyPress>", self._handle_key_capture_press, add="+")
        self.root.bind_all("<KeyRelease>", self._handle_key_capture_release, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._setup_tray()
        self.root.after(100, self._drain_events)

    def _configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.root.configure(bg=COLOR_BG)

        style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("TFrame", background=COLOR_BG)
        style.configure("Header.TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI Semibold", 11))
        style.configure("Version.TLabel", background=COLOR_BG, foreground=COLOR_MUTED, font=("Segoe UI", 9))
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("Muted.TLabel", background=COLOR_PANEL, foreground=COLOR_MUTED)
        style.configure(
            "TLabelFrame",
            background=COLOR_BG,
            foreground=COLOR_TEXT,
            bordercolor=COLOR_BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure("TLabelFrame.Label", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure(
            "TButton",
            background=COLOR_PANEL_ALT,
            foreground=COLOR_TEXT,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_PANEL_ALT,
            darkcolor=COLOR_PANEL_ALT,
            padding=(10, 6),
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", COLOR_ACCENT), ("pressed", COLOR_ACCENT_ACTIVE), ("disabled", COLOR_PANEL_ALT)],
            foreground=[("disabled", COLOR_DISABLED)],
            bordercolor=[("active", COLOR_ACCENT)],
        )
        style.configure(
            "TEntry",
            fieldbackground=COLOR_INPUT,
            foreground=COLOR_TEXT,
            insertcolor=COLOR_TEXT,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
            padding=6,
        )
        style.map("TEntry", fieldbackground=[("disabled", COLOR_PANEL_ALT)])
        style.configure(
            "TCheckbutton",
            background=COLOR_PANEL,
            foreground=COLOR_TEXT,
            indicatorbackground=COLOR_INPUT,
            indicatorforeground=COLOR_TEXT,
            indicatormargin=4,
        )
        style.map(
            "TCheckbutton",
            background=[("active", COLOR_PANEL)],
            foreground=[("disabled", COLOR_DISABLED)],
            indicatorbackground=[("selected", COLOR_ACCENT), ("active", COLOR_INPUT)],
        )
        style.configure(
            "Horizontal.TScale",
            background=COLOR_BG,
            troughcolor=COLOR_INPUT,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
        )
        style.map("Horizontal.TScale", background=[("active", COLOR_PANEL_ALT)])

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=0)
        frame.columnconfigure(1, weight=0)
        self.main_frame = frame

        left_panel = ttk.Frame(frame)
        left_panel.grid(row=0, column=0, sticky="n")
        left_panel.columnconfigure(0, weight=1)

        header_row = ttk.Frame(left_panel)
        header_row.grid(row=0, column=0, sticky="ew")
        header_row.columnconfigure(0, weight=1)

        title_row = ttk.Frame(header_row)
        title_row.grid(row=0, column=0, sticky="w")

        ttk.Label(title_row, text="MapHide", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(title_row, text=APP_VERSION, style="Version.TLabel").grid(
            row=0,
            column=1,
            sticky="sw",
            padx=(6, 0),
            pady=(0, 1),
        )
        self.settings_button = ttk.Button(header_row, text="Settings >", command=self.toggle_settings_panel)
        self.settings_button.grid(row=0, column=1, sticky="e")

        controls_frame = ttk.LabelFrame(left_panel, text="Controls", padding=12)
        controls_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        controls_frame.columnconfigure(1, weight=1)

        button_row = ttk.Frame(controls_frame)
        button_row.grid(row=0, column=0, columnspan=2, sticky="w")

        self.start_button = ttk.Button(button_row, text="Start", command=self.start_service)
        self.start_button.grid(row=0, column=0, padx=(0, 8))

        self.stop_button = ttk.Button(button_row, text="Stop", command=self.stop_service, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=(0, 8))

        ttk.Checkbutton(
            controls_frame,
            text="Auto connect on startup",
            variable=self.auto_connect_var,
            command=self.save_form_config,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 2))

        ttk.Label(controls_frame, text="Status").grid(row=2, column=0, sticky="nw", pady=(8, 2), padx=(0, 10))
        status_area = tk.Frame(
            controls_frame,
            width=STATUS_AREA_WIDTH,
            height=STATUS_AREA_HEIGHT,
            bg=COLOR_BG,
            highlightthickness=0,
        )
        status_area.grid(
            row=2,
            column=1,
            sticky="nw",
            pady=(8, 6),
        )
        status_area.grid_propagate(False)
        self.status_label = ttk.Label(
            status_area,
            textvariable=self.status_var,
            justify="left",
            wraplength=STATUS_AREA_WIDTH - 8,
        )
        self.status_label.place(x=0, y=0, width=STATUS_AREA_WIDTH, height=STATUS_AREA_HEIGHT)

        help_area = tk.Frame(
            controls_frame,
            width=HELP_AREA_WIDTH,
            height=HELP_AREA_HEIGHT,
            bg=COLOR_PANEL,
            highlightthickness=0,
        )
        help_area.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        help_area.grid_propagate(False)
        self.help_label = ttk.Label(
            help_area,
            textvariable=self.help_text_var,
            style="Muted.TLabel",
            wraplength=HELP_AREA_WIDTH - 8,
            justify="left",
        )
        self.help_label.place(x=0, y=0, width=HELP_AREA_WIDTH, height=HELP_AREA_HEIGHT)

        self.footer_brand = ttk.Label(left_panel, text="Color Dumper • 2026", style="Version.TLabel")
        self.footer_brand.grid(
            row=2,
            column=0,
            sticky="e",
            pady=(10, 0),
        )

        self.settings_panel = ttk.Frame(frame, padding=(14, 0, 0, 0))
        self.settings_panel.grid(row=0, column=1, sticky="n")
        self.settings_panel.grid_remove()
        self.settings_panel.columnconfigure(0, weight=1)

        source_frame = ttk.LabelFrame(self.settings_panel, text="Overlay Source", padding=12)
        source_frame.grid(row=0, column=0, sticky="ew")
        source_frame.columnconfigure(1, weight=1)

        ttk.Label(source_frame, text="Source Name").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Entry(source_frame, textvariable=self.item_var, width=34).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(
            source_frame,
            text="Enter the exact OBS source name. MapHide will follow that source name across scenes.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        obs_frame = ttk.LabelFrame(self.settings_panel, text="OBS Config", padding=12)
        obs_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        obs_frame.columnconfigure(1, weight=1)

        ttk.Label(obs_frame, text="Host").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 10))
        self.host_entry = ttk.Entry(obs_frame, textvariable=self.host_var, width=34)
        self.host_entry.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Checkbutton(
            obs_frame,
            text="Show",
            variable=self.show_host_var,
            command=self._update_sensitive_visibility,
        ).grid(row=0, column=2, sticky="w", padx=(10, 0))

        ttk.Label(obs_frame, text="Port").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 10))
        self.port_entry = ttk.Entry(obs_frame, textvariable=self.port_var, width=34)
        self.port_entry.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Checkbutton(
            obs_frame,
            text="Show",
            variable=self.show_port_var,
            command=self._update_sensitive_visibility,
        ).grid(row=1, column=2, sticky="w", padx=(10, 0))

        ttk.Label(obs_frame, text="Password").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 10))
        self.password_entry = ttk.Entry(obs_frame, textvariable=self.password_var, width=34, show="*")
        self.password_entry.grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Checkbutton(
            obs_frame,
            text="Show",
            variable=self.show_password_var,
            command=self._update_sensitive_visibility,
        ).grid(row=2, column=2, sticky="w", padx=(10, 0))

        self.hotkey_label = ttk.Label(obs_frame, textvariable=self.hotkey_label_var)
        self.hotkey_label.grid(row=3, column=0, sticky="w", pady=4, padx=(0, 10))

        hotkey_controls = ttk.Frame(obs_frame)
        hotkey_controls.grid(row=3, column=1, columnspan=2, sticky="w", pady=4)

        self.hotkey_button = ttk.Button(
            hotkey_controls,
            text=self.hotkey_var.get(),
            width=KEY_BUTTON_WIDTH,
            command=lambda: self._start_key_capture("show"),
        )
        self.hotkey_button.grid(row=0, column=0, sticky="w")

        self.hide_hotkey_label = ttk.Label(hotkey_controls, text="Hide key")
        self.hide_hotkey_button = ttk.Button(
            hotkey_controls,
            text=self.hide_hotkey_var.get(),
            width=KEY_BUTTON_WIDTH,
            command=lambda: self._start_key_capture("hide"),
        )
        self.hide_hotkey_label.grid(row=0, column=1, sticky="w", padx=(8, 6))
        self.hide_hotkey_button.grid(row=0, column=2, sticky="w")

        self.toggle_mode_check = ttk.Checkbutton(
            hotkey_controls,
            text="Toggle mode",
            variable=self.toggle_mode_var,
            command=self._update_toggle_mode_ui,
        )
        self.toggle_mode_check.grid(row=0, column=3, sticky="w", padx=(8, 0))

        ttk.Label(obs_frame, text="Hide delay").grid(row=4, column=0, sticky="w", pady=4, padx=(0, 10))
        hide_delay_frame = ttk.Frame(obs_frame)
        hide_delay_frame.grid(row=4, column=1, columnspan=2, sticky="ew", pady=4)
        hide_delay_frame.columnconfigure(0, weight=1)

        self.hide_delay_scale = ttk.Scale(
            hide_delay_frame,
            from_=MIN_HIDE_DELAY_MS,
            to=MAX_HIDE_DELAY_MS,
            variable=self.hide_delay_var,
            command=self._on_hide_delay_changed,
        )
        self.hide_delay_scale.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            hide_delay_frame,
            textvariable=self.hide_delay_label_var,
            style="Muted.TLabel",
            width=7,
        ).grid(row=0, column=1, sticky="e", padx=(10, 0))

        ttk.Label(
            self.settings_panel,
            text="Changes apply after you click Save Settings.",
            style="Muted.TLabel",
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=(10, 0),
        )

        ttk.Button(self.settings_panel, text="Save Settings", command=self.save_form_config).grid(
            row=3,
            column=0,
            sticky="e",
            pady=(10, 0),
        )

        ttk.Button(self.settings_panel, text="Reset Defaults", command=self.reset_defaults).grid(
            row=4,
            column=0,
            sticky="e",
            pady=(8, 0),
        )

        self._update_sensitive_visibility()
        self._update_toggle_mode_ui()
        self._sync_key_buttons()

    def _apply_window_background(self):
        if not hasattr(self, "main_frame"):
            return
        try:
            bg = ttk.Style().lookup("TFrame", "background")
            if bg:
                self.root.configure(bg=bg)
        except Exception:
            pass

    def _apply_window_icon(self):
        try:
            if ICON_ICO_PATH.exists():
                self.root.iconbitmap(default=str(ICON_ICO_PATH))
        except Exception:
            pass
        try:
            if ICON_WINDOW_PNG_PATH.exists():
                icon_photo_path = ICON_WINDOW_PNG_PATH
            elif ICON_RUNTIME_PNG_PATH.exists():
                icon_photo_path = ICON_RUNTIME_PNG_PATH
            else:
                icon_photo_path = ICON_PNG_PATH
            if icon_photo_path.exists():
                self.window_icon_image = tk.PhotoImage(file=str(icon_photo_path))
                self.root.iconphoto(True, self.window_icon_image)
        except Exception:
            pass

    def _apply_footer_watermark(self):
        if not hasattr(self, "footer_brand"):
            return
        if Image is None or ImageTk is None or not WATERMARK_PNG_PATH.exists():
            return
        try:
            watermark = Image.open(WATERMARK_PNG_PATH).convert("RGBA")
            visible_bounds = watermark.getbbox()
            if visible_bounds is not None:
                watermark = watermark.crop(visible_bounds)
            watermark.thumbnail(WATERMARK_MAX_SIZE, Image.Resampling.LANCZOS)
            self.footer_brand_image = ImageTk.PhotoImage(watermark)
            self.footer_brand.configure(image=self.footer_brand_image, text="")
        except Exception:
            pass

    def _measure_window_sizes(self):
        self.settings_panel.grid_remove()
        self.root.update_idletasks()
        self.collapsed_width = self.root.winfo_reqwidth()
        self.window_height = self.root.winfo_reqheight()

        original_toggle_mode = self.toggle_mode_var.get()
        original_hotkey = self.hotkey_var.get()
        original_hide_hotkey = self.hide_hotkey_var.get()
        original_capture_target = self.key_capture_target

        self.key_capture_target = None
        self.toggle_mode_var.set(True)
        self.hotkey_var.set("Press key...")
        self.hide_hotkey_var.set("SHIFT+Z")
        self._update_toggle_mode_ui()

        self.settings_panel.grid()
        self.root.update_idletasks()
        self.expanded_width = self.root.winfo_reqwidth() + WINDOW_EXTRA_WIDTH
        self.window_height = max(self.window_height, self.root.winfo_reqheight()) + WINDOW_EXTRA_HEIGHT

        self.settings_panel.grid_remove()

        self.toggle_mode_var.set(original_toggle_mode)
        self.hotkey_var.set(original_hotkey)
        self.hide_hotkey_var.set(original_hide_hotkey)
        self.key_capture_target = original_capture_target
        self._update_toggle_mode_ui()

    def _default_form_config(self):
        return default_config()

    def _load_initial_config(self):
        try:
            cfg = load_config()
        except Exception:
            cfg = default_config()
            self.status_var.set("Config not loaded. Fill in values and save settings.")
        self._set_form(cfg)
        if cfg.auto_connect:
            self.root.after(250, self.start_service)

    def _set_form(self, cfg):
        self.host_var.set(cfg.host)
        self.port_var.set(str(cfg.port))
        self.password_var.set(cfg.password)
        self.item_var.set(cfg.scene_item_name)
        self.auto_connect_var.set(cfg.auto_connect)
        self.hotkey_var.set(cfg.hotkey if is_valid_show_hotkey(cfg.hotkey) else "G")
        self.toggle_mode_var.set(cfg.toggle_mode)
        self.hide_hotkey_var.set(cfg.hide_hotkey if is_valid_hide_hotkey(cfg.hide_hotkey) else "H")
        self.hide_delay_var.set(self._clamp_hide_delay(cfg.hide_delay_ms))
        self._update_hide_delay_label()
        self.active_hotkey_label = self.hotkey_var.get().strip().upper() or "G"
        self.active_hide_hotkey_label = self.hide_hotkey_var.get().strip().upper() or "H"
        self.active_toggle_mode = cfg.toggle_mode
        self._update_toggle_mode_ui()
        self._sync_key_buttons()
        self._update_help_text()

    def _read_form(self):
        host = self.host_var.get().strip()
        port_text = self.port_var.get().strip()
        password = self.password_var.get()
        scene_item_name = self.item_var.get().strip()
        hotkey = self.hotkey_var.get().strip().upper()
        toggle_mode = self.toggle_mode_var.get()
        hide_hotkey = self.hide_hotkey_var.get().strip().upper()
        hide_delay_ms = self._clamp_hide_delay(self.hide_delay_var.get())

        if not host:
            raise ValueError("OBS Host is required.")
        if not port_text:
            raise ValueError("OBS Port is required.")
        if not scene_item_name:
            raise ValueError("Overlay Source is required.")
        if not is_valid_show_hotkey(hotkey):
            raise ValueError(SHOW_KEY_HELP)
        if toggle_mode:
            if not is_valid_hide_hotkey(hide_hotkey):
                raise ValueError(HIDE_KEY_HELP)

        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError("OBS Port must be a number.") from exc

        return AppConfig(
            host=host,
            port=port,
            password=password,
            scene_item_name=scene_item_name,
            auto_connect=self.auto_connect_var.get(),
            hotkey=hotkey,
            toggle_mode=toggle_mode,
            hide_hotkey=hide_hotkey,
            hide_delay_ms=hide_delay_ms,
        )

    def save_form_config(self):
        self.reset_confirm_pending = False
        try:
            cfg = self._read_form()
            save_config(cfg)
        except ValueError as exc:
            self.status_var.set(str(exc))
            return
        except Exception as exc:
            self._show_error("Could not save config", str(exc))
            return
        self.active_hotkey_label = cfg.hotkey
        self.active_hide_hotkey_label = cfg.hide_hotkey
        self.active_toggle_mode = cfg.toggle_mode
        self._update_help_text()
        if self.service.is_running:
            self._restart_service_with_config(cfg)
            self.status_var.set("Config saved. Restarting MapHide...")
        else:
            self.status_var.set("Config saved.")

    def reset_defaults(self):
        if not self.reset_confirm_pending:
            self.reset_confirm_pending = True
            self.status_var.set("Click Reset Defaults again to confirm.")
            return

        self.reset_confirm_pending = False
        cfg = self._default_form_config()
        self._set_form(cfg)
        save_config(cfg)
        self.active_hotkey_label = cfg.hotkey
        self.active_hide_hotkey_label = cfg.hide_hotkey
        self.active_toggle_mode = cfg.toggle_mode
        self._update_help_text()
        if self.service.is_running:
            self._restart_service_with_config(cfg)
            self.status_var.set("Defaults restored. Restarting MapHide...")
        else:
            self.status_var.set("Defaults restored.")

    def start_service(self):
        try:
            cfg = self._read_form()
            save_config(cfg)
            self.service = self._create_service(cfg)
            self.service.start(cfg)
        except ValueError as exc:
            self.status_var.set(str(exc))
            return
        except Exception as exc:
            self._show_error("Could not start MapHide", str(exc))
            return

        self.status_var.set("Starting...")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def stop_service(self):
        self.service.stop()
        self.status_var.set("Stopping...")

    def _restart_service_with_config(self, cfg):
        if self.restart_pending:
            self.pending_restart_config = cfg
            return
        self.restart_pending = True
        self.pending_restart_config = cfg
        self.restart_service_ref = self.service
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.restart_service_ref.stop()
        self.root.after(50, self._finish_service_restart)

    def _finish_service_restart(self):
        service_ref = self.restart_service_ref
        if service_ref is not None and service_ref.is_running:
            self.root.after(50, self._finish_service_restart)
            return

        cfg = self.pending_restart_config
        self.restart_pending = False
        self.pending_restart_config = None
        self.restart_service_ref = None

        if cfg is None:
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            return

        try:
            self.service = self._create_service(cfg)
            self.service.start(cfg)
        except Exception as exc:
            self.status_var.set(str(exc))
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            return

        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def _drain_events(self):
        while True:
            try:
                event = self.service.events.get_nowait()
            except queue.Empty:
                break

            kind = event["kind"]
            message = event["message"]
            timestamp = event["timestamp"]

            if kind == "status":
                self.status_var.set(message)
            elif kind == "overlay":
                self.status_var.set(f"{timestamp}  {message}")
            elif kind == "error":
                self.status_var.set(message)
            elif kind == "stopped":
                self.status_var.set(message)
                if not self.restart_pending:
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")

        self.root.after(100, self._drain_events)

    def _show_error(self, title, message):
        if messagebox is not None:
            messagebox.showerror(title, message)

    def _handle_global_click(self, event):
        widget = event.widget
        if not hasattr(widget, "winfo_class"):
            return
        widget_class = widget.winfo_class()
        focusable_inputs = {"TEntry", "Entry"}
        if widget_class in focusable_inputs:
            return
        try:
            self.root.focus_set()
        except Exception:
            pass

    def _update_help_text(self):
        hotkey = self.active_hotkey_label or "G"
        hide_hotkey = self.active_hide_hotkey_label or "H"
        if self.active_toggle_mode:
            self.help_text_var.set(
                f"Press {hotkey} to show the overlay. Press {hide_hotkey} to hide it."
            )
        else:
            self.help_text_var.set(f"Hold {hotkey} to show the overlay. Release {hotkey} to hide it.")

    def _update_toggle_mode_ui(self):
        toggle_mode = self.toggle_mode_var.get()
        self.hotkey_label_var.set("Show key" if toggle_mode else "Hotkey")
        if toggle_mode:
            self.hide_hotkey_label.grid()
            self.hide_hotkey_button.grid()
        else:
            self.hide_hotkey_label.grid_remove()
            self.hide_hotkey_button.grid_remove()
            if self.key_capture_target == "hide":
                self._stop_key_capture()
        self._sync_key_buttons()

    def _sync_key_buttons(self):
        if hasattr(self, "hotkey_button"):
            if self.key_capture_target != "show":
                self.hotkey_button.configure(text=self.hotkey_var.get().strip().upper() or "Select")
        if hasattr(self, "hide_hotkey_button"):
            if self.key_capture_target != "hide":
                self.hide_hotkey_button.configure(text=self.hide_hotkey_var.get().strip().upper() or "Select")

    def _start_key_capture(self, target):
        if self.key_capture_target == target:
            self._stop_key_capture()
            return
        self._stop_key_capture()
        self.key_capture_target = target
        button = self.hotkey_button if target == "show" else self.hide_hotkey_button
        button.configure(text="Press key...")
        if target == "show":
            self.status_var.set(SHOW_KEY_HELP)
        else:
            self.status_var.set(HIDE_KEY_HELP)
        try:
            self.root.focus_force()
        except Exception:
            pass

    def _stop_key_capture(self):
        if self.key_capture_target == "show" and hasattr(self, "hotkey_button"):
            self.hotkey_button.configure(text=self.hotkey_var.get().strip().upper() or "Select")
        elif self.key_capture_target == "hide" and hasattr(self, "hide_hotkey_button"):
            self.hide_hotkey_button.configure(text=self.hide_hotkey_var.get().strip().upper() or "Select")
        self.key_capture_target = None

    def _handle_key_capture_press(self, event):
        if self.key_capture_target is not None:
            return "break"
        return None

    def _handle_key_capture_release(self, event):
        if self.key_capture_target is None:
            return None
        hotkey = self._hotkey_from_event(event)
        if not hotkey:
            if self.key_capture_target == "hide":
                self.status_var.set(HIDE_KEY_HELP)
            else:
                self.status_var.set(SHOW_KEY_HELP)
            self._stop_key_capture()
            return "break"
        if self.key_capture_target == "show":
            if not is_valid_show_hotkey(hotkey):
                self.status_var.set(SHOW_KEY_HELP)
                self._stop_key_capture()
                return "break"
            self.hotkey_var.set(hotkey)
        elif self.key_capture_target == "hide":
            if not is_valid_hide_hotkey(hotkey):
                self.status_var.set(HIDE_KEY_HELP)
                self._stop_key_capture()
                return "break"
            self.hide_hotkey_var.set(hotkey)
        self._stop_key_capture()
        self._sync_key_buttons()
        self.status_var.set("Key selected. Click Save Settings to apply.")
        return "break"

    def _hotkey_from_event(self, event):
        key = normalize_event_key(event.keysym)
        if key is None:
            return None
        modifiers = [
            label
            for label, mask in EVENT_STATE_MODIFIERS
            if (event.state & mask) and label != key
        ]
        if key in MODIFIER_LABELS:
            return key
        labels = [*modifiers, key]
        return "+".join(labels)

    def _on_hide_delay_changed(self, value=None):
        self._update_hide_delay_label()

    def _update_hide_delay_label(self):
        self.hide_delay_label_var.set(f"{self._clamp_hide_delay(self.hide_delay_var.get())} ms")

    def _clamp_hide_delay(self, value):
        try:
            delay = int(float(value))
        except (TypeError, ValueError):
            delay = DEFAULT_HIDE_DELAY_MS
        return max(MIN_HIDE_DELAY_MS, min(MAX_HIDE_DELAY_MS, delay))

    def _create_service(self, cfg):
        return MapHideService(
            show_vk_codes=cfg.hotkey_vk_code(),
            show_hotkey_label=cfg.hotkey,
            toggle_mode=cfg.toggle_mode,
            hide_vk_codes=cfg.hide_hotkey_vk_code(),
            hide_hotkey_label=cfg.hide_hotkey,
        )

    def _update_sensitive_visibility(self):
        if hasattr(self, "host_entry"):
            self.host_entry.configure(show="" if self.show_host_var.get() else "*")
        if hasattr(self, "port_entry"):
            self.port_entry.configure(show="" if self.show_port_var.get() else "*")
        if hasattr(self, "password_entry"):
            self.password_entry.configure(show="" if self.show_password_var.get() else "*")

    def _apply_window_size(self, width):
        width = int(width)
        height = int(self.window_height)
        self.root.minsize(width, height)
        self.root.maxsize(width, height)
        self.root.geometry(f"{width}x{height}")

    def toggle_settings_panel(self):
        if self.settings_visible:
            self.hide_settings_panel()
        else:
            self.show_settings_panel()

    def show_settings_panel(self):
        if self.settings_visible:
            return
        self.settings_panel.grid()
        self.settings_visible = True
        self.settings_button.configure(text="< Settings")
        self._apply_window_size(self.expanded_width)

    def hide_settings_panel(self):
        if not self.settings_visible:
            return
        self._stop_key_capture()
        self.settings_visible = False
        self.settings_button.configure(text="Settings >")
        self.settings_panel.grid_remove()
        self._apply_window_size(self.collapsed_width)

    def _setup_tray(self):
        if pystray is None or Image is None or ImageDraw is None:
            self.status_var.set("Tray support unavailable. Closing the window will exit the app.")
            return

        menu = pystray.Menu(
            pystray.MenuItem("Show", self._on_tray_show, default=True),
            pystray.MenuItem("Exit", self._on_tray_exit),
        )
        self.tray_icon = pystray.Icon("MapHide", self._create_tray_image(), WINDOW_TITLE, menu)
        self.tray_thread = threading.Thread(target=self.tray_icon.run, name="TrayIcon", daemon=True)
        self.tray_thread.start()

    def _create_tray_image(self):
        if ICON_TRAY_PNG_PATH.exists():
            icon_image_path = ICON_TRAY_PNG_PATH
        elif ICON_RUNTIME_PNG_PATH.exists():
            icon_image_path = ICON_RUNTIME_PNG_PATH
        else:
            icon_image_path = ICON_PNG_PATH
        if icon_image_path.exists():
            try:
                return Image.open(icon_image_path).convert("RGBA")
            except Exception:
                pass

        image = Image.new("RGB", (64, 64), "#101820")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill="#2d6a4f")
        draw.rectangle((18, 18, 46, 26), fill="#d9ed92")
        draw.rectangle((18, 30, 34, 46), fill="#d9ed92")
        draw.rectangle((38, 30, 46, 46), fill="#d9ed92")
        return image

    def hide_to_tray(self):
        if self.tray_icon is None:
            self.exit_requested = True
            self.service.stop()
            self.service.wait(timeout=1.5)
            self.root.destroy()
            return

        self.is_hidden_to_tray = True
        self.root.withdraw()
        self.status_var.set("MapHide is still running in the system tray.")

    def show_window(self):
        self.is_hidden_to_tray = False
        current_state = self.root.state()
        if current_state == "withdrawn":
            self.root.deiconify()
        elif current_state == "iconic":
            self.root.state("normal")
        else:
            self.root.state("normal")
        self.root.after(0, self.root.lift)
        self.root.after(0, self.root.focus_force)

    def _on_tray_show(self, icon=None, item=None):
        self.root.after(0, self.show_window)

    def _on_tray_exit(self, icon=None, item=None):
        self.root.after(0, self.exit_app)

    def exit_app(self):
        self.exit_requested = True
        self.service.stop()
        self.service.wait(timeout=1.5)
        if self.tray_icon is not None:
            self.tray_icon.stop()
        self.root.destroy()

    def on_close(self):
        if self.exit_requested:
            return
        self.hide_to_tray()


def run_headless():
    print(f"MapHide starting - reading config from {CONFIG_PATH}...")
    try:
        cfg = load_config()
    except Exception as exc:
        print("Failed to load config:", exc)
        print(
            'Example config:\n{\n'
            '  "host":"",\n'
            '  "port":4455,\n'
            '  "password":"",\n'
            '  "scene_item_name":"",\n'
            '  "auto_connect":false,\n'
            '  "hotkey":"G",\n'
            '  "toggle_mode":false,\n'
            '  "hide_hotkey":"H",\n'
            '  "hide_delay_ms":120\n}'
        )
        sys.exit(1)

    service = MapHideService(
        show_vk_codes=cfg.hotkey_vk_code(),
        show_hotkey_label=cfg.hotkey,
        toggle_mode=cfg.toggle_mode,
        hide_vk_codes=cfg.hide_hotkey_vk_code(),
        hide_hotkey_label=cfg.hide_hotkey,
    )
    service.start(cfg)
    if cfg.toggle_mode:
        print(
            f"Headless mode active. Press {cfg.hotkey} to SHOW the overlay; "
            f"press {cfg.hide_hotkey} to HIDE. Press Ctrl+C to exit."
        )
    else:
        print(
            f"Headless mode active. Hold {cfg.hotkey} to SHOW the overlay; "
            f"release to HIDE. Press Ctrl+C to exit."
        )

    try:
        while True:
            event = service.events.get(timeout=0.5)
            print(f"{event['timestamp']}  {event['message']}")
            if event["kind"] in {"error", "stopped"} and not service.is_running:
                break
    except KeyboardInterrupt:
        print("\nExiting - stopping service...")
        service.stop()
        service.wait(timeout=2)


def run_gui():
    if tk is None or ttk is None:
        print("Tkinter is not available on this Python installation.")
        print("Run with --headless or install a Python build with Tk support.")
        sys.exit(1)

    set_windows_app_id()
    root = tk.Tk()
    MapHideApp(root)
    root.mainloop()


def main():
    if "--headless" in sys.argv:
        run_headless()
    else:
        run_gui()


if __name__ == "__main__":
    main()
