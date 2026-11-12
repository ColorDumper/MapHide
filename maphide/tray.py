"""The notification-area (tray) icon and its menu."""

import threading

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None

from .paths import APP_NAME, ICON_RUNTIME_PNG_PATH, ICON_TRAY_PNG_PATH

TRAY_FALLBACK_SIZE = (64, 64)
COLOR_TRAY_BG = "#101820"
COLOR_TRAY_TILE = "#2d6a4f"
COLOR_TRAY_MARK = "#d9ed92"


def tray_available():
    return pystray is not None and Image is not None and ImageDraw is not None


def tray_image():
    """The tray icon's picture: the bundled icon, or a simple drawn one if
    it can't be read."""
    icon_image_path = ICON_TRAY_PNG_PATH if ICON_TRAY_PNG_PATH.exists() else ICON_RUNTIME_PNG_PATH
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


class TrayIcon:
    """A tray icon with Show and Exit, running on its own thread.

    `on_show` and `on_exit` are called on the tray's thread, not the
    window's: they must hand the work over to the window's thread
    themselves rather than touch any widget directly.
    """

    def __init__(self, title, on_show, on_exit):
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda _icon, _item: on_show(), default=True),
            pystray.MenuItem("Exit", lambda _icon, _item: on_exit()),
        )
        self._icon = pystray.Icon(APP_NAME, tray_image(), title, menu)
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._icon.run, name="TrayIcon", daemon=True)
        self._thread.start()

    def stop(self):
        self._icon.stop()
