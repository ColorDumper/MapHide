"""The worker: polls the keys, runs the overlay decision, drives OBS."""

import logging
import queue
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .hotkeys import poll_hotkey
from .logs import (
    configure_logging,
    describe_cause,
    describe_exception,
    logger,
    plain_reason,
)
from .obs import (
    CONNECT_TIMEOUT,
    OBS_OVERLAY_MAY_REMAIN,
    ObsAuthError,
    ObsConnectionError,
    ObsRequestRefused,
    ObsUnreachableError,
    connect_obs,
    disconnect_obs,
    find_overlay_scene_items,
    find_scene_item_id,
    get_current_scene,
    set_overlay_enabled,
)
from .state import HIDE, SHOW, OverlayState, decide

POLL_INTERVAL = 0.005
SCENE_REFRESH_INTERVAL = 0.25
# How often to ask OBS about the active scene alone, while the source isn't
# yet known to be there - catches a source added to the scene you're already
# on, which a switch-triggered rescan would otherwise never notice. Cheap and
# infrequent by design: a single-scene request, not the full rescan, and
# nothing at all once the source is found.
MISSING_SOURCE_RECHECK_INTERVAL = 3.0
# Matches the connect timeout, not chosen independently: trying and waiting
# take the same amount of time, so the retry cadence reads as one predictable
# rhythm instead of two arbitrary, differently-sized numbers.
RECONNECT_DELAY = CONNECT_TIMEOUT
RECONNECT_TICK = 1.0

# Said while the link is down with the overlay last told to show: OBS keeps
# whatever it was last given, so nothing here can hide it until reconnected.
OVERLAY_MAY_REMAIN_NOTE = "The overlay may still be showing in OBS."
STOPPED_MESSAGE = "MapHide stopped."

# Where the service stands, as a status line shows it.
IDLE = "idle"
CONNECTING = "connecting"
CONNECTED = "connected"
RECONNECTING = "reconnecting"
STOPPING = "stopping"
STOPPED = "stopped"


@dataclass(frozen=True)
class ServiceStatus:
    state: str
    message: str


# What each event is about, so a window can choose its own wording and color
# for it rather than parse the message. The message stays the plain-English
# version, for the history list, the debug log and headless mode.
EVENT_LOG_FAILED = "log_failed"
EVENT_CONNECTING = "connecting"
EVENT_CONNECTED = "connected"
EVENT_CONNECT_FAILED = "connect_failed"
EVENT_RECONNECT_WAIT = "reconnect_wait"
EVENT_LINK_LOST = "link_lost"
EVENT_OVERLAY_MAY_REMAIN = "overlay_may_remain"
EVENT_SCENE = "scene"
# A scene change to a scene that doesn't carry the overlay source.
EVENT_SCENE_WITHOUT_SOURCE = "scene_without_source"
EVENT_SOURCE_FOUND = "source_found"
EVENT_SCENE_DROPPED = "scene_dropped"
EVENT_OVERLAY_SHOWN = "overlay_shown"
EVENT_OVERLAY_HIDDEN = "overlay_hidden"
EVENT_STOPPED = "stopped"


@dataclass(frozen=True)
class ObsSnapshot:
    """What OBS looks like from here right now, for a window to draw.

    `scene` is OBS's live (program) scene, or None while it isn't known -
    not connected yet, or the link is down. `covered` is True only while the
    overlay was last told to show AND the live scene carries the source, so
    it never claims the map is covered on a scene the source isn't in.
    `source_scene_count` is how many scenes carry the source, or None while
    unknown.
    """

    scene: str | None = None
    covered: bool = False
    source_scene_count: int | None = None


def obs_snapshot(scene_name, scene_items, overlay_visible):
    """The ObsSnapshot for the worker's current view of OBS."""
    if scene_name is None:
        return ObsSnapshot()
    return ObsSnapshot(
        scene=scene_name,
        covered=overlay_visible and scene_items.get(scene_name) is not None,
        source_scene_count=sum(item is not None for item in scene_items.values()),
    )


def scene_is_stale(scene_items, scene_synced, scene_name, target_visible):
    """Does this scene carry the source, and does it not yet match
    `target_visible`? A scene that has never been written to at all counts
    as stale regardless of what `target_visible` is - "unconfirmed" is not
    the same as "matches by coincidence"."""
    return (
        scene_items.get(scene_name) is not None and scene_synced.get(scene_name) != target_visible
    )


def find_stale_scene(scene_items, scene_synced, exclude, target_visible):
    """The first scene (other than `exclude`) still waiting to catch up to
    `target_visible`, or None once everything else already matches."""
    return next(
        (
            name
            for name in scene_items
            if name != exclude and scene_is_stale(scene_items, scene_synced, name, target_visible)
        ),
        None,
    )


def sync_scene(client, scene_items, scene_synced, scene_name, visible):
    """Write `visible` to exactly one scene and record that it now matches -
    the write and the bookkeeping always happen together, never one without
    the other. A scene whose item_id isn't known yet has nothing to write
    to, so it is left unmarked rather than falsely recorded as already
    correct - overlay_available can be True from the source existing in a
    different scene, so this can be reached before this scene's own item_id
    is known."""
    if scene_items.get(scene_name) is None:
        return
    set_overlay_enabled(client, scene_items, scene_name, visible, all_scenes=False)
    scene_synced[scene_name] = visible


def sync_scene_if_stale(client, scene_items, scene_synced, scene_name, visible):
    """sync_scene, but only if the scene doesn't already match - avoids a
    redundant OBS write when nothing has actually changed."""
    if scene_is_stale(scene_items, scene_synced, scene_name, visible):
        sync_scene(client, scene_items, scene_synced, scene_name, visible)


def catch_up_one_stale_scene(client, scene_items, scene_synced, exclude, target_visible):
    """Write `target_visible` to the next scene (other than `exclude`) still
    waiting to catch up, one scene per call. If OBS rejects the write, the
    scene itself (or the source's place in it) most likely no longer
    exists: drop it from scene_items and handle that locally, rather than
    letting one stale background scene look like the whole connection died.
    A write that fails any other way - a timeout, a dropped link - is not a
    verdict on the scene, and propagates as the connection failure it is.
    Returns the name of a scene dropped this way, or None."""
    stale_scene = find_stale_scene(scene_items, scene_synced, exclude, target_visible)
    if stale_scene is None:
        return None
    try:
        sync_scene(client, scene_items, scene_synced, stale_scene, target_visible)
    except ObsRequestRefused:
        del scene_items[stale_scene]
        scene_synced.pop(stale_scene, None)
        return stale_scene
    return None


def recheck_missing_source(client, scene_items, scene_name, source_name):
    """If `source_name` isn't yet known to be in `scene_name`, ask OBS again -
    a single-scene request, not a full rescan, and nothing at all once it is
    already known to be there. Updates `scene_items` in place and returns
    whether it was just found."""
    if scene_items.get(scene_name) is not None:
        return False
    found_item_id = find_scene_item_id(client, scene_name, source_name)
    if found_item_id is None:
        return False
    scene_items[scene_name] = found_item_id
    return True


def scene_status(scene_name, is_first_detection=False):
    # No hotkey/mode explanation here - the help text below the log already
    # covers that, and repeating it made this line far too long for the space.
    verb = "New scene detected" if is_first_detection else "Switched to scene"
    return f"{verb}: {scene_name}."


def manual_input_target(cfg, same_key, desired_visible):
    """Which key a press of the window's test button stands for: SHOW or HIDE.

    In hold mode, and in toggle mode with one key for both, it is the show
    key. In toggle mode with separate keys it is whichever key would change
    things - the hide key while the overlay should be showing, the show key
    otherwise - so one button covers and uncovers alike.
    """
    if cfg.toggle_mode and not same_key and desired_visible:
        return HIDE
    return SHOW


def seed_key_edge_tracking(state, cfg, show_vk_codes, hide_vk_codes):
    """Reset show_key_was_down/hide_key_was_down from a real poll of the
    current key state, not a blind False - run on every (re)connect. A key
    still physically held through the outage must not look like a fresh
    press the moment polling resumes."""
    show_key_down_now, _ = poll_hotkey(show_vk_codes)
    hide_key_down_now, _ = poll_hotkey(hide_vk_codes) if cfg.toggle_mode else (False, False)
    return replace(
        state,
        show_key_was_down=show_key_down_now,
        hide_key_was_down=hide_key_down_now,
    )


def human_ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def monotonic_now():
    """The time every timer in the worker is measured against: a datetime-shaped
    reading of the monotonic clock, so a clock correction or a daylight-saving
    change can never make an interval negative or stretch it by an hour. Only
    differences between two readings mean anything; for display use human_ts."""
    return datetime.min + timedelta(seconds=time.monotonic())


def stop_wait_should_continue(is_running, elapsed_ms, ceiling_ms):
    """Whether a poll loop waiting on a MapHideService to stop should keep
    going. Used by both the GUI (ui.py) and headless (map_hider.py) shutdown
    paths, so it lives next to the service itself rather than in either one.

    Pure - no clock, no thread, no Tk - so the cutoff logic is testable on
    its own, without a real timer or a live worker thread. `ceiling_ms=None`
    means wait indefinitely (a GUI Save Settings restart: the app keeps
    running either way, so there is no reason to ever give up on the old
    worker's own cleanup). A numeric ceiling is a backstop for actually
    exiting, where the process must eventually finish regardless of how long
    that cleanup takes - the shutdown sweep can touch more than one scene,
    see set_overlay_enabled's all_scenes write in this module's finally
    block below.
    """
    if not is_running:
        return False
    if ceiling_ms is not None and elapsed_ms >= ceiling_ms:
        return False
    return True


class MapHideService:
    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._events = queue.Queue()
        self._running = False
        self._status = ServiceStatus(IDLE, "Idle")
        self._snapshot = ObsSnapshot()
        self._manual_down = False
        self._manual_pressed = False
        self._status_lock = threading.Lock()

    @property
    def events(self):
        return self._events

    @property
    def is_running(self):
        return self._running

    @property
    def status(self):
        """Where the service stands right now. Read it whenever a status line
        is drawn: unlike the event queue, which is a history to replay in
        order, this is always current."""
        return self._status

    @property
    def snapshot(self):
        """The live scene, whether the map is covered, and how many scenes
        carry the source, as an ObsSnapshot. Always current, like status."""
        return self._snapshot

    def set_manual_input(self, down):
        """Press (True) or release (False) the window's test button. It goes
        through exactly the same decision as the hotkey - debounce, hide
        delay, hold or toggle - and only does anything while connected."""
        with self._status_lock:
            if down and not self._manual_down:
                self._manual_pressed = True
            self._manual_down = bool(down)

    def _take_manual_input(self):
        """The test button's state for one poll: whether it is down, and
        whether it was pressed since the last poll even if already released."""
        with self._status_lock:
            taken = (self._manual_down, self._manual_pressed)
            self._manual_pressed = False
            return taken

    def _release_manual_input(self):
        with self._status_lock:
            self._manual_down = False
            self._manual_pressed = False

    def _publish(self, snapshot):
        with self._status_lock:
            if snapshot != self._snapshot:
                self._snapshot = snapshot

    def _set_status(self, state, message, force=False):
        with self._status_lock:
            # Once a stop is requested, only the stop finishing changes what
            # is shown - a late event from the worker must not undo it.
            if not force and self._status.state == STOPPING and state != STOPPED:
                return
            self._status = ServiceStatus(state, message)

    def start(self, cfg):
        if self._running:
            raise RuntimeError("Service is already running.")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(cfg,),
            name="MapHideWorker",
            daemon=True,
        )
        self._running = True
        self._set_status(CONNECTING, "Starting...", force=True)
        self._publish(ObsSnapshot())
        self._release_manual_input()
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        with self._status_lock:
            # A worker that has already finished must not be shown as still
            # stopping.
            if self._running and self._status.state != STOPPED:
                self._status = ServiceStatus(STOPPING, "Stopping...")

    def wait(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _emit(
        self, kind, code, message, history=True, log=True, detail=None, state=None, subject=None
    ):
        # `subject` is the scene an event is about, if any, so a window can
        # name it without picking it back out of the message.
        # Every event reaches the debug log unless `log` is False, which is for
        # repeats that would only crowd out the lines worth reading; `detail`
        # is extra for the debug log alone, never shown in the window.
        # `history` decides whether the in-app history list also keeps this
        # one. `state`, when given, is the connection state the event puts the
        # service in, which is what the status line shows. The two are
        # independent: an overlay shown/hidden event belongs in the history
        # list but says nothing about the OBS connection, so it carries no
        # state and never disturbs what the status line is saying about it.
        if log:
            text = f"{message} ({detail})" if detail else message
            logger.log(logging.ERROR if kind == "error" else logging.INFO, "%s: %s", kind, text)
        if state is not None:
            self._set_status(state, message)
        self._events.put(
            {
                "kind": kind,
                "code": code,
                "message": message,
                "timestamp": human_ts(),
                "history": history,
                "subject": subject,
            }
        )

    def _wait_with_countdown(self, total_seconds, note=None):
        """Wait up to total_seconds, interruptible, with a status-only
        tick each second - so a long retry reads as "still trying" instead of
        looking stuck on whatever it last said, and the count reaches the
        full total rather than stopping short of however long this actually
        waits. The failure message that led here always gets a full tick of
        real screen time before anything here overwrites it, since each tick
        only lands after `self._stop_event.wait` has genuinely blocked for
        that long - there is no way for the two updates to land together.
        """
        elapsed = 0.0
        while elapsed < total_seconds:
            step = min(RECONNECT_TICK, total_seconds - elapsed)
            if self._stop_event.wait(step):
                return
            elapsed += step
            message = f"Reconnecting... {elapsed:g}s"
            if note:
                message += f". {note}"
            self._emit(
                "status",
                EVENT_RECONNECT_WAIT,
                message,
                history=False,
                log=False,
                state=RECONNECTING,
            )

    def _run(self, cfg):
        try:
            log_start_error = configure_logging(cfg.log_enabled)
        except Exception as exc:
            # A log that cannot start must never keep the worker from starting.
            log_start_error = plain_reason(exc)
        if log_start_error is not None:
            self._emit(
                "status", EVENT_LOG_FAILED, f"Could not start the debug log: {log_start_error}"
            )
        elif cfg.log_enabled:
            config_summary = ", ".join(
                f"{key}={value}" for key, value in cfg.to_loggable_dict().items()
            )
            logger.info("Config: %s", config_summary)
        show_vk_codes = cfg.show_vk_codes()
        hide_vk_codes = cfg.hide_vk_codes()
        same_key = show_vk_codes == hide_vk_codes
        # Which key the test button stands for, fixed for the length of one
        # press so that holding it can never flip between the two.
        manual_key = None
        client = None
        state = OverlayState()
        scene_items = {}
        scene_synced = {}
        overlay_available = False
        active_scene_name = None
        last_scene_refresh = datetime.min
        last_missing_source_check = datetime.min
        # Tracks whether the current run of failures already has a history
        # entry, separately from the status line (which shows every attempt).
        # Resets on a successful connect, so the next streak gets its own.
        failure_in_history = False
        failed_attempts = 0
        # Set while the link is down and the overlay was last told to show.
        overlay_may_remain = False
        # The last error that went into the history, so a final "stopped"
        # that only repeats it is not added a second time.
        last_history_error = None
        final_status_message = STOPPED_MESSAGE
        had_successful_connection = False

        try:
            while not self._stop_event.is_set():
                if client is None:
                    try:
                        # Announced once per streak, not on every retry: seeing
                        # "Connecting to OBS..." reappear after a failure reads as a
                        # fresh attempt about to succeed, when it is really the same
                        # loop continuing. failure_in_history already tracks exactly
                        # that - false for a genuinely new attempt, true partway
                        # through an already-acknowledged run of failures.
                        if not failure_in_history:
                            self._emit(
                                "status",
                                EVENT_CONNECTING,
                                "Connecting to OBS...",
                                state=CONNECTING,
                            )
                        client = connect_obs(cfg.host, cfg.port, cfg.password)
                        active_scene_name = None
                        last_scene_refresh = datetime.min
                        last_missing_source_check = datetime.min
                        # OBS's per-scene state is unverified again after any
                        # (re)connect - it restores sources enabled after a
                        # restart, and a dropped connection can strand one
                        # visible - so nothing already-confirmed here can be
                        # trusted going forward.
                        scene_synced = {}
                        # hide_requested_at deliberately survives: a hide already
                        # armed before the drop must still land once reconnected,
                        # not evaporate because nothing changed key-wise since.
                        state = seed_key_edge_tracking(state, cfg, show_vk_codes, hide_vk_codes)
                        self._release_manual_input()
                        manual_key = None
                        failure_in_history = False
                        overlay_may_remain = False
                        had_successful_connection = True
                        self._emit("status", EVENT_CONNECTED, "Connected to OBS.", state=CONNECTED)
                        if failed_attempts:
                            logger.info("Connected after %d failed attempts.", failed_attempts)
                        failed_attempts = 0
                    except ObsConnectionError as exc:
                        error_message = str(exc)
                        # A wrong password will not start working on its own. An
                        # unreachable OBS often just hasn't been opened yet, including
                        # on the very first attempt, so that keeps retrying. Any other
                        # failure on a first attempt that never succeeded usually means
                        # the settings are wrong, so that one still waits for the user.
                        # auto_reconnect off overrides all of that: any failure just
                        # stops the service, handing full manual control back to the user.
                        give_up = (
                            not cfg.auto_reconnect
                            or isinstance(exc, ObsAuthError)
                            or (
                                not had_successful_connection
                                and not isinstance(exc, ObsUnreachableError)
                            )
                        )
                        # Shown in the status line on every single attempt - a retry
                        # that is still failing should keep saying so, not go quiet
                        # after the first time. Only the history entry and the debug
                        # log line are limited to one per streak; the log gets a
                        # count of the attempts when the streak ends. A failure
                        # that gives up is followed at once by "stopped", which
                        # takes over the status line.
                        self._emit(
                            "error",
                            EVENT_CONNECT_FAILED,
                            error_message,
                            history=not failure_in_history,
                            log=not failure_in_history,
                            detail=describe_cause(exc),
                            state=None if give_up else RECONNECTING,
                        )
                        if not failure_in_history:
                            last_history_error = error_message
                        failure_in_history = True
                        failed_attempts += 1
                        if give_up:
                            final_status_message = error_message
                            break
                        self._wait_with_countdown(
                            RECONNECT_DELAY,
                            OVERLAY_MAY_REMAIN_NOTE if overlay_may_remain else None,
                        )
                        continue

                now = monotonic_now()
                try:
                    if (now - last_scene_refresh) >= timedelta(seconds=SCENE_REFRESH_INTERVAL):
                        latest_scene_name = get_current_scene(client)
                        if latest_scene_name != active_scene_name:
                            # None only right after a (re)connect - that first
                            # read is not a switch, it is just learning what
                            # scene OBS was already on.
                            is_first_detection = active_scene_name is None
                            active_scene_name = latest_scene_name
                            # Re-read every scene, not just this one: the source may have
                            # been added to a scene since the last look.
                            scene_items = find_overlay_scene_items(client, cfg.scene_item_name)
                            overlay_available = any(
                                found is not None for found in scene_items.values()
                            )
                            logger.info(
                                "Scenes read: %d, carrying the source: %d",
                                len(scene_items),
                                sum(found is not None for found in scene_items.values()),
                            )
                            # A scene change is worth a history line, but it is not
                            # part of the OBS connection's own story, so it carries no
                            # state and leaves the status line alone.
                            status_message = scene_status(active_scene_name, is_first_detection)
                            scene_code = EVENT_SCENE
                            if scene_items.get(active_scene_name) is None:
                                status_message += f" Source '{cfg.scene_item_name}' not found."
                                scene_code = EVENT_SCENE_WITHOUT_SOURCE
                            self._emit(
                                "status", scene_code, status_message, subject=active_scene_name
                            )
                            # Most switches need nothing here at all: the scene you were
                            # on was kept in sync continuously by every toggle while it
                            # was active, and any other scene the background catch-up
                            # below reaches before you switch back to it. This is only
                            # the (rare) fallback for one that hasn't caught up yet - a
                            # scene visited for the first time, or one you returned to
                            # faster than the trickle could reach it.
                            sync_scene_if_stale(
                                client,
                                scene_items,
                                scene_synced,
                                active_scene_name,
                                state.overlay_visible,
                            )
                        last_scene_refresh = now

                    # A separate, slower timer from the one above: catches a
                    # source added to the scene you're already on, which a
                    # switch-triggered rescan would otherwise never notice.
                    # No-ops entirely once the source is known to be there.
                    if active_scene_name is not None and (
                        now - last_missing_source_check
                    ) >= timedelta(seconds=MISSING_SOURCE_RECHECK_INTERVAL):
                        last_missing_source_check = now
                        if recheck_missing_source(
                            client, scene_items, active_scene_name, cfg.scene_item_name
                        ):
                            overlay_available = any(
                                found is not None for found in scene_items.values()
                            )
                            self._emit(
                                "status",
                                EVENT_SOURCE_FOUND,
                                f"Source '{cfg.scene_item_name}' found in scene: "
                                f"{active_scene_name}.",
                                subject=active_scene_name,
                            )
                            sync_scene_if_stale(
                                client,
                                scene_items,
                                scene_synced,
                                active_scene_name,
                                state.overlay_visible,
                            )

                    show_down, show_pressed = poll_hotkey(show_vk_codes)
                    hide_down, hide_pressed = (
                        poll_hotkey(hide_vk_codes) if cfg.toggle_mode else (False, False)
                    )
                    manual_down, manual_pressed = self._take_manual_input()
                    if (manual_down or manual_pressed) and manual_key is None:
                        manual_key = manual_input_target(cfg, same_key, state.desired_visible)
                    if manual_key == SHOW:
                        show_down = show_down or manual_down
                        show_pressed = show_pressed or manual_pressed
                    elif manual_key == HIDE:
                        hide_down = hide_down or manual_down
                        hide_pressed = hide_pressed or manual_pressed
                    if not manual_down:
                        manual_key = None
                    state, action = decide(
                        cfg,
                        state,
                        show_down,
                        hide_down,
                        same_key,
                        overlay_available,
                        now,
                        show_key_pressed=show_pressed,
                        hide_key_pressed=hide_pressed,
                    )
                    # How often the map itself gets toggled has nothing to do with
                    # the OBS connection, so these carry no state. Logged only
                    # when the active scene actually carries the source -
                    # sync_scene silently no-ops otherwise (the source may still be
                    # kept in sync in a different scene, in the background below),
                    # and a log line claiming something happened on the scene you're
                    # watching, when nothing did, is worse than saying nothing.
                    active_scene_has_source = scene_items.get(active_scene_name) is not None
                    if action == SHOW:
                        sync_scene(client, scene_items, scene_synced, active_scene_name, True)
                        if active_scene_has_source:
                            self._emit("overlay", EVENT_OVERLAY_SHOWN, "Overlay shown.")
                        else:
                            logger.info("Show requested, but the active scene has no source.")
                    elif action == HIDE:
                        sync_scene(client, scene_items, scene_synced, active_scene_name, False)
                        if active_scene_has_source:
                            self._emit("overlay", EVENT_OVERLAY_HIDDEN, "Overlay hidden.")
                        else:
                            logger.info("Hide requested, but the active scene has no source.")

                    # One other scene, at most, catches up per poll - the active scene
                    # already got its own write above, so this never costs more than a
                    # single extra request, and only while something is actually behind.
                    # A rejected write (the scene was deleted or renamed) is handled
                    # locally rather than torn down like a real connection failure.
                    dropped_scene = catch_up_one_stale_scene(
                        client, scene_items, scene_synced, active_scene_name, state.overlay_visible
                    )
                    if dropped_scene is not None:
                        # scene_items just lost an entry - overlay_available may no
                        # longer hold, the same recalculation done above whenever
                        # scene_items changes (scene switch, source found mid-scene).
                        overlay_available = any(
                            found is not None for found in scene_items.values()
                        )
                        self._emit(
                            "status",
                            EVENT_SCENE_DROPPED,
                            f"Scene '{dropped_scene}' is no longer available in OBS.",
                            subject=dropped_scene,
                        )

                    self._publish(
                        obs_snapshot(active_scene_name, scene_items, state.overlay_visible)
                    )
                    time.sleep(POLL_INTERVAL)
                except ObsConnectionError as exc:
                    error_message = str(exc)
                    # Always its own history entry: failure_in_history is guaranteed
                    # False here, since reaching this handler at all means a prior
                    # connect succeeded and reset it - this is a fresh drop, not a
                    # continuation of some already-recorded streak.
                    # Shown in the status line immediately: the reconnect attempt
                    # right behind it doesn't report anything of its own until its
                    # first tick, up to RECONNECT_TICK later - the status line must
                    # not go on saying "Connected to OBS." for that whole stretch.
                    # With auto reconnect off the service stops at once instead,
                    # and "stopped" takes over the status line.
                    self._emit(
                        "error",
                        EVENT_LINK_LOST,
                        error_message,
                        detail=describe_cause(exc),
                        state=RECONNECTING if cfg.auto_reconnect else None,
                    )
                    last_history_error = error_message
                    failure_in_history = True
                    # What OBS was last told is all that is known about what it
                    # is showing, and a told-to-show overlay stays up until
                    # something can tell it otherwise.
                    overlay_may_remain = state.overlay_visible
                    if overlay_may_remain:
                        self._emit("status", EVENT_OVERLAY_MAY_REMAIN, OVERLAY_MAY_REMAIN_NOTE)
                    disconnect_obs(client)
                    client = None
                    # desired_visible, overlay_visible, and hide_requested_at deliberately
                    # survive the drop. They are the only record of what the overlay should
                    # be, of what OBS was last told, and of a hide already counting down -
                    # the scene resolution above uses the first two to put things right on
                    # reconnect, and dropping the third would strand an already-armed hide.
                    active_scene_name = None
                    scene_synced = {}
                    # Nothing about OBS is known while the link is down.
                    self._publish(ObsSnapshot())
                    state = seed_key_edge_tracking(state, cfg, show_vk_codes, hide_vk_codes)
                    self._release_manual_input()
                    manual_key = None
                    if not cfg.auto_reconnect:
                        final_status_message = (
                            OBS_OVERLAY_MAY_REMAIN if overlay_may_remain else error_message
                        )
                        break
                    self._wait_with_countdown(
                        RECONNECT_DELAY, OVERLAY_MAY_REMAIN_NOTE if overlay_may_remain else None
                    )
        except Exception as exc:
            # Anything reaching here is a fault in MapHide rather than in the link to
            # OBS, which the clauses above already handle. Report it instead of letting
            # the worker thread die without a word; the block below still clears the
            # overlay either way.
            logger.error("Unexpected error: %s", describe_exception(exc))
            final_status_message = (
                f"MapHide stopped after an unexpected error ({type(exc).__name__})."
            )
        finally:
            # Nothing in this block may stop the "stopped" report below from
            # happening: the window waits on it before it lets you start again.
            if client is not None and scene_items:
                try:
                    set_overlay_enabled(client, scene_items, active_scene_name, False)
                except Exception as exc:
                    # Most likely the link died before the overlay could be
                    # cleared, so it may still be on screen. Say so rather than
                    # stopping quietly - whatever the cause.
                    logger.error(
                        "Could not hide the overlay while stopping: %s", describe_exception(exc)
                    )
                    final_status_message = OBS_OVERLAY_MAY_REMAIN
            if client is not None:
                try:
                    disconnect_obs(client)
                except Exception as exc:
                    logger.error(
                        "Could not close the OBS connection cleanly: %s", describe_exception(exc)
                    )

            # Emitted before the flag flips, not after: ui.py's restart polling
            # waits for is_running to go False before starting the replacement
            # worker, and must never be able to observe that before "stopped"
            # has already reached the queue - otherwise the new worker's own
            # events could land ahead of this one, and a stale "stopped" line
            # would end up in the history after theirs.
            self._publish(ObsSnapshot())
            try:
                self._emit(
                    "stopped",
                    EVENT_STOPPED,
                    final_status_message,
                    history=final_status_message != last_history_error,
                    state=STOPPED,
                )
            finally:
                self._running = False
