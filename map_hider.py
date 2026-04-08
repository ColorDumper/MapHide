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
APP_VERSION = "v0.1.1"
CONFIG_DIR = Path(os.getenv("APPDATA", APP_DIR)) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"
LEGACY_CONFIG_PATH = APP_DIR / "config.json"
ICON_ICO_PATH = APP_DIR / "MapHide.ico"
ICON_PNG_PATH = APP_DIR / "MapHide_Master.png"
WATERMARK_PNG_PATH = APP_DIR / "PaintTwo.png"
APP_USER_MODEL_ID = "MapHide.App"
TOGGLE_KEY_VK = 0x47
POLL_INTERVAL = 0.005
DEBOUNCE_MS = 50
HIDE_DELAY_MS = 160
SCENE_REFRESH_INTERVAL = 0.25
RECONNECT_DELAY = 2.0
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
    *[(str(number), ord(str(number))) for number in range(0, 10)],
    *[(f"F{number}", 0x6F + number) for number in range(1, 13)],
]
HOTKEY_LABELS = [label for label, _ in HOTKEY_OPTIONS]
HOTKEY_TO_VK = dict(HOTKEY_OPTIONS)


@dataclass
class AppConfig:
    host: str
    port: int
    password: str
    scene_item_name: str
    auto_connect: bool = False
    hotkey: str = "G"

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
        )

    def to_dict(self):
        return {
            "host": self.host,
            "port": self.port,
            "password": self.password,
            "scene_item_name": self.scene_item_name,
            "auto_connect": self.auto_connect,
            "hotkey": self.hotkey,
        }

    def hotkey_vk_code(self):
        return HOTKEY_TO_VK.get(self.hotkey, TOGGLE_KEY_VK)


def default_config():
    return AppConfig(
        host="",
        port=4455,
        password="",
        scene_item_name="",
        auto_connect=False,
        hotkey="G",
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


def is_key_down(vk_code):
    state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
    return (state & 0x8000) != 0


def human_ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def set_windows_app_id():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


class MapHideService:
    def __init__(self, vk_code=TOGGLE_KEY_VK, hotkey_label="G"):
        self.vk_code = vk_code
        self.hotkey_label = hotkey_label
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
                                self._emit(
                                    "status",
                                    f"Scene: {active_scene_name}. "
                                    f"{self.hotkey_label} toggles '{cfg.scene_item_name}'.",
                                    scene_item_id=item_id,
                                )
                        last_scene_refresh = now

                    down = is_key_down(self.vk_code)

                    if down and not overlay_visible and item_id is not None:
                        hide_requested_at = None
                        if (now - last_action_time) >= timedelta(milliseconds=DEBOUNCE_MS):
                            set_scene_item_enabled_raw(client, active_scene_name, item_id, True)
                            overlay_visible = True
                            last_action_time = now
                            self._emit("overlay", "Overlay shown.", visible=True)

                    elif not down and overlay_visible and item_id is not None:
                        if hide_requested_at is None:
                            hide_requested_at = now
                        if (
                            (now - hide_requested_at) >= timedelta(milliseconds=HIDE_DELAY_MS)
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
        self.collapsed_width = 0
        self.expanded_width = 0
        self.window_height = 0

        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.item_var = tk.StringVar()
        self.hotkey_var = tk.StringVar(value="G")
        self.show_host_var = tk.BooleanVar(value=False)
        self.show_port_var = tk.BooleanVar(value=False)
        self.show_password_var = tk.BooleanVar(value=False)
        self.auto_connect_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle")
        self.help_text_var = tk.StringVar(value="Hold G to show the overlay. Release G to hide it.")
        self.active_hotkey_label = "G"

        self._configure_styles()
        self._build_ui()
        self._apply_window_background()
        self._apply_window_icon()
        self._apply_footer_watermark()
        self._measure_window_sizes()
        self._apply_window_size(self.collapsed_width)
        self._load_initial_config()
        self.root.bind_all("<Button-1>", self._handle_global_click, add="+")
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
            "TCombobox",
            fieldbackground=COLOR_INPUT,
            foreground=COLOR_TEXT,
            background=COLOR_PANEL_ALT,
            arrowcolor=COLOR_TEXT,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
            padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", COLOR_INPUT)],
            foreground=[("readonly", COLOR_TEXT)],
            background=[("readonly", COLOR_PANEL_ALT)],
            arrowcolor=[("active", COLOR_ACCENT), ("readonly", COLOR_TEXT)],
        )
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
        ttk.Label(title_row, text=APP_VERSION, style="Version.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
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
        self.status_label = ttk.Label(controls_frame, textvariable=self.status_var, justify="left")
        self.status_label.grid(
            row=2,
            column=1,
            sticky="nsew",
            pady=(8, 6),
        )
        controls_frame.bind("<Configure>", self._update_status_wraplength)

        ttk.Label(
            controls_frame,
            textvariable=self.help_text_var,
            style="Muted.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

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

        ttk.Label(obs_frame, text="Hotkey").grid(row=3, column=0, sticky="w", pady=4, padx=(0, 10))
        self.hotkey_combobox = ttk.Combobox(
            obs_frame,
            textvariable=self.hotkey_var,
            values=HOTKEY_LABELS,
            width=5,
            state="readonly",
        )
        self.hotkey_combobox.grid(row=3, column=1, sticky="w", pady=4)

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

        self._update_sensitive_visibility()

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
            if ICON_PNG_PATH.exists():
                self.window_icon_image = tk.PhotoImage(file=str(ICON_PNG_PATH))
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
            watermark.thumbnail((40, 40), Image.Resampling.LANCZOS)
            self.footer_brand_image = ImageTk.PhotoImage(watermark)
            self.footer_brand.configure(image=self.footer_brand_image, text="")
        except Exception:
            pass

    def _measure_window_sizes(self):
        self.settings_panel.grid_remove()
        self.root.update_idletasks()
        self.collapsed_width = self.root.winfo_reqwidth()
        self.window_height = self.root.winfo_reqheight()

        self.settings_panel.grid()
        self.root.update_idletasks()
        self.expanded_width = self.root.winfo_reqwidth()
        self.window_height = max(self.window_height, self.root.winfo_reqheight()) + 36

        self.settings_panel.grid_remove()

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
        self.hotkey_var.set(cfg.hotkey if cfg.hotkey in HOTKEY_TO_VK else "G")
        self.active_hotkey_label = self.hotkey_var.get().strip().upper() or "G"
        self._update_help_text()

    def _read_form(self):
        host = self.host_var.get().strip()
        port_text = self.port_var.get().strip()
        password = self.password_var.get()
        scene_item_name = self.item_var.get().strip()
        hotkey = self.hotkey_var.get().strip().upper()

        if not host:
            raise ValueError("OBS Host is required.")
        if not port_text:
            raise ValueError("OBS Port is required.")
        if not scene_item_name:
            raise ValueError("Overlay Source is required.")
        if hotkey not in HOTKEY_TO_VK:
            raise ValueError("Select a valid hotkey.")

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
        )

    def save_form_config(self):
        try:
            cfg = self._read_form()
            save_config(cfg)
        except Exception as exc:
            self._show_error("Could not save config", str(exc))
            return
        self.active_hotkey_label = cfg.hotkey
        self._update_help_text()
        if self.service.is_running:
            self._restart_service_with_config(cfg)
        self.status_var.set("Config saved.")

    def start_service(self):
        try:
            cfg = self._read_form()
            save_config(cfg)
            self.service = MapHideService(vk_code=cfg.hotkey_vk_code(), hotkey_label=cfg.hotkey)
            self.service.start(cfg)
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
        self.service.stop()
        self.service.wait(timeout=2)
        self.service = MapHideService(vk_code=cfg.hotkey_vk_code(), hotkey_label=cfg.hotkey)
        self.service.start(cfg)

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
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")

        self.root.after(100, self._drain_events)

    def _show_error(self, title, message):
        if messagebox is not None:
            messagebox.showerror(title, message)

    def _update_status_wraplength(self, event=None):
        if not hasattr(self, "status_label"):
            return
        wraplength = max(self.status_label.winfo_width(), 220)
        self.status_label.configure(wraplength=wraplength)

    def _handle_global_click(self, event):
        widget = event.widget
        if not hasattr(widget, "winfo_class"):
            return
        widget_class = widget.winfo_class()
        focusable_inputs = {"TEntry", "Entry", "TCombobox", "Combobox"}
        if widget_class in focusable_inputs:
            return
        try:
            self.root.focus_set()
        except Exception:
            pass

    def _update_help_text(self):
        hotkey = self.active_hotkey_label or "G"
        self.help_text_var.set(f"Hold {hotkey} to show the overlay. Release {hotkey} to hide it.")

    def _update_sensitive_visibility(self):
        if hasattr(self, "host_entry"):
            self.host_entry.configure(show="" if self.show_host_var.get() else "*")
        if hasattr(self, "port_entry"):
            self.port_entry.configure(show="" if self.show_port_var.get() else "*")
        if hasattr(self, "password_entry"):
            self.password_entry.configure(show="" if self.show_password_var.get() else "*")

    def _apply_window_size(self, width):
        self.root.geometry(f"{int(width)}x{self.window_height}")
        self.root.update_idletasks()

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
        if ICON_PNG_PATH.exists():
            try:
                return Image.open(ICON_PNG_PATH).convert("RGBA")
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
            '  "hotkey":"G"\n}'
        )
        sys.exit(1)

    service = MapHideService(vk_code=cfg.hotkey_vk_code(), hotkey_label=cfg.hotkey)
    service.start(cfg)
    print(f"Headless mode active. Hold {cfg.hotkey} to SHOW the overlay; release to HIDE. Press Ctrl+C to exit.")

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
