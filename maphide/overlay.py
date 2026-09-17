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
    get_current_scene,
    set_overlay_enabled,
)
from .state import HIDE, SHOW, OverlayState, decide

POLL_INTERVAL = 0.005
SCENE_REFRESH_INTERVAL = 0.25
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
    the other."""
    set_overlay_enabled(client, scene_items, scene_name, visible, all_scenes=False)
    scene_synced[scene_name] = visible


def scene_status(scene_name, is_first_detection=False):
    # No hotkey/mode explanation here - the help text below the log already
    # covers that, and repeating it made this line far too long for the space.
    verb = "New scene detected" if is_first_detection else "Switched to scene"
    return f"{verb}: {scene_name}."


def human_ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


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
        configure_logging(cfg.log_enabled)
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
                        # OBS's per-scene state is unverified again after any
                        # (re)connect - it restores sources enabled after a
                        # restart, and a dropped connection can strand one
                        # visible - so nothing already-confirmed here can be
                        # trusted going forward.
                        scene_synced = {}
                        state = replace(
                            state,
                            hide_requested_at=None,
                            show_key_was_down=False,
                            hide_key_was_down=False,
                        )
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
                            if scene_is_stale(
                                scene_items, scene_synced, active_scene_name, state.overlay_visible
                            ):
                                sync_scene(
                                    client,
                                    scene_items,
                                    scene_synced,
                                    active_scene_name,
                                    state.overlay_visible,
                                )
                        last_scene_refresh = now

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
                    stale_scene = find_stale_scene(
                        scene_items, scene_synced, active_scene_name, state.overlay_visible
                    )
                    if stale_scene is not None:
                        sync_scene(
                            client, scene_items, scene_synced, stale_scene, state.overlay_visible
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
                    # desired_visible and overlay_visible deliberately survive the drop.
                    # They are the only record of what the overlay should be and of what
                    # OBS was last told, and the scene resolution above uses them to put
                    # things right on reconnect.
                    active_scene_name = None
                    scene_synced = {}
                    state = replace(
                        state,
                        hide_requested_at=None,
                        show_key_was_down=False,
                        hide_key_was_down=False,
                    )
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

            self._running = False
            self._emit("stopped", final_status_message)
