"""MapHide's window: a Qt Quick front end on the controller.

Main.qml draws; the Backend here hands it what to draw and forwards what the
user does to the controller. The rules for what the screen shows live in
view.py, where they are tested without Qt.
"""

import sys
from ctypes import wintypes
from dataclasses import asdict

from PySide6.QtCore import (
    Property,
    QAbstractNativeEventFilter,
    QEvent,
    QObject,
    QPoint,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QFontDatabase, QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalServer
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from shiboken6 import isValid

from ..config import config_from_form
from ..controller import HISTORY_NOTICE, HISTORY_UPDATE_AVAILABLE, AppController
from ..fieldlog import field_line
from ..logs import plain_reason
from ..overlay import human_ts
from ..paths import APP_DIR, APP_NAME, APP_USER_MODEL_ID, ICON_ICO_PATH
from ..single_instance import COMMAND_QUIT, COMMAND_SHOW, command_pipe_name
from ..themes import THEMES, theme_name
from ..updates import RELEASES_PAGE, Updater, checks_for_updates
from ..version import APP_VERSION
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
# The startup update check waits a little, so it never slows MapHide opening.
UPDATE_CHECK_DELAY_MS = 3000
CONFIG_NOT_LOADED = "Settings couldn't be read, so the defaults are in use."
NO_TRAY = "No notification area, so closing the window will exit MapHide."
# How long to wait, when Windows is signing out or shutting down, for the
# worker to hide the overlay. Windows gives an app about five seconds before
# ending it regardless.
SESSION_END_WAIT_SECONDS = 4
WM_ENDSESSION = 0x0016
# Fonts the window is drawn in; the self-test checks each one loaded.
FONT_FAMILIES = ("Barlow", "Barlow Condensed", "IBM Plex Mono")
# The shortest the window gets on a small screen: everything above the
# field log still shows.
MIN_WINDOW_HEIGHT = 540
# The title bar and border, when Windows hasn't said yet (the window isn't
# shown). Generous, so a guess never leaves the bottom off-screen.
DEFAULT_FRAME_HEIGHT = 40


def fitted_height(full, available, frame):
    """The window's height on a screen with `available` height above the
    taskbar, `frame` of it going to the title bar: the full height when it
    fits, otherwise what fits, but never below MIN_WINDOW_HEIGHT."""
    return max(MIN_WINDOW_HEIGHT, min(full, available - frame))


def on_screen_top(top, height, area_top, area_height):
    """Where a window `height` tall, now at `top`, goes so it's inside the
    area: it stays put if it already is. When it can't fit, its title bar
    stays visible."""
    lowest = area_top + area_height - height
    return max(area_top, min(top, lowest))


def set_window_height(window, height):
    """Resize the window to `height` and hold it there, so it can't be
    dragged taller or shorter. The hold is loosened first: Windows keeps a
    window inside its old limits and would ignore the new height."""
    window.setMinimumHeight(min(height, window.minimumHeight()))
    window.setMaximumHeight(max(height, window.maximumHeight()))
    window.resize(window.width(), height)
    window.setMinimumHeight(height)
    window.setMaximumHeight(height)


def fit_to_screen(window):
    """Give the window the height its screen has room for, title bar
    included, and move it inside the area above the taskbar if part of it
    is off. Safe before the window is shown: it then guesses the title bar."""
    screen = window.screen()
    if screen is None:
        return
    area = screen.availableGeometry()
    margins = window.frameMargins()
    frame = margins.top() + margins.bottom()
    if window.isVisible() and frame > 0:
        frame_height = frame
    else:
        frame_height = DEFAULT_FRAME_HEIGHT
    height = fitted_height(window.property("fullHeight"), area.height(), frame_height)
    if height != window.height():
        set_window_height(window, height)
    if window.isVisible():
        outer = window.frameGeometry()
        top = on_screen_top(outer.top(), outer.height(), area.top(), area.height())
        if top != outer.top():
            window.setFramePosition(outer.topLeft() + QPoint(0, top - outer.top()))


class ScreenFit(QObject):
    """Fits the window to its screen again whenever that changes: moved to
    another monitor, a new resolution or scaling, a taller taskbar."""

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._screen = None
        window.screenChanged.connect(self._on_screen_changed)
        self._on_screen_changed(window.screen())

    # Connected as this object's own methods, not lambdas, so Qt stops
    # calling them the moment this object is gone.

    def _on_screen_changed(self, screen):
        if self._screen is not None and isValid(self._screen):
            self._screen.availableGeometryChanged.disconnect(self._on_area_changed)
        self._screen = screen
        if screen is not None:
            screen.availableGeometryChanged.connect(self._on_area_changed)
        self.fit()

    def _on_area_changed(self, _area):
        self.fit()

    def fit(self):
        fit_to_screen(self._window)


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
    # A mouse press anywhere in the window, at (x, y) - see FieldFocus.
    windowPressed = Signal(float, float)
    # The settings form's values changed from this side (load, reset).
    formChanged = Signal()
    # Test Link, the cover source line.
    settingsChanged = Signal()
    saved = Signal()
    # A reason to show in the drawer's footer.
    saveFailed = Signal(str)
    # The update check in Settings.
    updateChanged = Signal()

    def __init__(
        self,
        quit_app=None,
        schedule=_schedule,
        updater_options=None,
        update_checks=None,
        **controller_options,
    ):
        """`controller_options` go to the AppController, `updater_options`
        to the Updater - a test passes stand-ins there."""
        super().__init__()
        self._schedule = schedule
        self.controller = AppController(
            schedule=schedule, notify=self.notice, on_change=self.refresh, **controller_options
        )
        # exit(), not quit(): Qt's quit() first asks every window to close
        # and gives up if one refuses - and this window refuses until the
        # worker has finished hiding the overlay, which is when this runs.
        self._quit_app = quit_app or (lambda: QGuiApplication.exit(0))
        # Whether closing the window leaves MapHide running in the tray.
        self.hides_to_tray = False
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
        # Whether this copy looks for updates at all; a Store copy doesn't.
        self._update_checks = checks_for_updates() if update_checks is None else update_checks
        self.updater = Updater(schedule, on_change=self.refresh, **(updater_options or {}))
        self._update = self._update_view()
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
        if cfg.check_updates and self._update_checks:
            self._schedule(UPDATE_CHECK_DELAY_MS, self._check_quietly)

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
        update = self._update_view()
        if update != self._update:
            self._update = update
            self.updateChanged.emit()

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

    def _update_view(self):
        updater = self.updater
        version = updater.release.version if updater.release else ""
        # Whole percent, so the window redraws only when the number moves.
        return (
            updater.state,
            updater.message,
            version,
            round(updater.progress * 100),
            updater.can_install_release,
        )

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

    @Property(str, notify=changed)
    def resetWarning(self):
        return self._view.reset_warning

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
        # The saved settings, never the form: Start doesn't pick up, or
        # save, changes Save hasn't kept. Checked as the form would be, so a
        # missing host gets the same message.
        try:
            self.controller.start(config_from_form(**form_values(self.controller.running_config)))
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
        """The window's close button: hide to the tray, or exit when there
        is no tray to come back from."""
        if self.hides_to_tray and not self.controller.exit_requested:
            self.hideRequested.emit()
        else:
            self.exitApp()

    @Slot()
    def exitApp(self):
        """Stop the worker, letting it hide the overlay, then quit."""
        if self.controller.begin_exit(self._quit_app):
            self.hideRequested.emit()

    def end_session(self, wait_seconds=SESSION_END_WAIT_SECONDS):
        """Windows is signing out, restarting or shutting down, or an
        installer is closing MapHide. Stop the worker and wait here for it
        to hide the overlay: Windows ends the process soon after this
        returns, so the usual exit, which waits in the background, would be
        cut short."""
        self.exitApp()
        self.controller.service.wait(timeout=wait_seconds)

    # The settings drawer.

    @Property("QVariantMap", notify=formChanged)
    def form(self):
        return self._form

    @Property(bool, notify=formChanged)
    def hasUnsavedChanges(self):
        """Whether the form holds anything Save hasn't kept. Spaces around a
        value don't count: Save would drop them."""
        saved = self.controller.running_config
        if self._form == form_values(saved):
            return False
        try:
            return config_from_form(**self._form) != saved
        except ValueError:
            # Half-typed, so it can't be what's saved.
            return True

    @Slot()
    def discardChanges(self):
        """Settings closed without Save: put the saved settings back, theme
        included."""
        if self._form != form_values(self.controller.running_config):
            self._set_form(self.controller.running_config)
            self.clearTest()
            self.refresh()

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
        # The form now shows exactly what was saved (spaces trimmed, say).
        self._set_form(self.controller.running_config)
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

    # Updates.

    @Property(bool, constant=True)
    def updatesShown(self):
        return self._update_checks

    @Property(bool, notify=updateChanged)
    def canInstallUpdate(self):
        return self._update[4]

    @Property(str, constant=True)
    def releasesPage(self):
        return RELEASES_PAGE

    @Property(str, notify=updateChanged)
    def updateState(self):
        return self._update[0]

    @Property(str, notify=updateChanged)
    def updateMessage(self):
        return self._update[1]

    @Property(str, notify=updateChanged)
    def updateVersion(self):
        return self._update[2]

    @Property(int, notify=updateChanged)
    def updatePercent(self):
        return self._update[3]

    def _check_quietly(self):
        """The check when MapHide opens: a new version is noted in the field
        log, and a failure (no internet, say) says nothing."""
        self.updater.check(on_found=self._update_found, quiet=True)

    def _update_found(self, release):
        self.controller.add_history(
            human_ts(),
            f"MapHide {release.version} is available.",
            HISTORY_UPDATE_AVAILABLE,
            release.version,
        )
        self.refresh()

    @Slot()
    def checkForUpdates(self):
        if self._update_checks:
            self.updater.check()

    @Slot()
    def clearUpdateResult(self):
        self.updater.clear_latest()

    @Slot()
    def installUpdate(self):
        """Download the new version and hand over to its installer, which
        closes MapHide, updates it and opens it again."""
        self.updater.install(on_started=self.exitApp)


def load_fonts():
    for font in sorted(FONTS_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(font))


class FieldFocus(QObject):
    """Reports every mouse press in the window, before whatever was clicked
    gets it, so the window can let a text field give up the keyboard when
    you click anywhere else - as fields do in other Windows apps. Qt Quick
    otherwise keeps a field focused until something asks for focus, so a
    field would go on taking typed keys - your hotkey among them - after
    you'd clicked away from it. Main.qml decides; see releaseFieldUnlessAt."""

    def __init__(self, window, on_press):
        super().__init__(window)
        self._on_press = on_press
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            position = event.scenePosition()
            self._on_press(position.x(), position.y())
        # Never swallow the click: whatever was clicked still gets it.
        return False


def build_window(backend):
    """Load the window for `backend`, still hidden. Returns (engine, window,
    QML warnings); window is None if it failed to load."""
    warnings = []
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_PATH)))
    roots = engine.rootObjects()
    window = roots[0] if roots else None
    if window is not None:
        window._field_focus = FieldFocus(window, backend.windowPressed.emit)
        set_window_height(window, window.property("fullHeight"))
    return engine, window, warnings


def ends_session(message, wparam):
    """Whether a Windows message says the session is ending for real: a
    WM_ENDSESSION that wasn't cancelled. Sign-out, restart and shutdown send
    it, and so does an installer closing MapHide through Windows' Restart
    Manager."""
    return message == WM_ENDSESSION and bool(wparam)


class SessionEnd(QAbstractNativeEventFilter):
    """Calls `on_end` once when Windows ends the session. Qt alone treats
    this like the window's close button, which hides MapHide to the tray -
    and Windows then ends it without the overlay being hidden."""

    def __init__(self, on_end):
        super().__init__()
        self._on_end = on_end
        self._ended = False

    def nativeEventFilter(self, event_type, message):
        if not self._ended and bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if ends_session(msg.message, msg.wParam):
                self._ended = True
                self._on_end()
        # Qt still handles the message as it normally would.
        return False, 0


class CommandServer(QObject):
    """Listens for commands from a second launch of MapHide - see
    single_instance.send_command. "show" brings the window forward, "quit"
    exits the way Exit in the tray does."""

    def __init__(self, name, on_show, on_quit):
        super().__init__()
        self._handlers = {COMMAND_SHOW: on_show, COMMAND_QUIT: on_quit}
        self._connections = set()
        self._server = QLocalServer(self)
        # Only this Windows user can connect.
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._accept)
        self.listening = self._server.listen(name)

    # Connected as this object's own methods, not lambdas, so Qt stops
    # calling them the moment this object is gone.

    def _accept(self):
        while self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            self._connections.add(connection)
            connection.readyRead.connect(self._on_ready_read)
            connection.disconnected.connect(self._on_disconnected)
            self._read(connection)

    def _on_ready_read(self):
        self._read(self.sender())

    def _on_disconnected(self):
        # A second launch writes one line and hangs up at once, so read
        # whatever is left before letting the connection go.
        connection = self.sender()
        self._read(connection)
        self._connections.discard(connection)
        if isValid(connection):
            connection.deleteLater()

    def _read(self, connection):
        # Qt may already have deleted a connection that hung up.
        if connection is None or not isValid(connection):
            return
        while connection.canReadLine():
            line = bytes(connection.readLine(64)).decode("ascii", "replace").strip()
            handler = self._handlers.get(line)
            if handler is not None:
                handler()

    def close(self):
        self._server.close()
        for connection in list(self._connections):
            if isValid(connection):
                connection.abort()
        self._connections.clear()


class TrayIcon:
    """The notification-area icon: click it, or Show, to bring the window
    back; Exit quits."""

    def __init__(self, icon, on_show, on_exit):
        self._icon = QSystemTrayIcon(icon)
        self._icon.setToolTip(APP_NAME)
        self._menu = QMenu()
        show = QAction("Show", self._menu)
        show.triggered.connect(on_show)
        exit_action = QAction("Exit", self._menu)
        exit_action.triggered.connect(on_exit)
        self._menu.addAction(show)
        self._menu.addAction(exit_action)
        self._menu.setDefaultAction(show)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(
            lambda reason: (
                on_show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
            )
        )

    def show(self):
        self._icon.show()

    def hide(self):
        self._icon.hide()


def main():
    set_app_id(APP_USER_MODEL_ID)
    app = QApplication(sys.argv)
    # The tray keeps MapHide running with no window open.
    app.setQuitOnLastWindowClosed(False)
    icon = QIcon(str(ICON_ICO_PATH))
    app.setWindowIcon(icon)
    load_fonts()

    backend = Backend()
    engine, window, _warnings = build_window(backend)
    if window is None:
        return 1

    def paint_title_bar():
        apply_dark_title_bar(int(window.winId()), backend.theme["title_bar"])

    def show_window():
        if backend.controller.exit_requested:
            # A late tray click while MapHide is closing.
            return
        window.showNormal()
        window.raise_()
        window.requestActivate()

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(icon, on_show=show_window, on_exit=backend.exitApp)
        tray.show()
        backend.hides_to_tray = True

    # A second launch brings this window forward, and `MapHide.exe --quit`
    # closes MapHide properly; both arrive here.
    commands = CommandServer(command_pipe_name(), on_show=show_window, on_quit=backend.exitApp)
    session_end = SessionEnd(backend.end_session)
    app.installNativeEventFilter(session_end)

    backend.themeChanged.connect(paint_title_bar)
    backend.hideRequested.connect(window.hide)
    backend.load()
    if tray is None:
        backend.notice(NO_TRAY)
    # Shown only now, so it appears with its theme's title bar already set.
    paint_title_bar()
    screen_fit = ScreenFit(window)
    window.show()
    # Again, now that Windows has said how tall the title bar really is.
    screen_fit.fit()
    result = app.exec()
    commands.close()
    app.removeNativeEventFilter(session_end)
    if tray is not None:
        tray.hide()
    # Tear the window down while the backend it reads from still exists.
    del engine
    return result


def bundle_problems(icon_path=ICON_ICO_PATH):
    """Pieces the app needs that opening the window doesn't prove are there:
    HTTPS, which the update check uses, and the window icon. Without HTTPS
    every check would just say GitHub can't be reached. Needs a running
    QApplication. Returns what's wrong, empty when nothing is."""
    problems = []
    try:
        # Imported here: a missing piece should fail this check, not stop
        # MapHide from opening.
        import ssl

        ssl.create_default_context()
    except Exception:
        problems.append("HTTPS support did not load, so update checks would fail")
    if QIcon(str(icon_path)).pixmap(32, 32).isNull():
        problems.append("the window icon did not load")
    return problems


def selftest():
    """Build the window without showing it, and check that it loaded with
    its map image and fonts. Returns an exit code: 0 when all is well. The
    build workflow runs this against the packaged app, so a Qt piece left
    out of the bundle fails there instead of on someone's PC."""
    app = QApplication(sys.argv)
    load_fonts()
    backend = Backend()
    engine, window, warnings = build_window(backend)
    problems = list(warnings)
    if window is None:
        problems.append("the window did not load")
    else:
        map_image = window.findChild(QObject, "mapImage")
        # A loaded image has a size; one that failed to decode has none.
        if map_image is None or not map_image.property("implicitWidth"):
            problems.append("the map image did not load")
    missing_fonts = set(FONT_FAMILIES) - set(QFontDatabase.families())
    if missing_fonts:
        problems.append(f"fonts not loaded: {', '.join(sorted(missing_fonts))}")
    problems.extend(bundle_problems())
    for problem in problems:
        print(problem, file=sys.stderr)
    del engine
    del app
    return 1 if problems else 0
