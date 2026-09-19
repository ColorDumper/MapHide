"""The worker: polls the keys, runs the overlay decision, drives OBS."""

import logging
import queue
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta

from .hotkeys import poll_hotkey
from .logs import configure_logging, logger
from .obs import (
    CONNECT_TIMEOUT,
    OBS_OVERLAY_MAY_REMAIN,
    ObsAuthError,
    ObsConnectionError,
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
    Returns the name of a scene dropped this way, or None."""
    stale_scene = find_stale_scene(scene_items, scene_synced, exclude, target_visible)
    if stale_scene is None:
        return None
    try:
        sync_scene(client, scene_items, scene_synced, stale_scene, target_visible)
    except ObsConnectionError:
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

    @property
    def events(self):
        return self._events

    @property
    def is_running(self):
        return self._running

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
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def wait(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _emit(self, kind, message, history=True, live=True):
        # The debug log always gets everything, either flag or not - that is
        # what it is for. `history` decides whether the in-app history list
        # also keeps this one; `live` decides whether it updates the live
        # status line. The two are independent: an overlay shown/hidden event
        # belongs in the history list but must not interrupt whatever the
        # live status is currently saying about the OBS connection itself.
        logger.log(logging.ERROR if kind == "error" else logging.INFO, "%s: %s", kind, message)
        self._events.put(
            {
                "kind": kind,
                "message": message,
                "timestamp": human_ts(),
                "history": history,
                "live": live,
            }
        )

    def _wait_with_countdown(self, total_seconds):
        """Wait up to total_seconds, interruptible, with a live-only status
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
            self._emit("status", f"Reconnecting... {elapsed:g}s", history=False)

    def _run(self, cfg):
        log_start_error = configure_logging(cfg.log_enabled)
        if log_start_error is not None:
            self._emit(
                "status",
                f"Could not start the debug log: {log_start_error}",
                live=False,
            )
        elif cfg.log_enabled:
            config_summary = ", ".join(
                f"{key}={value}" for key, value in cfg.to_loggable_dict().items()
            )
            logger.info("Config: %s", config_summary)
        show_vk_codes = cfg.show_vk_codes()
        hide_vk_codes = cfg.hide_vk_codes()
        same_key = show_vk_codes == hide_vk_codes
        client = None
        state = OverlayState()
        scene_items = {}
        scene_synced = {}
        overlay_available = False
        active_scene_name = None
        last_scene_refresh = datetime.min
        last_missing_source_check = datetime.min
        # Tracks whether the current run of failures already has a history
        # entry, separately from the live status (which shows every attempt).
        # Resets on a successful connect, so the next streak gets its own.
        failure_in_history = False
        final_status_message = "MapHide stopped."
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
                            self._emit("status", "Connecting to OBS...")
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
                        failure_in_history = False
                        had_successful_connection = True
                        self._emit("status", "Connected to OBS.")
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
                        # Shown live on every single attempt - a retry that is still
                        # failing should keep saying so, not go quiet after the first
                        # time. Only the history entry is limited to one per streak.
                        self._emit("error", error_message, history=not failure_in_history)
                        failure_in_history = True
                        if give_up:
                            final_status_message = error_message
                            break
                        self._wait_with_countdown(RECONNECT_DELAY)
                        continue

                now = datetime.now()
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
                            # live=False: a scene change is worth a history line, but it
                            # is not part of the OBS connection's own story, and must
                            # not interrupt whatever the live status is saying about that.
                            status_message = scene_status(active_scene_name, is_first_detection)
                            if scene_items.get(active_scene_name) is None:
                                status_message += f" Source '{cfg.scene_item_name}' not found."
                            self._emit("status", status_message, live=False)
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
                                f"Source '{cfg.scene_item_name}' found in scene: "
                                f"{active_scene_name}.",
                                live=False,
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
                    # live=False on both: how often the map itself gets toggled has
                    # nothing to do with what the live status is saying about the
                    # OBS connection, and toggling it should never interrupt that.
                    if action == SHOW:
                        sync_scene(client, scene_items, scene_synced, active_scene_name, True)
                        self._emit("overlay", "Overlay shown.", live=False)
                    elif action == HIDE:
                        sync_scene(client, scene_items, scene_synced, active_scene_name, False)
                        self._emit("overlay", "Overlay hidden.", live=False)

                    # One other scene, at most, catches up per poll - the active scene
                    # already got its own write above, so this never costs more than a
                    # single extra request, and only while something is actually behind.
                    # A rejected write (the scene was deleted or renamed) is handled
                    # locally rather than torn down like a real connection failure.
                    dropped_scene = catch_up_one_stale_scene(
                        client, scene_items, scene_synced, active_scene_name, state.overlay_visible
                    )
                    if dropped_scene is not None:
                        self._emit(
                            "status",
                            f"Scene '{dropped_scene}' is no longer available in OBS.",
                            live=False,
                        )

                    time.sleep(POLL_INTERVAL)
                except ObsConnectionError as exc:
                    error_message = str(exc)
                    # Always its own history entry: failure_in_history is guaranteed
                    # False here, since reaching this handler at all means a prior
                    # connect succeeded and reset it - this is a fresh drop, not a
                    # continuation of some already-recorded streak.
                    # live=False: the reconnect attempt right behind it is about to
                    # take over the live status anyway, so this only needs to be
                    # logged, not shown live for the instant before that happens.
                    self._emit("error", error_message, live=False)
                    failure_in_history = True
                    disconnect_obs(client)
                    client = None
                    # desired_visible, overlay_visible, and hide_requested_at deliberately
                    # survive the drop. They are the only record of what the overlay should
                    # be, of what OBS was last told, and of a hide already counting down -
                    # the scene resolution above uses the first two to put things right on
                    # reconnect, and dropping the third would strand an already-armed hide.
                    active_scene_name = None
                    scene_synced = {}
                    state = seed_key_edge_tracking(state, cfg, show_vk_codes, hide_vk_codes)
                    if not cfg.auto_reconnect:
                        final_status_message = error_message
                        break
                    self._wait_with_countdown(RECONNECT_DELAY)
        except Exception as exc:
            # Anything reaching here is a fault in MapHide rather than in the link to
            # OBS, which the clauses above already handle. Report it instead of letting
            # the worker thread die without a word; the block below still clears the
            # overlay either way.
            final_status_message = f"MapHide stopped after an unexpected error: {exc}"
        finally:
            if client is not None and scene_items:
                try:
                    set_overlay_enabled(client, scene_items, active_scene_name, False)
                except ObsConnectionError:
                    # The link died before the overlay could be cleared, so it may
                    # still be on screen. Say so rather than stopping quietly.
                    final_status_message = OBS_OVERLAY_MAY_REMAIN
            if client is not None:
                disconnect_obs(client)

            # Emitted before the flag flips, not after: ui.py's restart polling
            # waits for is_running to go False before starting the replacement
            # worker, and must never be able to observe that before "stopped"
            # has already reached the queue - otherwise the new worker's own
            # events could land ahead of this one, and a stale "stopped" would
            # overwrite a live status that had already moved on.
            self._emit("stopped", final_status_message)
            self._running = False
