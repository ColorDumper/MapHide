"""Tests for the controller: what the settings window asks of MapHide, checked
without a window, a worker thread or a real timer."""

import queue
import threading

import pytest

from maphide.config import AppConfig, default_config
from maphide.controller import (
    CHECK_FAILED,
    EXIT_WAIT_CEILING_MS,
    HISTORY_LINE_COUNT,
    RESTART_POLL_INTERVAL_MS,
    AppController,
    help_text,
    status_line,
)
from maphide.obs import ConnectionCheck
from maphide.overlay import CONNECTED, STOPPED, STOPPING, ObsSnapshot, ServiceStatus


def make_config(**overrides):
    values = {
        "host": "10.0.0.2",
        "port": 4455,
        "password": "",
        "scene_item_name": "Overlay",
        **overrides,
    }
    return AppConfig(**values)


class FakeService:
    """Stands in for MapHideService. Stopping only asks: the test decides
    when the worker has actually finished by calling finish_stopping()."""

    def __init__(self):
        self.events = queue.Queue()
        self.is_running = False
        self.status = ServiceStatus(STOPPED, "Idle")
        self.snapshot = ObsSnapshot()
        self.manual_inputs = []
        self.started_with = []
        self.stop_requests = 0

    def start(self, cfg):
        if self.is_running:
            raise RuntimeError("Service is already running.")
        self.is_running = True
        self.started_with.append(cfg)

    def stop(self):
        self.stop_requests += 1
        if self.is_running:
            self.status = ServiceStatus(STOPPING, "Stopping...")

    def set_manual_input(self, down):
        self.manual_inputs.append(down)

    def finish_stopping(self):
        self.is_running = False
        self.status = ServiceStatus(STOPPED, "MapHide stopped.")

    def emit(self, message, history=True):
        self.events.put(
            {"kind": "status", "message": message, "timestamp": "t", "history": history}
        )


class ManualScheduler:
    """Collects scheduled callbacks; the test runs them when it chooses."""

    def __init__(self):
        self.pending = []
        self.elapsed_ms = 0

    def __call__(self, milliseconds, callback):
        self.pending.append((milliseconds, callback))

    def run_next(self):
        milliseconds, callback = self.pending.pop(0)
        self.elapsed_ms += milliseconds
        callback()


class Harness:
    def __init__(self):
        self.service = FakeService()
        self.schedule = ManualScheduler()
        self.saved = []
        self.notices = []
        self.changes = 0
        self.controller = AppController(
            schedule=self.schedule,
            service=self.service,
            save=self.saved.append,
            notify=self.notices.append,
            on_change=self._changed,
        )

    def _changed(self):
        self.changes += 1


@pytest.fixture
def h():
    return Harness()


# Status and help wording.


def test_the_status_line_shows_the_services_own_wording():
    status = ServiceStatus(CONNECTED, "Connected to OBS.")

    assert status_line(status, restart_pending=False) == "Connected to OBS."


def test_the_status_line_hides_the_stop_and_start_of_a_settings_restart():
    status = ServiceStatus(STOPPING, "Stopping...")

    assert status_line(status, restart_pending=True) == "Applying settings..."


def test_help_text_describes_hold_mode():
    assert help_text(make_config(hotkey="M")) == (
        "Hold M to show the overlay. Release M to hide it."
    )


def test_help_text_describes_toggle_mode():
    assert help_text(make_config(hotkey="M", toggle_mode=True, hide_hotkey="ESC")) == (
        "Press M to show the overlay. Press ESC to hide it."
    )


# Loading.


def test_loading_uses_the_saved_settings(h):
    cfg, loaded = h.controller.load(load=lambda: make_config(hotkey="M"))

    assert loaded is True
    assert cfg.hotkey == "M"
    assert h.controller.running_config.hotkey == "M"


@pytest.mark.parametrize("error", [OSError("denied"), ValueError("bad"), KeyError("host")])
def test_loading_falls_back_to_defaults_when_the_file_cannot_be_used(h, error):
    def failing_load():
        raise error

    cfg, loaded = h.controller.load(load=failing_load)

    assert loaded is False
    assert cfg == default_config()


def test_loading_replaces_values_the_form_cannot_show(h):
    cfg, _ = h.controller.load(load=lambda: make_config(hotkey="?", hide_delay_ms=9999))

    assert cfg.hotkey == "G"
    assert cfg.hide_delay_ms == 400


# Starting and stopping.


def test_start_saves_the_settings_then_starts_the_worker_with_them(h):
    cfg = make_config()

    h.controller.start(cfg)

    assert h.saved == [cfg]
    assert h.service.started_with == [cfg]
    assert (h.controller.can_start, h.controller.can_stop) == (False, True)


def test_start_does_not_run_the_worker_when_saving_fails(h):
    def failing_save(_cfg):
        raise OSError("denied")

    controller = AppController(schedule=h.schedule, service=h.service, save=failing_save)

    with pytest.raises(OSError):
        controller.start(make_config())
    assert h.service.started_with == []


def test_stop_asks_the_worker_to_stop(h):
    h.controller.start(make_config())

    h.controller.stop()

    assert h.service.stop_requests == 1


def test_buttons_follow_the_worker_once_it_has_actually_stopped(h):
    h.controller.start(make_config())
    h.controller.stop()
    assert h.controller.can_start is False

    h.service.finish_stopping()

    assert (h.controller.can_start, h.controller.can_stop) == (True, False)


# Saving.


def test_saving_while_stopped_records_it_without_starting_anything(h):
    cfg = make_config(hotkey="M")

    h.controller.save(cfg)

    assert h.saved == [cfg]
    assert h.controller.running_config == cfg
    assert h.controller.history_lines[-1].endswith("Config saved.")
    assert h.service.started_with == []
    assert h.changes == 1


def test_a_failed_save_changes_nothing(h):
    def failing_save(_cfg):
        raise OSError("denied")

    controller = AppController(schedule=h.schedule, service=h.service, save=failing_save)

    with pytest.raises(OSError):
        controller.save(make_config(hotkey="M"))
    assert controller.running_config == default_config()
    assert controller.history_lines == []


def test_saving_while_running_restarts_the_worker_once_the_old_one_has_stopped(h):
    h.controller.start(make_config())
    new_cfg = make_config(hotkey="M")

    h.controller.save(new_cfg)

    assert h.controller.restart_pending is True
    assert h.controller.status_text == "Applying settings..."
    assert (h.controller.can_start, h.controller.can_stop) == (False, False)
    h.schedule.run_next()
    assert h.service.started_with == [make_config()], "must wait for the old worker"

    h.service.finish_stopping()
    h.schedule.run_next()

    assert h.service.started_with == [make_config(), new_cfg]
    assert h.controller.restart_pending is False


def test_saving_twice_during_one_restart_starts_once_with_the_newest_settings(h):
    h.controller.start(make_config())
    h.controller.save(make_config(hotkey="M"))
    h.controller.save(make_config(hotkey="N"))

    assert h.service.stop_requests == 1
    h.service.finish_stopping()
    h.schedule.run_next()

    assert h.service.started_with == [make_config(), make_config(hotkey="N")]
    assert h.schedule.pending == []


def test_a_restart_waits_as_long_as_the_old_worker_needs(h):
    h.controller.start(make_config())
    h.controller.save(make_config(hotkey="M"))

    for _ in range(1000):
        h.schedule.run_next()

    assert h.controller.restart_pending is True
    assert len(h.schedule.pending) == 1


def test_a_restart_that_cannot_start_the_new_worker_says_so(h):
    h.controller.start(make_config())
    h.controller.save(make_config(hotkey="M"))
    h.service.finish_stopping()

    def refuse_to_start(_cfg):
        raise RuntimeError("Service is already running.")

    h.service.start = refuse_to_start
    h.schedule.run_next()

    assert h.notices == ["Service is already running."]
    assert h.controller.restart_pending is False


def test_restoring_defaults_saves_and_returns_them(h):
    h.controller.save(make_config(hotkey="M"))

    cfg = h.controller.restore_defaults()

    assert cfg == default_config()
    assert h.saved[-1] == default_config()
    assert h.controller.running_config == default_config()
    assert h.controller.history_lines[-1].endswith("Defaults restored.")


# History.


def test_events_marked_for_history_are_kept(h):
    h.service.emit("Connected to OBS.")
    h.service.emit("Reconnecting... 1s", history=False)

    assert h.controller.drain_events() is True
    assert h.controller.history_lines == ["t  Connected to OBS."]


def test_draining_with_nothing_new_reports_no_change(h):
    h.service.emit("Reconnecting... 1s", history=False)

    assert h.controller.drain_events() is False


def test_history_keeps_only_the_newest_lines(h):
    for index in range(HISTORY_LINE_COUNT + 3):
        h.controller.add_history("t", f"line {index}")

    assert len(h.controller.history_lines) == HISTORY_LINE_COUNT
    assert h.controller.history_lines[0] == "t  line 3"
    assert h.controller.history_lines[-1] == f"t  line {HISTORY_LINE_COUNT + 2}"


# Exit.


def test_exit_waits_for_the_worker_to_finish_before_finishing(h):
    finished = []
    h.controller.start(make_config())

    assert h.controller.begin_exit(lambda: finished.append(True)) is True
    h.schedule.run_next()
    assert finished == []

    h.service.finish_stopping()
    h.schedule.run_next()

    assert finished == [True]


def test_exit_finishes_at_once_when_nothing_is_running(h):
    finished = []

    h.controller.begin_exit(lambda: finished.append(True))

    assert finished == [True]


def test_exit_gives_up_waiting_at_the_ceiling(h):
    finished = []
    h.controller.start(make_config())
    h.controller.begin_exit(lambda: finished.append(True))

    while not finished:
        h.schedule.run_next()

    assert h.schedule.elapsed_ms == EXIT_WAIT_CEILING_MS
    assert EXIT_WAIT_CEILING_MS % RESTART_POLL_INTERVAL_MS == 0


def test_a_second_exit_request_is_ignored(h):
    finished = []
    h.controller.start(make_config())
    h.controller.begin_exit(lambda: finished.append(1))

    assert h.controller.begin_exit(lambda: finished.append(2)) is False
    assert h.service.stop_requests == 1


def test_exiting_during_a_restart_does_not_start_the_new_worker(h):
    finished = []
    h.controller.start(make_config())
    h.controller.save(make_config(hotkey="M"))

    h.controller.begin_exit(lambda: finished.append(True))
    h.service.finish_stopping()
    while h.schedule.pending:
        h.schedule.run_next()

    assert h.service.started_with == [make_config()]
    assert h.service.is_running is False
    assert finished == [True]


def test_the_snapshot_comes_straight_from_the_worker(h):
    h.service.snapshot = ObsSnapshot(scene="Gameplay", covered=True, source_scene_count=3)

    assert h.controller.snapshot == ObsSnapshot(
        scene="Gameplay", covered=True, source_scene_count=3
    )


# The test button and the connection check.


def test_the_test_button_only_works_while_connected(h):
    assert h.controller.can_test is False
    h.controller.start(make_config())
    assert h.controller.can_test is False, "started, but not connected yet"

    h.service.status = ServiceStatus(CONNECTED, "Connected to OBS.")
    assert h.controller.can_test is True

    h.controller.save(make_config(hotkey="M"))
    assert h.controller.can_test is False, "not while settings are being applied"


def test_the_test_button_is_passed_to_the_worker(h):
    h.controller.set_manual_input(True)
    h.controller.set_manual_input(False)

    assert h.service.manual_inputs == [True, False]


def run_check(h, check, host="10.0.0.2", port="4455", source=" Overlay "):
    results = []
    controller = AppController(schedule=h.schedule, service=h.service, check=check)
    started = controller.check_connection(host, port, "pw", source, results.append)
    return controller, results, started


def finish_check(h, controller):
    controller._check_thread.join(timeout=5)
    while h.schedule.pending:
        h.schedule.run_next()


def test_a_connection_check_reports_back_on_the_windows_thread(h):
    calls = []

    def check(host, port, password, source_name):
        calls.append((host, port, password, source_name))
        return ConnectionCheck(ok=True, source_scene_count=2)

    controller, results, started = run_check(h, check)
    assert started is True
    assert controller.checking_connection is True
    finish_check(h, controller)

    assert calls == [("10.0.0.2", 4455, "pw", "Overlay")]
    assert results == [ConnectionCheck(ok=True, source_scene_count=2)]
    assert controller.checking_connection is False


def test_a_connection_check_with_an_unusable_port_says_so_without_trying(h):
    controller = AppController(schedule=h.schedule, service=h.service, check=None)

    with pytest.raises(ValueError, match="OBS Port must be a number."):
        controller.check_connection("10.0.0.2", "44a5", "", "", lambda _result: None)
    assert controller.checking_connection is False


def test_only_one_connection_check_runs_at_a_time(h):
    release = threading.Event()

    def slow_check(*_args):
        release.wait(timeout=5)
        return ConnectionCheck(ok=True)

    controller, results, _ = run_check(h, slow_check)
    assert controller.check_connection("10.0.0.2", "4455", "", "", results.append) is False

    release.set()
    finish_check(h, controller)
    assert results == [ConnectionCheck(ok=True)]


def test_a_connection_check_that_breaks_still_reports_back(h):
    def broken_check(*_args):
        raise RuntimeError("bug")

    controller, results, _ = run_check(h, broken_check)
    finish_check(h, controller)

    assert results == [ConnectionCheck(ok=False, message=CHECK_FAILED)]
    assert controller.checking_connection is False
