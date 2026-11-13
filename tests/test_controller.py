"""Tests for the controller: what the settings window asks of MapHide, checked
without a window, a worker thread or a real timer."""

import queue
import threading

import pytest

from maphide.config import AppConfig, default_config
from maphide.controller import (
    CHECK_FAILED,
    EXIT_WAIT_CEILING_MS,
    HISTORY_DEFAULTS_RESTORED,
    HISTORY_LINE_COUNT,
    HISTORY_SETTINGS_SAVED,
    RESTART_POLL_INTERVAL_MS,
    SUBJECT_RELINKING,
    AppController,
    HistoryEntry,
)
from maphide.obs import ConnectionCheck
from maphide.overlay import (
    CONNECTED,
    EVENT_CONNECT_FAILED,
    EVENT_CONNECTED,
    EVENT_CONNECTING,
    EVENT_OVERLAY_HIDDEN,
    EVENT_SCENE,
    EVENT_STOPPED,
    STOPPED,
    STOPPED_MESSAGE,
    STOPPING,
    ObsSnapshot,
    ServiceStatus,
)


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

    def emit(self, message, history=True, code=None, subject=None):
        self.events.put(
            {
                "kind": "status",
                "code": code,
                "message": message,
                "timestamp": "t",
                "history": history,
                "subject": subject,
            }
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


def test_start_runs_the_worker_with_the_settings(h):
    cfg = make_config()

    h.controller.start(cfg)

    assert h.service.started_with == [cfg]
    assert (h.controller.can_start, h.controller.can_stop) == (False, True)


def test_start_never_saves(h):
    h.controller.load(load=lambda: make_config(hotkey="M"))

    h.controller.start(make_config(hotkey="K"))

    assert h.saved == []
    assert h.controller.history == []


def test_start_works_when_the_settings_file_cant_be_written(h):
    def failing_save(_cfg):
        raise OSError("denied")

    controller = AppController(schedule=h.schedule, service=h.service, save=failing_save)

    controller.start(make_config())

    assert h.service.started_with == [make_config()]


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
    assert h.controller.history[-1].message == "Config saved."
    assert h.service.started_with == []
    assert h.changes == 1


def test_a_failed_save_changes_nothing(h):
    def failing_save(_cfg):
        raise OSError("denied")

    controller = AppController(schedule=h.schedule, service=h.service, save=failing_save)

    with pytest.raises(OSError):
        controller.save(make_config(hotkey="M"))
    assert controller.running_config == default_config()
    assert controller.history == []


def test_saving_while_running_restarts_the_worker_once_the_old_one_has_stopped(h):
    h.controller.start(make_config())
    new_cfg = make_config(hotkey="M")

    h.controller.save(new_cfg)

    assert h.controller.restart_pending is True
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


def test_saving_while_maphide_is_stopping_does_not_start_it_again(h):
    h.controller.start(make_config())
    h.controller.stop()

    h.controller.save(make_config(hotkey="M"))
    h.service.finish_stopping()
    while h.schedule.pending:
        h.schedule.run_next()

    assert h.service.started_with == [make_config()]
    assert h.saved[-1] == make_config(hotkey="M")
    assert h.controller.running_config == make_config(hotkey="M")
    assert h.controller.can_start is True


def test_restoring_defaults_while_running_stops_and_stays_stopped(h):
    h.controller.start(make_config())

    h.controller.restore_defaults()
    assert h.service.stop_requests == 1
    h.service.finish_stopping()
    while h.schedule.pending:
        h.schedule.run_next()

    assert h.service.started_with == [make_config()]
    assert h.controller.can_start is True


def test_restoring_defaults_during_a_restart_cancels_it(h):
    h.controller.start(make_config())
    h.controller.save(make_config(hotkey="M"))

    h.controller.restore_defaults()
    h.service.finish_stopping()
    while h.schedule.pending:
        h.schedule.run_next()

    assert h.service.started_with == [make_config()]
    assert h.controller.restart_pending is False
    assert h.controller.can_start is True


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
    assert h.controller.history[-1].message == "Defaults restored."


# History.


def test_events_marked_for_history_are_kept(h):
    h.service.emit("Connected to OBS.")
    h.service.emit("Reconnecting... 1s", history=False)

    assert h.controller.drain_events() is True
    assert [entry.message for entry in h.controller.history] == ["Connected to OBS."]


def test_history_entries_keep_the_event_code_and_scene(h):
    h.service.emit("Switched to scene: Gameplay.", code=EVENT_SCENE, subject="Gameplay")

    h.controller.drain_events()

    assert h.controller.history == [
        HistoryEntry("t", "Switched to scene: Gameplay.", EVENT_SCENE, "Gameplay")
    ]


def test_saving_and_restoring_defaults_are_marked_in_the_history(h):
    h.controller.save(make_config())
    h.controller.restore_defaults()

    codes = [entry.code for entry in h.controller.history]
    assert codes == [HISTORY_SETTINGS_SAVED, HISTORY_DEFAULTS_RESTORED]


def test_draining_with_nothing_new_reports_no_change(h):
    h.service.emit("Reconnecting... 1s", history=False)

    assert h.controller.drain_events() is False


def test_history_keeps_only_the_newest_lines(h):
    for index in range(HISTORY_LINE_COUNT + 3):
        h.controller.add_history("t", f"line {index}")

    messages = [entry.message for entry in h.controller.history]
    assert len(messages) == HISTORY_LINE_COUNT
    assert messages[0] == "line 3"
    assert messages[-1] == f"line {HISTORY_LINE_COUNT + 2}"


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


# Saving without restarting the worker.


@pytest.mark.parametrize(
    "change",
    [{"theme": "legacy"}, {"auto_connect": True}, {"check_updates": False}, {}],
    ids=["theme", "connect on startup", "update check", "nothing"],
)
def test_saving_a_change_the_worker_does_not_use_leaves_it_running(h, change):
    h.controller.start(make_config())

    h.controller.save(make_config(**change))

    assert h.controller.restart_pending is False
    assert h.service.stop_requests == 0
    assert h.controller.running_config == make_config(**change)
    assert h.controller.history[-1].message == "Config saved."


def test_after_a_restart_saving_the_same_settings_again_does_not_restart(h):
    h.controller.start(make_config())
    h.controller.save(make_config(hotkey="M"))
    h.service.finish_stopping()
    h.schedule.run_next()
    assert h.service.started_with[-1] == make_config(hotkey="M")

    h.controller.save(make_config(hotkey="M", theme="legacy"))

    assert h.controller.restart_pending is False
    assert h.service.stop_requests == 1


def test_a_window_only_change_during_a_restart_is_kept(h):
    h.controller.start(make_config())
    h.controller.save(make_config(hotkey="M"))
    h.controller.save(make_config(hotkey="M", theme="legacy"))

    h.service.finish_stopping()
    h.schedule.run_next()

    assert h.service.started_with[-1] == make_config(hotkey="M", theme="legacy")


def test_starting_puts_the_started_settings_into_effect(h):
    h.controller.start(make_config(hotkey="M"))

    assert h.controller.running_config == make_config(hotkey="M")


# Saving while connected: a quiet reconnect in the history.


def connected_in(h, scene="Gameplay"):
    h.controller.start(make_config())
    h.service.status = ServiceStatus(CONNECTED, "Connected to OBS.")
    h.service.snapshot = ObsSnapshot(scene=scene)


def relink(h, *events):
    """The old worker finishes stopping, the new one starts and reports
    `events` as (code, message, subject)."""
    h.service.emit(STOPPED_MESSAGE, code=EVENT_STOPPED)
    h.service.finish_stopping()
    while h.schedule.pending:
        h.schedule.run_next()
    for code, message, subject in events:
        h.service.emit(message, code=code, subject=subject)
    h.controller.drain_events()


def lines(h):
    return [(entry.code, entry.subject) for entry in h.controller.history]


def test_saving_while_connected_shows_one_saved_line_then_link_up(h):
    connected_in(h)

    h.controller.save(make_config(hotkey="M"))
    relink(
        h,
        (EVENT_CONNECTING, "Connecting to OBS...", None),
        (EVENT_CONNECTED, "Connected to OBS.", None),
        (EVENT_SCENE, "Live scene: Gameplay", "Gameplay"),
    )

    assert lines(h) == [(HISTORY_SETTINGS_SAVED, SUBJECT_RELINKING), (EVENT_CONNECTED, None)]


def test_a_scene_that_changed_meanwhile_is_still_shown(h):
    connected_in(h)

    h.controller.save(make_config(hotkey="M"))
    relink(
        h,
        (EVENT_CONNECTING, "Connecting to OBS...", None),
        (EVENT_CONNECTED, "Connected to OBS.", None),
        (EVENT_SCENE, "Live scene: Camera", "Camera"),
    )

    assert lines(h)[-1] == (EVENT_SCENE, "Camera")


def test_a_problem_while_relinking_is_always_shown(h):
    connected_in(h)

    h.controller.save(make_config(hotkey="M"))
    relink(
        h,
        (EVENT_CONNECTING, "Connecting to OBS...", None),
        (EVENT_CONNECT_FAILED, "Failed to connect to OBS.", None),
        (EVENT_CONNECTING, "Connecting to OBS...", None),
    )

    # Quiet ends at the problem: the retry after it is shown too.
    assert lines(h) == [
        (HISTORY_SETTINGS_SAVED, SUBJECT_RELINKING),
        (EVENT_CONNECT_FAILED, None),
        (EVENT_CONNECTING, None),
    ]


def test_other_news_while_relinking_is_shown(h):
    connected_in(h)

    h.controller.save(make_config(hotkey="M"))
    h.service.emit("Overlay hidden.", code=EVENT_OVERLAY_HIDDEN)
    relink(h, (EVENT_CONNECTED, "Connected to OBS.", None))

    assert (EVENT_OVERLAY_HIDDEN, None) in lines(h)


def test_once_relinked_the_history_is_back_to_normal(h):
    connected_in(h)
    h.controller.save(make_config(hotkey="M"))
    relink(
        h,
        (EVENT_CONNECTED, "Connected to OBS.", None),
        (EVENT_SCENE, "Live scene: Gameplay", "Gameplay"),
    )

    h.controller.stop()
    h.service.emit(STOPPED_MESSAGE, code=EVENT_STOPPED)
    h.controller.drain_events()

    assert lines(h)[-1] == (EVENT_STOPPED, None)


def test_saving_while_stopped_is_a_plain_saved_line(h):
    h.controller.save(make_config(hotkey="M"))

    assert lines(h) == [(HISTORY_SETTINGS_SAVED, None)]


def test_reset_during_a_relink_still_shows_the_stop(h):
    connected_in(h)
    h.controller.save(make_config(hotkey="M"))

    h.controller.restore_defaults()
    relink(h)

    assert lines(h)[-1] == (EVENT_STOPPED, None)
