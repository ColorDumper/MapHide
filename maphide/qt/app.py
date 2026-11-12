"""MapHide's window: a Qt Quick front end on the controller.

Main.qml draws; the Backend here hands it what to draw and forwards what the
user does to the controller. The rules for what the screen shows live in
view.py, where they are tested without Qt.
"""

import sys
from dataclasses import asdict

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from ..config import config_from_form
from ..controller import HISTORY_NOTICE, AppController
from ..fieldlog import field_line
from ..logs import plain_reason
from ..overlay import human_ts
from ..paths import APP_DIR, APP_USER_MODEL_ID, APP_VERSION, ICON_RUNTIME_PNG_PATH
from ..themes import THEMES, theme_name
from ..winutil import apply_dark_title_bar, set_app_id
from .view import (
    FORM_FIELDS,
    captured_hotkey,
    form_values,
    key_label,
    main_view,
    new_entries,
    source_line,
)

QML_PATH = APP_DIR / "maphide" / "qt" / "Main.qml"
FONTS_DIR = APP_DIR / "assets" / "fonts"
# How often the window catches up with the worker: its events, the live
# scene, and whether the map is covered.
POLL_INTERVAL_MS = 100
AUTO_CONNECT_DELAY_MS = 250
CONFIG_NOT_LOADED = "Settings couldn't be read, so the defaults are in use."


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


def _schedule(milliseconds, callback):
    QTimer.singleShot(milliseconds, callback)


class Backend(QObject):
    changed = Signal()
    themeChanged = Signal()
    # time, text, tone - see fieldlog
    lineAdded = Signal(str, str, str)
    # The window should hide now: MapHide is closing.
    hideRequested = Signal()
    # The settings form's values changed from this side (load, reset).
    formChanged = Signal()
    # Test Link, the cover source line.
    settingsChanged = Signal()
    saved = Signal()
    # A reason to show in the drawer's footer.
    saveFailed = Signal(str)

    def __init__(self, quit_app=None, schedule=_schedule, **controller_options):
        """`controller_options` go to the AppController - a test passes a
        stand-in service, save or connection check there."""
        super().__init__()
        self.controller = AppController(
            schedule=schedule, notify=self.notice, on_change=self.refresh, **controller_options
        )
        # exit(), not quit(): Qt's quit() first asks every window to close
        # and gives up if one refuses - and this window refuses until the
        # worker has finished hiding the overlay, which is when this runs.
        self._quit_app = quit_app or (lambda: QGuiApplication.exit(0))
        self._view = main_view(self.controller)
        self._last_entry = None
        self._form = form_values(self.controller.running_config)
        # "idle", "busy", "ok" or "failed", and what a failure said.
        self._test_state = "idle"
        self._test_message = ""
        # The last Test Link's scene count, and the source name it was for.
        self._tested_source = None
        self._tested_count = None
        self._settings = self._settings_view()
        self._poll_timer = QTimer(self, interval=POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)

    def load(self, **load_options):
        """Read the saved settings and start watching the worker. Call once
        the window exists, so it sees the first lines of the field log."""
        cfg, loaded = self.controller.load(**load_options)
        self._set_form(cfg)
        if not loaded:
            self.notice(CONFIG_NOT_LOADED)
        self.refresh()
        self._poll_timer.start()
        if cfg.auto_connect:
            QTimer.singleShot(AUTO_CONNECT_DELAY_MS, self._start)

    # Keeping the window current.

    def _poll(self):
        self.controller.drain_events()
        self.refresh()

    def refresh(self):
        for entry in new_entries(self.controller.history, self._last_entry):
            line = field_line(entry)
            self.lineAdded.emit(line.time, line.text, line.tone)
            self._last_entry = entry
        view = main_view(self.controller)
        if view != self._view:
            self._view = view
            self.changed.emit()
        settings = self._settings_view()
        if settings != self._settings:
            self._settings = settings
            self.settingsChanged.emit()

    def _source_count(self):
        """How many scenes carry the source named in the form, if known:
        live from the worker while it runs with that name, else from the
        last Test Link for it."""
        source = str(self._form["scene_item_name"]).strip()
        live = self.controller.snapshot.source_scene_count
        if live is not None and source == self.controller.running_config.scene_item_name:
            return live
        if source == self._tested_source:
            return self._tested_count
        return None

    def _settings_view(self):
        text, warning = source_line(self._source_count())
        return (text, warning, self._test_state, self._test_message)

    def _set_form(self, cfg):
        self._form = form_values(cfg)
        self.formChanged.emit()
        self.themeChanged.emit()

    def notice(self, text):
        """Tell the user something in the field log, such as why Start
        didn't go ahead."""
        self.controller.add_history(human_ts(), text, HISTORY_NOTICE)
        self.refresh()

    # What the window draws.

    @Property(str, notify=changed)
    def screen(self):
        return self._view.screen

    @Property(str, notify=changed)
    def hint(self):
        return self._view.hint

    @Property(str, notify=changed)
    def scene(self):
        return self._view.scene

    @Property(str, notify=changed)
    def mode(self):
        return self._view.mode

    @Property(str, notify=changed)
    def showKey(self):
        return self._view.show_key

    @Property(bool, notify=changed)
    def toggleMode(self):
        return self._view.toggle_mode

    @Property(bool, notify=changed)
    def primaryIsStop(self):
        return self._view.primary_is_stop

    @Property(bool, notify=changed)
    def primaryEnabled(self):
        return self._view.primary_enabled

    @Property(bool, notify=changed)
    def testEnabled(self):
        return self._view.test_enabled

    @Property("QVariantMap", notify=themeChanged)
    def theme(self):
        return theme_colors(theme_name(self._form["theme"]))

    @Property(str, notify=themeChanged)
    def themeName(self):
        return theme_name(self._form["theme"])

    @Property(str, constant=True)
    def version(self):
        return APP_VERSION

    @Property(str, constant=True)
    def assets(self):
        return QUrl.fromLocalFile(str(APP_DIR / "assets")).toString()

    # What the user does.

    def _start(self):
        try:
            self.controller.start(config_from_form(**self._form))
        except ValueError as exc:
            self.notice(str(exc))
        except OSError as exc:
            self.notice(f"Couldn't save settings: {plain_reason(exc)}")
        except RuntimeError as exc:
            self.notice(str(exc))

    @Slot()
    def primary(self):
        if self._view.primary_is_stop:
            self.controller.stop()
        else:
            self._start()

    @Slot()
    def holdDown(self):
        self.controller.set_manual_input(True)

    @Slot()
    def holdUp(self):
        self.controller.set_manual_input(False)

    @Slot()
    def requestClose(self):
        """The window's close button: stop the worker, letting it hide the
        overlay, then quit."""
        if self.controller.begin_exit(self._quit_app):
            self.hideRequested.emit()

    # The settings drawer.

    @Property("QVariantMap", notify=formChanged)
    def form(self):
        return self._form

    @Slot(str, "QVariant")
    def setField(self, name, value):
        if name not in FORM_FIELDS:
            return
        if name == "hide_delay_ms":
            # QML numbers arrive as floats.
            value = round(value)
        self._form[name] = value
        if name == "theme":
            self.themeChanged.emit()
        self.formChanged.emit()
        self.refresh()

    @Slot(str, int, bool, result=str)
    def captureKey(self, target, key, shift_held):
        """Set the show or hide key from a key press. Returns "" when it
        took, or the help to show when the key can't be used."""
        hotkey, problem = captured_hotkey(target, key, shift_held)
        if hotkey is None:
            return problem
        self._form["hotkey" if target == "show" else "hide_hotkey"] = hotkey
        self.formChanged.emit()
        return ""

    @Slot(str, result=str)
    def keyLabel(self, hotkey):
        return key_label(hotkey)

    @Property(str, notify=settingsChanged)
    def sourceText(self):
        return self._settings[0]

    @Property(bool, notify=settingsChanged)
    def sourceWarning(self):
        return self._settings[1]

    @Property(str, notify=settingsChanged)
    def testState(self):
        return self._test_state

    @Property(str, notify=settingsChanged)
    def testMessage(self):
        return self._test_message

    def _set_test(self, state, message=""):
        self._test_state = state
        self._test_message = message
        self.refresh()

    @Slot()
    def testLink(self):
        form = self._form
        source = str(form["scene_item_name"]).strip()

        def done(result):
            if result.ok:
                self._tested_source = source
                self._tested_count = result.source_scene_count
            self._set_test("ok" if result.ok else "failed", result.message)

        try:
            started = self.controller.check_connection(
                form["host"], form["port"], form["password"], source, done
            )
        except ValueError as exc:
            self._set_test("failed", str(exc))
            return
        if started:
            self._set_test("busy")

    @Slot()
    def clearTest(self):
        if self._test_state != "busy":
            self._set_test("idle")

    @Slot()
    def save(self):
        try:
            self.controller.save(config_from_form(**self._form))
        except ValueError as exc:
            self.saveFailed.emit(str(exc))
            return
        except OSError as exc:
            self.saveFailed.emit(f"Couldn't save settings: {plain_reason(exc)}")
            return
        self.saved.emit()

    @Slot()
    def resetDefaults(self):
        try:
            cfg = self.controller.restore_defaults()
        except OSError as exc:
            self.saveFailed.emit(f"Couldn't save settings: {plain_reason(exc)}")
            return
        self._set_form(cfg)
        self.saved.emit()


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
    backend.themeChanged.connect(paint_title_bar)
    backend.hideRequested.connect(window.hide)
    backend.load()
    result = app.exec()
    # Tear the window down while the backend it reads from still exists.
    del engine
    return result
