"""The worker: watches the keys, decides what the overlay should be, tells OBS."""

import queue
import threading
import time
from datetime import datetime, timedelta

from .hotkeys import HOTKEY_TO_VK, is_hotkey_down
from .obs import (
    ObsAuthError,
    ObsConnectionError,
    connect_obs,
    disconnect_obs,
    find_overlay_scene_items_raw,
    get_current_program_scene_raw,
    set_overlay_enabled_raw,
)

POLL_INTERVAL = 0.005
DEBOUNCE_MS = 50
SCENE_REFRESH_INTERVAL = 0.25
RECONNECT_DELAY = 2.0
OBS_OVERLAY_MAY_REMAIN = "MapHide stopped, but lost the connection before it could hide the overlay. Check OBS."


def human_ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class MapHideService:
    def __init__(
        self,
        show_vk_codes=None,
        show_hotkey_label="G",
        toggle_mode=False,
        hide_vk_codes=None,
        hide_hotkey_label="H",
    ):
        self.show_vk_codes = show_vk_codes or [HOTKEY_TO_VK["G"]]
        self.show_hotkey_label = show_hotkey_label
        self.toggle_mode = toggle_mode
        self.hide_vk_codes = hide_vk_codes or [HOTKEY_TO_VK["H"]]
        self.hide_hotkey_label = hide_hotkey_label
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
        self._events.put(
            {
                "kind": kind,
                "message": message,
                "timestamp": human_ts(),
            }
        )

    def _run(self, cfg):
        client = None
        overlay_visible = False
        desired_visible = False
        item_id = None
        scene_items = {}
        overlay_available = False
        active_scene_name = None
        last_action_time = datetime.min
        hide_requested_at = None
        last_scene_refresh = datetime.min
        announced_connection_failure = False
        final_status_message = "MapHide stopped."
        had_successful_connection = False
        show_key_was_down = False
        hide_key_was_down = False

        try:
            while not self._stop_event.is_set():
                if client is None:
                    try:
                        self._emit("status", "Connecting to OBS...")
                        client = connect_obs(cfg.host, cfg.port, cfg.password)
                        item_id = None
                        active_scene_name = None
                        last_scene_refresh = datetime.min
                        hide_requested_at = None
                        show_key_was_down = False
                        hide_key_was_down = False
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
                        latest_scene_name = get_current_program_scene_raw(client)
                        if latest_scene_name != active_scene_name:
                            active_scene_name = latest_scene_name
                            # Re-read every scene, not just this one: the source may have
                            # been added to a scene since the last look.
                            scene_items = find_overlay_scene_items_raw(client, cfg.scene_item_name)
                            item_id = scene_items.get(active_scene_name)
                            overlay_available = any(found is not None for found in scene_items.values())
                            hide_requested_at = None
                            if item_id is None:
                                self._emit(
                                    "status",
                                    f"Scene: {active_scene_name}. "
                                    f"Source '{cfg.scene_item_name}' not found.",
                                )
                            else:
                                if self.toggle_mode:
                                    status_message = (
                                        f"Scene: {active_scene_name}. "
                                        f"{self.show_hotkey_label} shows '{cfg.scene_item_name}', "
                                        f"{self.hide_hotkey_label} hides it."
                                    )
                                else:
                                    status_message = (
                                        f"Scene: {active_scene_name}. "
                                        f"Hold {self.show_hotkey_label} for '{cfg.scene_item_name}'."
                                    )
                                self._emit("status", status_message)
                            # OBS's actual state is unknown at this point: it restores
                            # sources enabled after a restart, and a dropped connection can
                            # strand one visible. Send our state rather than assume it
                            # already matches. In hold mode the key is the authority; in
                            # toggle mode the latched state is.
                            if not self.toggle_mode:
                                desired_visible = is_hotkey_down(self.show_vk_codes)
                            set_overlay_enabled_raw(
                                client, scene_items, active_scene_name, desired_visible
                            )
                            overlay_visible = desired_visible
                        last_scene_refresh = now

                    show_key_down = is_hotkey_down(self.show_vk_codes)
                    previous_desired = desired_visible

                    if self.toggle_mode:
                        hide_key_down = is_hotkey_down(self.hide_vk_codes)
                        show_pressed = show_key_down and not show_key_was_down
                        hide_pressed = hide_key_down and not hide_key_was_down
                        if overlay_available:
                            if self.show_vk_codes == self.hide_vk_codes:
                                if show_pressed:
                                    desired_visible = not desired_visible
                            else:
                                if show_pressed:
                                    desired_visible = True
                                if hide_pressed:
                                    desired_visible = False
                        show_key_was_down = show_key_down
                        hide_key_was_down = hide_key_down
                    else:
                        desired_visible = show_key_down

                    # The delay exists to cover a map's closing animation, so it runs
                    # from the moment the intent changes, not from whenever OBS is told.
                    if desired_visible != previous_desired:
                        hide_requested_at = None if desired_visible else now

                    if overlay_available and desired_visible != overlay_visible:
                        settled = (now - last_action_time) >= timedelta(milliseconds=DEBOUNCE_MS)
                        if desired_visible and settled:
                            set_overlay_enabled_raw(client, scene_items, active_scene_name, True)
                            overlay_visible = True
                            last_action_time = now
                            self._emit("overlay", "Overlay shown.")
                        elif (
                            not desired_visible
                            and settled
                            and hide_requested_at is not None
                            and (now - hide_requested_at) >= timedelta(milliseconds=cfg.hide_delay_ms)
                        ):
                            set_overlay_enabled_raw(client, scene_items, active_scene_name, False)
                            overlay_visible = False
                            last_action_time = now
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
                    item_id = None
                    active_scene_name = None
                    hide_requested_at = None
                    show_key_was_down = False
                    hide_key_was_down = False
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
                    set_overlay_enabled_raw(client, scene_items, active_scene_name, False)
                except ObsConnectionError:
                    # The link died before the overlay could be cleared, so it may
                    # still be on screen. Say so rather than stopping quietly.
                    final_status_message = OBS_OVERLAY_MAY_REMAIN
            if client is not None:
                disconnect_obs(client)

            self._running = False
            self._emit("stopped", final_status_message)
