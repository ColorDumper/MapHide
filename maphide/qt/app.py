"""Starts MapHide's window.

The window's state is simulated here, so its look and feel can be judged
without OBS.
"""

import sys
import time
from dataclasses import asdict

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from ..paths import APP_DIR, APP_USER_MODEL_ID, APP_VERSION, ICON_RUNTIME_PNG_PATH
from ..themes import DEFAULT_THEME, THEMES
from ..winutil import apply_dark_title_bar, set_app_id

QML_PATH = APP_DIR / "maphide" / "qt" / "Main.qml"
FONTS_DIR = APP_DIR / "assets" / "fonts"


def argb(color, opacity):
    """'#rrggbb' at `opacity` as Qt's '#aarrggbb'."""
    return f"#{round(opacity * 255):02x}{color[1:]}"


def theme_colors(name):
    """A theme's colors as QML reads them, with each see-through color
    already combined with its opacity."""
    theme = THEMES[name]
    colors = asdict(theme)
    colors["glass"] = argb(theme.panel, theme.glass_opacity)
    colors["glass_button"] = argb(theme.panel, theme.glass_button_opacity)
    colors["scan_line"] = argb(theme.scan_line, theme.scan_line_opacity)
    # Field draws its contour lines in the text color, Legacy in the muted one.
    colors["topo_line"] = theme.text if name == "field" else theme.muted
    colors["switch_off"] = theme.border2
    return colors


class Backend(QObject):
    changed = Signal()
    # time, text, kind ("n" plain, "r" covered, "g" linked)
    lineAdded = Signal(str, str, str)

    def __init__(self):
        super().__init__()
        self._state = "stopped"
        self._toggle = False
        self._show_key = "G"
        self._hide_key = "H"
        self._delay_ms = 120
        self._theme = DEFAULT_THEME
        self._link_timer = QTimer(self, singleShot=True, interval=1300)
        self._link_timer.timeout.connect(self._link_up)
        self._hide_timer = QTimer(self, singleShot=True)
        self._hide_timer.timeout.connect(self._drop_cover)

    def _add(self, message, kind="n"):
        self.lineAdded.emit(time.strftime("%H:%M:%S"), message, kind)

    def _set(self, state, message=None, kind="n"):
        self._state = state
        if message:
            self._add(message, kind)
        self.changed.emit()

    def _link_up(self):
        self._set("connected", "> link up · obs", "g")

    def _drop_cover(self):
        self._set("connected", "> cover dropped")

    @Property(str, notify=changed)
    def state(self):
        return self._state

    @Property(str, notify=changed)
    def scene(self):
        return {"stopped": "—", "connecting": "…"}.get(self._state, "Gameplay")

    @Property(str, notify=changed)
    def mode(self):
        if self._toggle:
            return f"TOGGLE · {self._show_key}/{self._hide_key}"
        return f"HOLD · {self._show_key}"

    @Property(str, notify=changed)
    def showKey(self):
        return self._show_key

    @Property(bool, notify=changed)
    def toggleMode(self):
        return self._toggle

    @Property("QVariantMap", notify=changed)
    def theme(self):
        return theme_colors(self._theme)

    @Property(str, constant=True)
    def version(self):
        return APP_VERSION

    @Property(str, constant=True)
    def assets(self):
        return QUrl.fromLocalFile(str(APP_DIR / "assets")).toString()

    @Slot()
    def primary(self):
        if self._state == "stopped":
            self._set("connecting", "> acquiring link…")
            self._link_timer.start()
        else:
            self._link_timer.stop()
            self._hide_timer.stop()
            self._set("stopped", "> stopped")

    @Slot()
    def holdDown(self):
        if self._state not in ("connected", "covering"):
            return
        self._hide_timer.stop()
        if self._toggle and self._state == "covering":
            self._set("connected", "> cover dropped")
        elif self._state == "connected":
            self._set("covering", "> map covered", "r")

    @Slot()
    def holdUp(self):
        if not self._toggle and self._state == "covering":
            self._hide_timer.start(self._delay_ms)

    @Slot(str)
    def setTheme(self, name):
        self._theme = name
        self.changed.emit()


def load_fonts():
    for font in sorted(FONTS_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(font))


def main():
    set_app_id(APP_USER_MODEL_ID)
    app = QGuiApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ICON_RUNTIME_PNG_PATH)))
    load_fonts()

    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_PATH)))
    if not engine.rootObjects():
        return 1
    window = engine.rootObjects()[0]

    def paint_title_bar():
        apply_dark_title_bar(int(window.winId()), backend.theme["title_bar"])

    paint_title_bar()
    backend.changed.connect(paint_title_bar)
    result = app.exec()
    # Tear the window down while the backend it reads from still exists.
    del engine
    return result
