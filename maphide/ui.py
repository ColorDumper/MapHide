"""The settings window and the tray icon."""

import ctypes
import queue
import sys
import threading

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    tk = None
    ttk = None
    messagebox = None

try:
    import pystray
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None
    ImageTk = None

from dataclasses import replace

from .config import (
    DEFAULT_HIDE_DELAY_MS,
    MAX_HIDE_DELAY_MS,
    MIN_HIDE_DELAY_MS,
    AppConfig,
    default_config,
    load_config,
    save_config,
)
from .hotkeys import (
    HIDE_KEY_HELP,
    MODIFIER_STATE_MASKS,
    SHOW_KEY_HELP,
    is_valid_hide_hotkey,
    is_valid_show_hotkey,
    normalize_event_key,
)
from .overlay import MapHideService
from .paths import (
    APP_NAME,
    APP_USER_MODEL_ID,
    APP_VERSION,
    ICON_ICO_PATH,
    ICON_RUNTIME_PNG_PATH,
    ICON_TRAY_PNG_PATH,
    ICON_WINDOW_PNG_PATH,
    WATERMARK_PNG_PATH,
)

KEY_BUTTON_WIDTH = 16
STATUS_AREA_WIDTH = 300
STATUS_AREA_HEIGHT = 72
HELP_AREA_WIDTH = 340
HELP_AREA_HEIGHT = 44
# Tk's requested size comes up short of what the panel actually needs once it
# is mapped, so the measured figures get this much added on.
WINDOW_EXTRA_WIDTH = 32
WINDOW_EXTRA_HEIGHT = 56
EVENT_DRAIN_INTERVAL_MS = 100
AUTO_CONNECT_DELAY_MS = 250
RESTART_POLL_INTERVAL_MS = 50
SERVICE_STOP_WAIT = 1.5
KEY_CAPTURE_PROMPT = "Press key..."
KEY_UNSET_LABEL = "Select"
SETTINGS_SHOW_LABEL = "Settings >"
SETTINGS_HIDE_LABEL = "< Settings"
FOCUSABLE_WIDGET_CLASSES = ("TEntry", "Entry")
TRAY_FALLBACK_SIZE = (64, 64)
COLOR_TRAY_BG = "#101820"
COLOR_TRAY_TILE = "#2d6a4f"
COLOR_TRAY_MARK = "#d9ed92"
WATERMARK_MAX_SIZE = (64, 40)
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


def set_windows_app_id():
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)


class MapHideApp:
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.resizable(False, False)
        self.service = MapHideService()
        self.tray_icon = None
        self.tray_thread = None
        self.exit_requested = False
        self.settings_visible = False
        self.restart_pending = False
        self.pending_restart_config = None
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
        self.hotkey_caption_var = tk.StringVar(value="Hotkey")
        self.hide_delay_var = tk.IntVar(value=DEFAULT_HIDE_DELAY_MS)
        self.hide_delay_label_var = tk.StringVar(value=f"{DEFAULT_HIDE_DELAY_MS} ms")
        self.show_host_var = tk.BooleanVar(value=False)
        self.show_port_var = tk.BooleanVar(value=False)
        self.show_password_var = tk.BooleanVar(value=False)
        self.auto_connect_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle")
        self.help_text_var = tk.StringVar(value="Hold G to show the overlay. Release G to hide it.")
        self.running_config = default_config()
        self.key_capture_target = None

        # Stay hidden while building. Windows gives a taskbar button its icon at
        # the moment the window first appears, so appearing before the icon is set
        # leaves Tk's own feather there until the window is next re-shown. Building
        # unseen also spares the user the window resizing itself on the way up.
        self.root.withdraw()
        self._configure_styles()
        self._build_ui()
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
        self.root.after(EVENT_DRAIN_INTERVAL_MS, self._drain_events)
        self.root.deiconify()

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

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
        self.settings_button = ttk.Button(header_row, text=SETTINGS_SHOW_LABEL, command=self.toggle_settings_panel)
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

        self.hotkey_caption = ttk.Label(obs_frame, textvariable=self.hotkey_caption_var)
        self.hotkey_caption.grid(row=3, column=0, sticky="w", pady=4, padx=(0, 10))

        hotkey_controls = ttk.Frame(obs_frame)
        hotkey_controls.grid(row=3, column=1, columnspan=2, sticky="w", pady=4)

        self.hotkey_button = ttk.Button(
            hotkey_controls,
            text=self.hotkey_var.get(),
            width=KEY_BUTTON_WIDTH,
            command=lambda: self._start_key_capture("show"),
        )
        self.hotkey_button.grid(row=0, column=0, sticky="w")

        self.hide_hotkey_caption = ttk.Label(hotkey_controls, text="Hide key")
        self.hide_hotkey_button = ttk.Button(
            hotkey_controls,
            text=self.hide_hotkey_var.get(),
            width=KEY_BUTTON_WIDTH,
            command=lambda: self._start_key_capture("hide"),
        )
        self.hide_hotkey_caption.grid(row=0, column=1, sticky="w", padx=(8, 6))
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
            command=lambda _value: self._update_hide_delay_label(),
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

    def _apply_window_icon(self):
        # The window has to exist before the icon will stick to it, but it is still
        # withdrawn here, so this creates it without putting it on screen.
        self.root.update_idletasks()
        try:
            if ICON_ICO_PATH.exists():
                self.root.iconbitmap(default=str(ICON_ICO_PATH))
        except tk.TclError:
            pass
        # One image, the largest we ship. Given several, Tk hands Windows the
        # smallest for the icon the taskbar draws, which is what left it soft;
        # given one large image Windows scales it down cleanly for every size.
        icon_photo_path = next(
            (
                path
                for path in (ICON_RUNTIME_PNG_PATH, ICON_TRAY_PNG_PATH, ICON_WINDOW_PNG_PATH)
                if path.exists()
            ),
            None,
        )
        if icon_photo_path is not None:
            try:
                self.window_icon_image = tk.PhotoImage(file=str(icon_photo_path))
                self.root.iconphoto(True, self.window_icon_image)
            except tk.TclError:
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
        except (OSError, tk.TclError):
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
        # Measured against the widest content the panel can hold, so the window
        # never has to resize once a longer key name is chosen.
        self.hotkey_var.set(KEY_CAPTURE_PROMPT)
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

    def _load_initial_config(self):
        try:
            cfg = load_config()
        except (OSError, ValueError, KeyError):
            cfg = default_config()
            self.status_var.set("Config not loaded. Fill in values and save settings.")
        self._set_form(cfg)
        if cfg.auto_connect:
            self.root.after(AUTO_CONNECT_DELAY_MS, self.start_service)

    def _set_form(self, cfg):
        cfg = replace(
            cfg,
            hotkey=cfg.hotkey if is_valid_show_hotkey(cfg.hotkey) else "G",
            hide_hotkey=cfg.hide_hotkey if is_valid_hide_hotkey(cfg.hide_hotkey) else "H",
            hide_delay_ms=self._clamp_hide_delay(cfg.hide_delay_ms),
        )
        self.running_config = cfg
        self.host_var.set(cfg.host)
        self.port_var.set(str(cfg.port))
        self.password_var.set(cfg.password)
        self.item_var.set(cfg.scene_item_name)
        self.auto_connect_var.set(cfg.auto_connect)
        self.hotkey_var.set(cfg.hotkey)
        self.toggle_mode_var.set(cfg.toggle_mode)
        self.hide_hotkey_var.set(cfg.hide_hotkey)
        self.hide_delay_var.set(cfg.hide_delay_ms)
        self._update_hide_delay_label()
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
        except OSError as exc:
            self._show_error("Could not save config", str(exc))
            return
        self._apply_config(cfg, "Config saved.")

    def reset_defaults(self):
        if not self.reset_confirm_pending:
            self.reset_confirm_pending = True
            self.status_var.set("Click Reset Defaults again to confirm.")
            return

        self.reset_confirm_pending = False
        cfg = default_config()
        self._set_form(cfg)
        save_config(cfg)
        self._apply_config(cfg, "Defaults restored.")

    def _apply_config(self, cfg, done_message):
        self.running_config = cfg
        self._update_help_text()
        if self.service.is_running:
            self._restart_service_with_config(cfg)
            self.status_var.set(f"{done_message} Restarting MapHide...")
        else:
            self.status_var.set(done_message)

    def start_service(self):
        try:
            cfg = self._read_form()
            save_config(cfg)
            self.service.start(cfg)
        except ValueError as exc:
            self.status_var.set(str(exc))
            return
        except (OSError, RuntimeError) as exc:
            self._show_error("Could not start MapHide", str(exc))
            return

        self.status_var.set("Starting...")
        self._sync_service_buttons()

    def stop_service(self):
        self.service.stop()
        self.status_var.set("Stopping...")

    def _restart_service_with_config(self, cfg):
        self.pending_restart_config = cfg
        if self.restart_pending:
            return
        self.restart_pending = True
        self._sync_service_buttons()
        self.service.stop()
        self.root.after(RESTART_POLL_INTERVAL_MS, self._finish_service_restart)

    def _finish_service_restart(self):
        # The worker clears its running flag on the way out, so wait for it
        # rather than starting a second one on top of it.
        if self.service.is_running:
            self.root.after(RESTART_POLL_INTERVAL_MS, self._finish_service_restart)
            return

        cfg = self.pending_restart_config
        self.restart_pending = False
        self.pending_restart_config = None
        try:
            self.service.start(cfg)
        except RuntimeError as exc:
            self.status_var.set(str(exc))
        self._sync_service_buttons()

    def _sync_service_buttons(self):
        # Derived from what the service is doing, not from the event stream. A
        # restart stops and starts the same service, so its "stopped" event can
        # arrive after the restart has already finished; acting on that event
        # switched the buttons back while MapHide was still running.
        running = self.service.is_running
        wanted = {
            self.start_button: "disabled" if running or self.restart_pending else "normal",
            self.stop_button: "normal" if running and not self.restart_pending else "disabled",
        }
        for button, state in wanted.items():
            if str(button.cget("state")) != state:
                button.configure(state=state)

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

        self._sync_service_buttons()
        self.root.after(EVENT_DRAIN_INTERVAL_MS, self._drain_events)

    def _show_error(self, title, message):
        if messagebox is not None:
            messagebox.showerror(title, message)

    def _handle_global_click(self, event):
        widget = event.widget
        if not hasattr(widget, "winfo_class"):
            return
        widget_class = widget.winfo_class()
        if widget_class in FOCUSABLE_WIDGET_CLASSES:
            return
        try:
            self.root.focus_set()
        except tk.TclError:
            pass

    def _update_help_text(self):
        hotkey = self.running_config.hotkey
        hide_hotkey = self.running_config.hide_hotkey
        if self.running_config.toggle_mode:
            self.help_text_var.set(
                f"Press {hotkey} to show the overlay. Press {hide_hotkey} to hide it."
            )
        else:
            self.help_text_var.set(f"Hold {hotkey} to show the overlay. Release {hotkey} to hide it.")

    def _update_toggle_mode_ui(self):
        toggle_mode = self.toggle_mode_var.get()
        self.hotkey_caption_var.set("Show key" if toggle_mode else "Hotkey")
        if toggle_mode:
            self.hide_hotkey_caption.grid()
            self.hide_hotkey_button.grid()
        else:
            self.hide_hotkey_caption.grid_remove()
            self.hide_hotkey_button.grid_remove()
            if self.key_capture_target == "hide":
                self._stop_key_capture()
        self._sync_key_buttons()

    def _sync_key_buttons(self):
        if hasattr(self, "hotkey_button"):
            if self.key_capture_target != "show":
                self.hotkey_button.configure(text=self.hotkey_var.get().strip().upper() or KEY_UNSET_LABEL)
        if hasattr(self, "hide_hotkey_button"):
            if self.key_capture_target != "hide":
                self.hide_hotkey_button.configure(text=self.hide_hotkey_var.get().strip().upper() or KEY_UNSET_LABEL)

    def _start_key_capture(self, target):
        if self.key_capture_target == target:
            self._stop_key_capture()
            return
        self._stop_key_capture()
        self.key_capture_target = target
        button = self.hotkey_button if target == "show" else self.hide_hotkey_button
        button.configure(text=KEY_CAPTURE_PROMPT)
        if target == "show":
            self.status_var.set(SHOW_KEY_HELP)
        else:
            self.status_var.set(HIDE_KEY_HELP)
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def _stop_key_capture(self):
        if self.key_capture_target == "show" and hasattr(self, "hotkey_button"):
            self.hotkey_button.configure(text=self.hotkey_var.get().strip().upper() or KEY_UNSET_LABEL)
        elif self.key_capture_target == "hide" and hasattr(self, "hide_hotkey_button"):
            self.hide_hotkey_button.configure(text=self.hide_hotkey_var.get().strip().upper() or KEY_UNSET_LABEL)
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
            for label, mask in MODIFIER_STATE_MASKS.items()
            if (event.state & mask) and label != key
        ]
        if key in MODIFIER_STATE_MASKS:
            return key
        labels = [*modifiers, key]
        return "+".join(labels)

    def _update_hide_delay_label(self):
        self.hide_delay_label_var.set(f"{self._clamp_hide_delay(self.hide_delay_var.get())} ms")

    def _clamp_hide_delay(self, value):
        try:
            delay = int(float(value))
        except (TypeError, ValueError):
            delay = DEFAULT_HIDE_DELAY_MS
        return max(MIN_HIDE_DELAY_MS, min(MAX_HIDE_DELAY_MS, delay))

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
            self._hide_settings_panel()
        else:
            self._show_settings_panel()

    def _show_settings_panel(self):
        if self.settings_visible:
            return
        self.settings_panel.grid()
        self.settings_visible = True
        self.settings_button.configure(text=SETTINGS_HIDE_LABEL)
        self._apply_window_size(self.expanded_width)

    def _hide_settings_panel(self):
        if not self.settings_visible:
            return
        self._stop_key_capture()
        self.settings_visible = False
        self.settings_button.configure(text=SETTINGS_SHOW_LABEL)
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
        self.tray_icon = pystray.Icon(APP_NAME, self._create_tray_image(), WINDOW_TITLE, menu)
        self.tray_thread = threading.Thread(target=self.tray_icon.run, name="TrayIcon", daemon=True)
        self.tray_thread.start()

    def _create_tray_image(self):
        if ICON_TRAY_PNG_PATH.exists():
            icon_image_path = ICON_TRAY_PNG_PATH
        else:
            icon_image_path = ICON_RUNTIME_PNG_PATH
        if icon_image_path.exists():
            try:
                return Image.open(icon_image_path).convert("RGBA")
            except OSError:
                pass

        image = Image.new("RGB", TRAY_FALLBACK_SIZE, COLOR_TRAY_BG)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=COLOR_TRAY_TILE)
        draw.rectangle((18, 18, 46, 26), fill=COLOR_TRAY_MARK)
        draw.rectangle((18, 30, 34, 46), fill=COLOR_TRAY_MARK)
        draw.rectangle((38, 30, 46, 46), fill=COLOR_TRAY_MARK)
        return image

    def _hide_to_tray(self):
        if self.tray_icon is None:
            self.exit_requested = True
            self.service.stop()
            self.service.wait(timeout=SERVICE_STOP_WAIT)
            self.root.destroy()
            return

        self.root.withdraw()
        self.status_var.set("MapHide is still running in the system tray.")

    def _show_window(self):
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
        self.root.after(0, self._show_window)

    def _on_tray_exit(self, icon=None, item=None):
        self.root.after(0, self._exit_app)

    def _exit_app(self):
        self.exit_requested = True
        self.service.stop()
        self.service.wait(timeout=SERVICE_STOP_WAIT)
        if self.tray_icon is not None:
            self.tray_icon.stop()
        self.root.destroy()

    def on_close(self):
        if self.exit_requested:
            return
        self._hide_to_tray()



def run_gui():
    if tk is None or ttk is None:
        print("Tkinter is not available on this Python installation.")
        print("Run with --headless or install a Python build with Tk support.")
        sys.exit(1)

    set_windows_app_id()
    root = tk.Tk()
    MapHideApp(root)
    root.mainloop()
