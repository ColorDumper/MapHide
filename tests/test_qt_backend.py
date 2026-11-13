"""The Qt window's backend: what it does with clicks and typing, checked
under Qt but without a window, a worker thread or OBS."""

import pytest

pytest.importorskip("PySide6")

from test_controller import FakeService, ManualScheduler, make_config  # noqa: E402

from maphide.controller import HISTORY_NOTICE  # noqa: E402
from maphide.hotkeys import SHOW_KEY_HELP  # noqa: E402
from maphide.obs import ConnectionCheck  # noqa: E402
from maphide.overlay import CONNECTED, CONNECTING, ServiceStatus  # noqa: E402
from maphide.qt.app import WM_ENDSESSION, Backend, ends_session  # noqa: E402
from maphide.qt.view import QT_KEY_ESCAPE, SCREEN_CONNECTING, SOURCE_FOLLOWS  # noqa: E402
from maphide.updates import Release  # noqa: E402


@pytest.fixture(autouse=True)
def _qt(qt_app):
    return qt_app


class StartingService(FakeService):
    """Says it is connecting the moment it starts, as the real one does."""

    def start(self, cfg):
        super().start(cfg)
        self.status = ServiceStatus(CONNECTING, "Starting...")

    def wait(self, timeout=None):
        self.waits.append(timeout)

    @property
    def waits(self):
        return self.__dict__.setdefault("_waits", [])


class Harness:
    def __init__(self):
        self.service = StartingService()
        self.schedule = ManualScheduler()
        self.saved = []
        self.checks = []
        self.check_result = ConnectionCheck(ok=True, source_scene_count=3)
        self.quits = 0
        self.latest = Release("0.2.0")
        self.installers = []
        self.backend = Backend(
            quit_app=self._quit,
            schedule=self.schedule,
            update_checks=True,
            updater_options={
                "current": "0.2.6",
                "fetch": lambda: self.latest,
                "download": lambda release, folder, progress: "setup.exe",
                "launch": self.installers.append,
                "can_install": True,
                # Never the real download folder.
                "folder": "downloads",
                "verify": lambda path, sha256: None,
                "clean": lambda folder: None,
            },
            service=self.service,
            save=self.saved.append,
            check=self._check,
        )
        self.lines = []
        self.backend.lineAdded.connect(lambda *line: self.lines.append(line))
        self.save_failures = []
        self.backend.saveFailed.connect(self.save_failures.append)
        self.saves = []
        self.backend.saved.connect(lambda: self.saves.append(True))
        self.hides = []
        self.backend.hideRequested.connect(lambda: self.hides.append(True))

    def _quit(self):
        self.quits += 1

    def _check(self, host, port, password, source):
        self.checks.append((host, port, password, source))
        return self.check_result

    def load(self, load):
        self.backend.load(load=load)
        self.backend._poll_timer.stop()

    def run_updater(self):
        """Run what's scheduled, letting the updater's thread finish each
        time it has one running, until nothing is left."""
        while self.schedule.pending:
            if self.backend.updater.thread is not None:
                self.backend.updater.thread.join(timeout=5)
            self.schedule.run_next()

    def run_check(self):
        """Let the connection check's thread finish and its result land."""
        self.backend.controller._check_thread.join(timeout=5)
        while self.schedule.pending:
            self.schedule.run_next()


@pytest.fixture
def h():
    return Harness()


def fill_form(backend, **values):
    defaults = {"host": "10.0.0.2", "port": "4455", "scene_item_name": "Overlay"}
    for name, value in {**defaults, **values}.items():
        backend.setField(name, value)


def save_form(backend, **values):
    """Fill the form and press Save: Start runs the saved settings."""
    fill_form(backend, **values)
    backend.save()


def test_loading_fills_the_form_from_the_saved_settings(h):
    h.load(lambda: make_config(host="10.0.0.9", port=4456))

    assert h.backend.form["host"] == "10.0.0.9"
    assert h.backend.form["port"] == "4456"


def test_settings_that_cant_be_read_are_reported_in_the_field_log(h):
    def broken():
        raise ValueError("bad json")

    h.load(broken)

    assert h.lines[-1][1].startswith("> Settings couldn't be read")


def run_scheduled(h):
    while h.schedule.pending:
        h.schedule.run_next()


def test_connect_on_startup_starts_maphide_with_the_saved_settings(h):
    h.load(lambda: make_config(host="10.0.0.9", auto_connect=True, check_updates=False))
    assert h.service.started_with == []

    run_scheduled(h)

    assert [cfg.host for cfg in h.service.started_with] == ["10.0.0.9"]


def test_connect_on_startup_ignores_an_edit_made_before_it_starts(h):
    h.load(lambda: make_config(host="10.0.0.9", auto_connect=True, check_updates=False))
    fill_form(h.backend, host="10.0.0.5")

    run_scheduled(h)

    assert [cfg.host for cfg in h.service.started_with] == ["10.0.0.9"]


def test_maphide_waits_for_start_when_connect_on_startup_is_off(h):
    h.load(lambda: make_config(auto_connect=False, check_updates=False))

    run_scheduled(h)

    assert h.service.started_with == []


# The settings form.


def test_picking_a_theme_restyles_the_window_at_once(h):
    restyles = []
    h.backend.themeChanged.connect(lambda: restyles.append(True))

    h.backend.setField("theme", "legacy")

    assert h.backend.themeName == "legacy"
    assert restyles


def test_the_hide_delay_from_the_slider_is_a_whole_number(h):
    h.backend.setField("hide_delay_ms", 130.0)

    assert h.backend.form["hide_delay_ms"] == 130
    assert isinstance(h.backend.form["hide_delay_ms"], int)


def test_an_unknown_field_is_ignored(h):
    h.backend.setField("not_a_setting", "x")

    assert "not_a_setting" not in h.backend.form


def test_a_captured_key_goes_into_the_form(h):
    assert h.backend.captureKey("show", ord("M"), False) == ""
    assert h.backend.form["hotkey"] == "M"

    assert h.backend.captureKey("hide", QT_KEY_ESCAPE, False) == ""
    assert h.backend.form["hide_hotkey"] == "ESC"


def test_a_key_that_cant_be_used_explains_and_changes_nothing(h):
    assert h.backend.captureKey("show", QT_KEY_ESCAPE, False) == SHOW_KEY_HELP
    assert h.backend.form["hotkey"] == "G"


# Save and reset.


def test_saving_writes_the_form_and_says_so(h):
    fill_form(h.backend)

    h.backend.save()

    assert h.saved[-1].host == "10.0.0.2"
    assert h.saves == [True]
    assert h.lines[-1][1] == "> settings saved"


def test_saving_a_form_that_isnt_ready_explains_why(h):
    fill_form(h.backend, host="")

    h.backend.save()

    assert h.saved == []
    assert h.save_failures == ["OBS Host is required."]


def test_a_settings_file_that_cant_be_written_is_reported_plainly(h):
    def refuse(_cfg):
        raise PermissionError(13, "Permission denied", r"C:\Users\someone\AppData\x")

    h.backend.controller._save = refuse
    fill_form(h.backend)

    h.backend.save()

    assert h.save_failures == ["Couldn't save settings: Permission denied"]


def test_reset_puts_the_defaults_back_in_the_form(h):
    fill_form(h.backend)

    h.backend.resetDefaults()

    assert h.backend.form["host"] == ""
    assert h.lines[-1][1] == "> defaults restored"


# Start, stop and the test button.


def test_start_with_saved_settings_that_arent_ready_says_why_in_the_field_log(h):
    h.backend.primary()

    assert h.service.started_with == []
    assert h.lines[-1][1:] == ("> OBS Host is required.", "warning")
    assert h.backend.controller.history[-1].code == HISTORY_NOTICE


def test_start_that_maphide_refuses_says_why_in_the_field_log(h):
    save_form(h.backend)

    def refuse(cfg):
        raise RuntimeError("Service is already running.")

    h.service.start = refuse
    h.backend.primary()

    assert h.lines[-1][1:] == ("> Service is already running.", "warning")


def test_start_runs_the_worker_with_the_saved_settings(h):
    save_form(h.backend, hotkey="M")

    h.backend.primary()

    assert h.service.started_with[-1].hotkey == "M"
    assert h.backend.primaryIsStop


def test_start_ignores_and_never_saves_unsaved_changes(h):
    save_form(h.backend, hotkey="M")
    h.saved.clear()
    h.backend.setField("hotkey", "K")

    h.backend.primary()

    assert h.service.started_with[-1].hotkey == "M"
    assert h.saved == []


# Unsaved changes.


def test_closing_settings_puts_the_saved_settings_back(h):
    save_form(h.backend, hotkey="M")
    h.backend.setField("host", "192.168.1.50")
    h.backend.setField("hotkey", "K")

    h.backend.discardChanges()

    assert h.backend.form["host"] == "10.0.0.2"
    assert h.backend.form["hotkey"] == "M"
    assert h.backend.hasUnsavedChanges is False


def test_closing_settings_puts_the_saved_theme_back(h):
    save_form(h.backend, theme="field")
    h.backend.setField("theme", "legacy")
    assert h.backend.themeName == "legacy"

    h.backend.discardChanges()

    assert h.backend.themeName == "field"


def test_a_change_counts_as_unsaved_until_saved(h):
    save_form(h.backend)
    assert h.backend.hasUnsavedChanges is False

    h.backend.setField("hide_delay_ms", 650)
    assert h.backend.hasUnsavedChanges is True

    h.backend.save()
    assert h.backend.hasUnsavedChanges is False


def test_changing_a_field_back_is_not_an_unsaved_change(h):
    save_form(h.backend)

    h.backend.setField("host", "192.168.1.50")
    h.backend.setField("host", "10.0.0.2")

    assert h.backend.hasUnsavedChanges is False


def test_spaces_around_a_value_are_not_an_unsaved_change(h):
    save_form(h.backend)

    h.backend.setField("host", "  10.0.0.2 ")

    assert h.backend.hasUnsavedChanges is False


def test_a_captured_key_is_an_unsaved_change(h):
    save_form(h.backend)

    h.backend.captureKey("show", ord("K"), False)

    assert h.backend.hasUnsavedChanges is True


def test_reset_leaves_nothing_unsaved(h):
    save_form(h.backend)
    h.backend.setField("host", "192.168.1.50")

    h.backend.resetDefaults()

    assert h.backend.hasUnsavedChanges is False


def test_stop_stops_the_worker(h):
    save_form(h.backend)
    h.backend.primary()

    h.backend.primary()

    assert h.service.stop_requests == 1


def test_the_test_button_presses_and_releases(h):
    h.backend.holdDown()
    h.backend.holdUp()

    assert h.service.manual_inputs == [True, False]


def test_a_settings_change_while_running_reads_as_connecting(h):
    save_form(h.backend)
    h.backend.primary()
    h.service.status = ServiceStatus(CONNECTED, "Connected to OBS.")

    fill_form(h.backend, hotkey="M")
    h.backend.save()

    assert h.backend.screen == SCREEN_CONNECTING


# Test Link.


def test_test_link_reports_the_scenes_carrying_the_source(h):
    fill_form(h.backend)

    h.backend.testLink()
    assert h.backend.testState == "busy"
    h.run_check()

    assert h.checks == [("10.0.0.2", 4455, "", "Overlay")]
    assert h.backend.testState == "ok"
    assert h.backend.sourceText == f"Found in 3 scenes. {SOURCE_FOLLOWS}"


def test_test_link_with_no_host_fails_at_once(h):
    fill_form(h.backend, host="")

    h.backend.testLink()

    assert h.checks == []
    assert h.backend.testState == "failed"
    assert h.backend.testMessage == "OBS Host is required."


def test_a_failed_test_link_shows_the_reason(h):
    h.check_result = ConnectionCheck(ok=False, message="Failed to connect to OBS.")
    fill_form(h.backend)

    h.backend.testLink()
    h.run_check()

    assert h.backend.testState == "failed"
    assert h.backend.testMessage == "Failed to connect to OBS."


def test_a_renamed_source_forgets_the_old_scene_count(h):
    fill_form(h.backend)
    h.backend.testLink()
    h.run_check()

    h.backend.setField("scene_item_name", "Other")

    assert "Found in" not in h.backend.sourceText


# Closing.


def test_closing_hides_the_window_and_quits_once_the_worker_is_done(h):
    save_form(h.backend)
    h.backend.primary()

    h.backend.requestClose()
    assert h.hides == [True]
    assert h.quits == 0

    h.service.finish_stopping()
    h.schedule.run_next()
    assert h.quits == 1


def test_closing_twice_is_one_exit(h):
    h.backend.requestClose()
    h.backend.requestClose()

    assert h.hides == [True]
    assert h.quits == 1


def test_with_a_tray_closing_the_window_keeps_maphide_running(h):
    h.backend.hides_to_tray = True

    h.backend.requestClose()

    assert h.hides == [True]
    assert h.quits == 0
    assert not h.backend.controller.exit_requested


def test_exit_from_the_tray_quits(h):
    h.backend.hides_to_tray = True

    h.backend.exitApp()

    assert h.quits == 1


# Windows ending the session.


def test_a_session_end_stops_the_worker_and_waits_for_it_here(h):
    save_form(h.backend)
    h.backend.primary()

    h.backend.end_session(wait_seconds=3)

    assert h.service.stop_requests == 1
    assert h.service.waits == [3]
    assert h.hides == [True]


def test_only_a_real_session_end_counts():
    assert ends_session(WM_ENDSESSION, 1)
    # Windows sends it with wParam 0 when the sign-out was cancelled.
    assert not ends_session(WM_ENDSESSION, 0)
    assert not ends_session(0x0011, 1)  # WM_QUERYENDSESSION only asks


# Updates.

NEW_RELEASE = Release(
    "0.3.0", "https://github.com/ColorDumper/MapHide/releases/download/x", 1, "0" * 64
)


def test_opening_maphide_checks_for_updates_and_notes_a_new_one(h):
    h.latest = NEW_RELEASE
    h.load(lambda: make_config())

    h.run_updater()

    assert h.backend.updateState == "available"
    assert h.backend.updateVersion == "0.3.0"
    assert h.lines[-1][1] == "> update available · v0.3.0 · see settings"


def test_no_check_at_startup_when_it_is_turned_off(h):
    h.latest = NEW_RELEASE
    h.load(lambda: make_config(check_updates=False))

    while h.schedule.pending:
        h.schedule.run_next()

    assert h.backend.updateState == "idle"


def test_old_downloads_are_cleared_out_even_with_checks_turned_off():
    cleaned = []
    harness = Harness()
    harness.backend.updater._clean = cleaned.append
    harness.load(lambda: make_config(check_updates=False))
    assert cleaned == []

    run_scheduled(harness)
    harness.backend.updater.tidy_thread.join(timeout=5)

    assert cleaned == ["downloads"]


def test_a_store_copy_leaves_the_download_folder_alone():
    cleaned = []
    harness = Harness()
    harness.backend._update_checks = False
    harness.backend.updater._clean = cleaned.append
    harness.load(lambda: make_config(check_updates=False))

    run_scheduled(harness)

    assert harness.backend.updater.tidy_thread is None
    assert cleaned == []


def test_a_store_copy_never_checks():
    harness = Harness()
    harness.backend._update_checks = False
    harness.load(lambda: make_config())

    while harness.schedule.pending:
        harness.schedule.run_next()
    harness.backend.checkForUpdates()

    assert harness.backend.updateState == "idle"


def test_check_now_says_when_maphide_is_up_to_date(h):
    h.backend.checkForUpdates()
    h.run_updater()

    assert h.backend.updateState == "latest"


def test_an_installed_copy_offers_to_install_a_release_with_a_setup_file(h):
    h.latest = NEW_RELEASE
    h.backend.checkForUpdates()
    h.run_updater()

    assert h.backend.canInstallUpdate is True


def test_a_release_without_a_setup_file_sends_you_to_the_download_page(h):
    h.latest = Release("0.3.0")
    h.backend.checkForUpdates()
    h.run_updater()

    assert h.backend.updateState == "available"
    assert h.backend.canInstallUpdate is False


def test_update_runs_the_installer_and_closes_maphide(h):
    h.latest = NEW_RELEASE
    h.backend.checkForUpdates()
    h.run_updater()

    h.backend.installUpdate()
    h.run_updater()

    assert h.installers == ["setup.exe"]
    assert h.backend.updateState == "installing"
    assert h.hides == [True]
    assert h.quits == 1
