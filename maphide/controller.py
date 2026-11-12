"""Everything the settings window asks of MapHide, apart from drawing it.

The window forwards clicks here and redraws from what this exposes, so the
same behaviour holds whichever toolkit draws the window: starting and
stopping the worker, saving settings (restarting the worker when they
change under it), the in-app history list, and shutting down cleanly.

Nothing here touches a widget. Timers go through the `schedule` callable
the window passes in, so they always run on the window's own thread.
"""

import queue
import threading
from dataclasses import dataclass

from .config import (
    connection_from_form,
    default_config,
    form_ready,
    load_config,
    save_config,
    worker_settings_differ,
)
from .obs import ConnectionCheck, check_connection
from .overlay import CONNECTED, MapHideService, human_ts, stop_wait_should_continue

HISTORY_LINE_COUNT = 10
RESTART_POLL_INTERVAL_MS = 50
CHECK_POLL_INTERVAL_MS = 50
CHECK_FAILED = "Could not check the connection."
# A backstop, not a normal-case budget: the worker's own shutdown cleanup can
# legitimately take a moment (one OBS request per scene carrying the overlay
# source), so exit polls for it to actually finish rather than guessing at a
# fixed wait - see stop_wait_should_continue. This only ever matters if that
# cleanup somehow runs far longer than any realistic scene count justifies.
EXIT_WAIT_CEILING_MS = 15_000
# History codes for the controller's own entries, alongside the worker's
# EVENT_* codes.
HISTORY_SETTINGS_SAVED = "settings_saved"
HISTORY_DEFAULTS_RESTORED = "defaults_restored"
# A newer MapHide is out; `subject` is its version.
HISTORY_UPDATE_AVAILABLE = "update_available"
# A message the window itself puts in the history, such as a setting it
# can't use.
HISTORY_NOTICE = "notice"


@dataclass(frozen=True)
class HistoryEntry:
    """One line of the in-app history. `code` says what it is about (an
    EVENT_* code or one of the HISTORY_* codes above), so a window can word
    it its own way; `subject` is the scene it names, if any."""

    timestamp: str
    message: str
    code: str | None = None
    subject: str | None = None


def _ignore(*_args):
    return None


class AppController:
    """The window's side of MapHide, without the window.

    `schedule(milliseconds, callback)` runs `callback` later on the window's
    thread. `notify(text)` shows the user a one-off message. `on_change()`
    asks the window to redraw what it shows.
    """

    def __init__(
        self,
        schedule,
        service=None,
        save=save_config,
        notify=_ignore,
        on_change=_ignore,
        check=check_connection,
    ):
        self._schedule = schedule
        self.service = service if service is not None else MapHideService()
        self._save = save
        self._check = check
        self._check_thread = None
        self._notify = notify
        self._on_change = on_change
        self.running_config = default_config()
        # What the settings file holds, as last read or written; None when
        # that isn't known, as when the file couldn't be read.
        self._saved_config = None
        # The settings the running worker was started with, or None.
        self._worker_config = None
        self.restart_pending = False
        self._pending_restart_config = None
        self.exit_requested = False
        self.history = []

    # What the window draws.

    @property
    def snapshot(self):
        """The live scene, whether the map is covered, and how many scenes
        carry the source - see overlay.ObsSnapshot."""
        return self.service.snapshot

    @property
    def can_start(self):
        # Derived from what the service is doing, not from the event stream.
        # A restart stops and starts the same service, so its "stopped" event
        # can arrive after the restart has already finished.
        return not self.service.is_running and not self.restart_pending

    @property
    def can_stop(self):
        return self.service.is_running and not self.restart_pending

    @property
    def can_test(self):
        """Whether the test button can do anything: only while connected."""
        return (
            self.service.is_running
            and not self.restart_pending
            and self.service.status.state == CONNECTED
        )

    @property
    def checking_connection(self):
        return self._check_thread is not None

    # Testing.

    def set_manual_input(self, down):
        """Press (True) or release (False) the test button. It drives the
        overlay through the same decision as the hotkey."""
        self.service.set_manual_input(down)

    def check_connection(self, host, port, password, source_name, on_done):
        """Try connecting to OBS once with these form values, off the
        window's thread, then call `on_done(ConnectionCheck)` on the window's
        thread. Raises ValueError (with a message to show) if the host or
        port can't be used. Returns False, and does nothing, while a check is
        already running."""
        if self._check_thread is not None:
            return False
        host, port_number = connection_from_form(host, port)
        source_name = str(source_name).strip()
        result = []

        def run():
            try:
                result.append(self._check(host, port_number, password, source_name))
            except Exception:
                # A bug in the check must still end the wait in the window.
                result.append(ConnectionCheck(ok=False, message=CHECK_FAILED))

        self._check_thread = threading.Thread(target=run, name="ConnectionCheck", daemon=True)
        self._check_thread.start()
        self._schedule(CHECK_POLL_INTERVAL_MS, lambda: self._await_check(result, on_done))
        return True

    def _await_check(self, result, on_done):
        if not result:
            self._schedule(CHECK_POLL_INTERVAL_MS, lambda: self._await_check(result, on_done))
            return
        self._check_thread = None
        on_done(result[0])

    # Settings.

    def load(self, load=load_config):
        """Read the saved settings. Returns the settings to show, and whether
        they were read successfully - on failure the defaults are used."""
        try:
            cfg = load()
            loaded = True
            self._saved_config = cfg
        except (OSError, ValueError, KeyError):
            cfg = default_config()
            loaded = False
            self._saved_config = None
        self.running_config = form_ready(cfg)
        return self.running_config, loaded

    def save(self, cfg):
        """Save `cfg` and put it into effect. Raises OSError if it can't be
        written, in which case nothing changes."""
        self._write(cfg)
        self._apply(cfg, "Config saved.", HISTORY_SETTINGS_SAVED)

    def restore_defaults(self):
        """Save the default settings, and return them. A running worker is
        stopped, not restarted: the defaults have no OBS address to connect
        to."""
        cfg = default_config()
        self._write(cfg)
        self._record(cfg, "Defaults restored.", HISTORY_DEFAULTS_RESTORED)
        if self.restart_pending:
            # The restart under way finishes stopping, then starts nothing.
            self._pending_restart_config = None
        elif self.service.is_running:
            self.service.stop()
        self._on_change()
        return cfg

    def _record(self, cfg, done_message, code):
        self.running_config = cfg
        # The history, not the live status line: a save confirmation isn't
        # part of the OBS connection's own story.
        self.add_history(human_ts(), done_message, code)

    def _apply(self, cfg, done_message, code):
        self._record(cfg, done_message, code)
        # Only restart for a change the worker would actually see: a restart
        # briefly drops the OBS link and hides the overlay. A restart already
        # under way always takes the newest settings.
        if self.restart_pending or (self.service.is_running and self._worker_needs(cfg)):
            self._restart_service_with(cfg)
        self._on_change()

    def _worker_needs(self, cfg):
        return self._worker_config is None or worker_settings_differ(self._worker_config, cfg)

    # The worker.

    def _write(self, cfg):
        self._save(cfg)
        self._saved_config = cfg

    def start(self, cfg):
        """Save `cfg`, unless the file already holds it, and start the
        worker with it. A save shows in the field log, as Save's does.
        Raises OSError if the settings can't be saved, RuntimeError if the
        worker is already running."""
        if cfg != self._saved_config:
            self._write(cfg)
            self.add_history(human_ts(), "Config saved.", HISTORY_SETTINGS_SAVED)
        self.service.start(cfg)
        self._worker_config = cfg
        self.running_config = cfg
        self._on_change()

    def stop(self):
        self.service.stop()
        self._on_change()

    def _restart_service_with(self, cfg):
        self._pending_restart_config = cfg
        if self.restart_pending:
            # A restart is already waiting on the old worker; it picks up
            # the newest settings when it gets there.
            return
        self.restart_pending = True
        self.service.stop()
        # No ceiling: MapHide keeps running either way, so there is no reason
        # to give up on the old worker's own shutdown cleanup early and start
        # a new one on top of it.
        self._wait_for_service_stop(None, self._finish_restart)

    def _finish_restart(self):
        cfg = self._pending_restart_config
        self.restart_pending = False
        self._pending_restart_config = None
        if self.exit_requested:
            # MapHide is closing: a new worker would outlive the exit's own
            # wait and be cut off without hiding the overlay.
            return
        if cfg is None:
            # Restore defaults called the restart off.
            self._on_change()
            return
        try:
            self.service.start(cfg)
            self._worker_config = cfg
        except RuntimeError as exc:
            self._notify(str(exc))
        self._on_change()

    def _wait_for_service_stop(self, ceiling_ms, on_stopped, elapsed_ms=0):
        """Poll until the worker actually reports stopped, then run
        on_stopped. See stop_wait_should_continue for the cutoff."""
        if stop_wait_should_continue(self.service.is_running, elapsed_ms, ceiling_ms):
            self._schedule(
                RESTART_POLL_INTERVAL_MS,
                lambda: self._wait_for_service_stop(
                    ceiling_ms, on_stopped, elapsed_ms + RESTART_POLL_INTERVAL_MS
                ),
            )
            return
        on_stopped()

    # History.

    def drain_events(self):
        """Move the worker's new events into the history. Returns whether
        the history changed."""
        changed = False
        while True:
            try:
                event = self.service.events.get_nowait()
            except queue.Empty:
                return changed
            if event["history"]:
                self.add_history(
                    event["timestamp"], event["message"], event.get("code"), event.get("subject")
                )
                changed = True

    def add_history(self, timestamp, message, code=None, subject=None):
        self.history.append(HistoryEntry(timestamp, message, code, subject))
        del self.history[:-HISTORY_LINE_COUNT]

    # Shutting down.

    def begin_exit(self, on_finished):
        """Stop the worker, then call `on_finished` once it has finished
        hiding the overlay (or the backstop ceiling passes). Returns False,
        and does nothing, if an exit is already under way."""
        if self.exit_requested:
            return False
        self.exit_requested = True
        self.service.stop()
        self._wait_for_service_stop(EXIT_WAIT_CEILING_MS, on_finished)
        return True
