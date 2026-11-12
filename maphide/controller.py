"""Everything the settings window asks of MapHide, apart from drawing it.

The window forwards clicks here and redraws from what this exposes, so the
same behaviour holds whichever toolkit draws the window: starting and
stopping the worker, saving settings (restarting the worker when they
change under it), the in-app history list, and shutting down cleanly.

Nothing here touches a widget. Timers go through the `schedule` callable
the window passes in, so they always run on the window's own thread.
"""

import queue

from .config import default_config, form_ready, load_config, save_config
from .overlay import CONNECTED, MapHideService, human_ts, stop_wait_should_continue

HISTORY_LINE_COUNT = 10
RESTART_POLL_INTERVAL_MS = 50
# A backstop, not a normal-case budget: the worker's own shutdown cleanup can
# legitimately take a moment (one OBS request per scene carrying the overlay
# source), so exit polls for it to actually finish rather than guessing at a
# fixed wait - see stop_wait_should_continue. This only ever matters if that
# cleanup somehow runs far longer than any realistic scene count justifies.
EXIT_WAIT_CEILING_MS = 15_000
APPLYING_SETTINGS = "Applying settings..."


def status_line(status, restart_pending):
    """What the status line says: the service's own wording, except while a
    settings change is restarting it - the stop and start in between are not
    worth showing."""
    return APPLYING_SETTINGS if restart_pending else status.message


def help_text(cfg):
    """One line on how to use the keys the running settings name."""
    if cfg.toggle_mode:
        return f"Press {cfg.hotkey} to show the overlay. Press {cfg.hide_hotkey} to hide it."
    return f"Hold {cfg.hotkey} to show the overlay. Release {cfg.hotkey} to hide it."


def _ignore(*_args):
    return None


class AppController:
    """The window's side of MapHide, without the window.

    `schedule(milliseconds, callback)` runs `callback` later on the window's
    thread. `notify(text)` shows the user a one-off message. `on_change()`
    asks the window to redraw the status line, buttons and history.
    """

    def __init__(
        self, schedule, service=None, save=save_config, notify=_ignore, on_change=_ignore
    ):
        self._schedule = schedule
        self.service = service if service is not None else MapHideService()
        self._save = save
        self._notify = notify
        self._on_change = on_change
        self.running_config = default_config()
        self.restart_pending = False
        self._pending_restart_config = None
        self.exit_requested = False
        self.history_lines = []

    # What the window draws.

    @property
    def status_text(self):
        return status_line(self.service.status, self.restart_pending)

    @property
    def help_text(self):
        return help_text(self.running_config)

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

    # Testing.

    def set_manual_input(self, down):
        """Press (True) or release (False) the test button. It drives the
        overlay through the same decision as the hotkey."""
        self.service.set_manual_input(down)

    # Settings.

    def load(self, load=load_config):
        """Read the saved settings. Returns the settings to show, and whether
        they were read successfully - on failure the defaults are used."""
        try:
            cfg = load()
            loaded = True
        except (OSError, ValueError, KeyError):
            cfg = default_config()
            loaded = False
        self.running_config = form_ready(cfg)
        return self.running_config, loaded

    def save(self, cfg):
        """Save `cfg` and put it into effect. Raises OSError if it can't be
        written, in which case nothing changes."""
        self._save(cfg)
        self._apply(cfg, "Config saved.")

    def restore_defaults(self):
        """Save and apply the default settings, and return them."""
        cfg = default_config()
        self._save(cfg)
        self._apply(cfg, "Defaults restored.")
        return cfg

    def _apply(self, cfg, done_message):
        self.running_config = cfg
        # The history, not the live status line: a save confirmation isn't
        # part of the OBS connection's own story.
        self.add_history(human_ts(), done_message)
        if self.service.is_running:
            self._restart_service_with(cfg)
        self._on_change()

    # The worker.

    def start(self, cfg):
        """Save `cfg` and start the worker with it. Raises OSError if the
        settings can't be saved, RuntimeError if the worker is already
        running."""
        self._save(cfg)
        self.service.start(cfg)
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
        try:
            self.service.start(cfg)
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
                self.add_history(event["timestamp"], event["message"])
                changed = True

    def add_history(self, timestamp, message):
        self.history_lines.append(f"{timestamp}  {message}")
        del self.history_lines[:-HISTORY_LINE_COUNT]

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
