"""The worker: polls the keys, runs the overlay decision, drives OBS."""

import logging
import queue
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta

from .hotkeys import is_hotkey_down
from .logs import configure_logging, logger
from .obs import (
    OBS_OVERLAY_MAY_REMAIN,
    ObsAuthError,
    ObsConnectionError,
    connect_obs,
    disconnect_obs,
    find_overlay_scene_items,
    get_current_scene,
    set_overlay_enabled,
)
from .state import HIDE, SHOW, OverlayState, decide

POLL_INTERVAL = 0.005
SCENE_REFRESH_INTERVAL = 0.25
RECONNECT_DELAY = 2.0


def scene_status(cfg, scene_name):
    if cfg.toggle_mode:
        return (
            f"Scene: {scene_name}. "
            f"{cfg.hotkey} shows '{cfg.scene_item_name}', "
            f"{cfg.hide_hotkey} hides it."
        )
    return f"Scene: {scene_name}. Hold {cfg.hotkey} for '{cfg.scene_item_name}'."


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

    def _emit(self, kind, message):
        logger.log(logging.ERROR if kind == "error" else logging.INFO, "%s: %s", kind, message)
        self._events.put(
            {
                "kind": kind,
                "message": message,
                "timestamp": human_ts(),
            }
        )

    def _run(self, cfg):
        configure_logging(cfg.log_enabled)
        show_vk_codes = cfg.show_vk_codes()
        hide_vk_codes = cfg.hide_vk_codes()
        same_key = show_vk_codes == hide_vk_codes
        client = None
        state = OverlayState()
        scene_items = {}
        overlay_available = False
        active_scene_name = None
        last_scene_refresh = datetime.min
        announced_connection_failure = False
        final_status_message = "MapHide stopped."
        had_successful_connection = False

        try:
            while not self._stop_event.is_set():
                if client is None:
                    try:
                        self._emit("status", "Connecting to OBS...")
                        client = connect_obs(cfg.host, cfg.port, cfg.password)
                        active_scene_name = None
                        last_scene_refresh = datetime.min
                        state = replace(
                            state,
                            hide_requested_at=None,
                            show_key_was_down=False,
                            hide_key_was_down=False,
                        )
                        announced_connection_failure = False
                        had_successful_connection = True
                        self._emit("status", "Connected to OBS.")
                    except ObsConnectionError as exc:
                        error_message = str(exc)
                        if not announced_connection_failure:
                            self._emit("error", error_message)
                            announced_connection_failure = True
                        # A wrong password will not start working on its own, and a
                        # first attempt that never succeeded usually means the settings
                        # are wrong. Both wait for the user instead of retrying forever.
                        if isinstance(exc, ObsAuthError) or not had_successful_connection:
                            final_status_message = error_message
                            break
                        time.sleep(RECONNECT_DELAY)
                        continue

                now = datetime.now()
                try:
                    if (now - last_scene_refresh) >= timedelta(seconds=SCENE_REFRESH_INTERVAL):
                        latest_scene_name = get_current_scene(client)
                        if latest_scene_name != active_scene_name:
                            active_scene_name = latest_scene_name
                            # Re-read every scene, not just this one: the source may have
                            # been added to a scene since the last look.
                            scene_items = find_overlay_scene_items(client, cfg.scene_item_name)
                            overlay_available = any(
                                found is not None for found in scene_items.values()
                            )
                            if scene_items.get(active_scene_name) is None:
                                self._emit(
                                    "status",
                                    f"Scene: {active_scene_name}. "
                                    f"Source '{cfg.scene_item_name}' not found.",
                                )
                            else:
                                self._emit("status", scene_status(cfg, active_scene_name))
                            # OBS's actual state is unknown at this point: it restores
                            # sources enabled after a restart, and a dropped connection can
                            # strand one visible. Send our state rather than assume it
                            # already matches. In hold mode the key is the authority; in
                            # toggle mode the latched state is.
                            desired_visible = (
                                state.desired_visible
                                if cfg.toggle_mode
                                else is_hotkey_down(show_vk_codes)
                            )
                            set_overlay_enabled(
                                client, scene_items, active_scene_name, desired_visible
                            )
                            state = replace(
                                state,
                                desired_visible=desired_visible,
                                overlay_visible=desired_visible,
                                hide_requested_at=None,
                            )
                        last_scene_refresh = now

                    state, action = decide(
                        cfg,
                        state,
                        is_hotkey_down(show_vk_codes),
                        is_hotkey_down(hide_vk_codes) if cfg.toggle_mode else False,
                        same_key,
                        overlay_available,
                        now,
                    )
                    if action == SHOW:
                        set_overlay_enabled(client, scene_items, active_scene_name, True)
                        self._emit("overlay", "Overlay shown.")
                    elif action == HIDE:
                        set_overlay_enabled(client, scene_items, active_scene_name, False)
                        self._emit("overlay", "Overlay hidden.")

                    time.sleep(POLL_INTERVAL)
                except ObsConnectionError as exc:
                    self._emit("error", str(exc))
                    disconnect_obs(client)
                    client = None
                    # desired_visible and overlay_visible deliberately survive the drop.
                    # They are the only record of what the overlay should be and of what
                    # OBS was last told, and the scene resolution above uses them to put
                    # things right on reconnect.
                    active_scene_name = None
                    state = replace(
                        state,
                        hide_requested_at=None,
                        show_key_was_down=False,
                        hide_key_was_down=False,
                    )
                    time.sleep(RECONNECT_DELAY)
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
