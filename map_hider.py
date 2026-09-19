"""
map_hider.py

Entry point for MapHide. Runs on the gaming PC, watches for the configured
key, and tells OBS on the streaming PC to show or hide the overlay source.

The application itself lives in the maphide package:
    config.py            the settings file: its shape, and reading and writing it
    hotkeys.py           reading the keyboard
    state.py             deciding what the overlay should be (pure, no I/O)
    overlay.py           the worker: polls the keys, runs the decision, drives OBS
    obs.py               talking to OBS over the WebSocket
    ui.py                the settings window and tray icon
    paths.py             where MapHide's files live
    logs.py              the opt-in debug log
    single_instance.py   the guard against two copies running at once
"""

import ctypes
import json
import queue
import sys

from maphide.config import default_config, load_config
from maphide.overlay import MapHideService, stop_wait_should_continue
from maphide.paths import CONFIG_PATH
from maphide.single_instance import acquire as acquire_single_instance

EVENT_POLL_SECONDS = 0.5
SHUTDOWN_POLL_SECONDS = 0.25
# A backstop, not a normal-case budget - see stop_wait_should_continue. The
# worker's own shutdown cleanup can legitimately take a moment (one OBS
# request per scene carrying the overlay source), so Ctrl+C polls for it to
# actually finish rather than giving up on a single fixed wait.
SHUTDOWN_WAIT_CEILING_SECONDS = 15
ALREADY_RUNNING_MESSAGE = "MapHide is already running."
ALREADY_RUNNING_NOTICE_MUTEX = "Local\\MapHide-AlreadyRunningNotice"
# Distinct from the main window's title ("MapHide") so FindWindowW below can
# only ever match this notice, never the app itself.
NOTICE_TITLE = "MapHide - Already Running"
# The standard Win32 dialog class MessageBoxW creates its window as.
NOTICE_WINDOW_CLASS = "#32770"
MB_ICONWARNING = 0x30

_show_message_box = ctypes.windll.user32.MessageBoxW
_find_window = ctypes.windll.user32.FindWindowW
_set_foreground_window = ctypes.windll.user32.SetForegroundWindow


def _wait_for_service_stop(service, ceiling_ms, poll_seconds=SHUTDOWN_POLL_SECONDS):
    """Block until the worker actually reports stopped, or a generous
    ceiling is reached - see maphide.overlay.stop_wait_should_continue.
    Rejoins the worker thread in short increments rather than a single fixed
    wait, so Ctrl+C can't cut a slow, multi-scene shutdown cleanup short.
    """
    elapsed_ms = 0.0
    while stop_wait_should_continue(service.is_running, elapsed_ms, ceiling_ms):
        service.wait(timeout=poll_seconds)
        elapsed_ms += poll_seconds * 1000


def run_headless():
    print(f"MapHide starting - reading config from {CONFIG_PATH}...")
    try:
        cfg = load_config()
    except (OSError, ValueError, KeyError) as exc:
        print("Failed to load config:", exc)
        print("Example config:")
        print(json.dumps(default_config().to_dict(), indent=2))
        sys.exit(1)

    service = MapHideService()
    service.start(cfg)
    if cfg.toggle_mode:
        print(
            f"Headless mode active. Press {cfg.hotkey} to SHOW the overlay; "
            f"press {cfg.hide_hotkey} to HIDE. Press Ctrl+C to exit."
        )
    else:
        print(
            f"Headless mode active. Hold {cfg.hotkey} to SHOW the overlay; "
            f"release to HIDE. Press Ctrl+C to exit."
        )

    try:
        while True:
            # The wait has a timeout so Ctrl+C is noticed on Windows, which means
            # a quiet spell is normal rather than a reason to stop.
            try:
                event = service.events.get(timeout=EVENT_POLL_SECONDS)
            except queue.Empty:
                if service.is_running:
                    continue
                break
            print(f"{event['timestamp']}  {event['message']}")
            if event["kind"] in {"error", "stopped"} and not service.is_running:
                break
    except KeyboardInterrupt:
        print("\nExiting - stopping service...")
        service.stop()
        _wait_for_service_stop(service, SHUTDOWN_WAIT_CEILING_SECONDS * 1000)


def run_selftest():
    """Import every module and bundled package the app needs, then exit.

    The build workflow runs this against the frozen executable so a missing
    PyInstaller hidden import fails CI instead of reaching a user. A windowed
    build has no console, so a clean exit (code 0) is the only pass signal.
    """
    import tkinter  # noqa: F401

    import pystray  # noqa: F401
    from PIL import Image, ImageDraw, ImageTk  # noqa: F401

    from maphide import obs, overlay, state, ui  # noqa: F401


def report_already_running(headless, notice_name=ALREADY_RUNNING_NOTICE_MUTEX):
    if headless:
        print(ALREADY_RUNNING_MESSAGE)
        return
    # A user clicking the exe several times in a row while it's already
    # running would otherwise pop one message box per click - each launch is
    # a separate process, so nothing but a second mutex could stop them
    # stacking up. Only the first one to grab it owns the box; every later
    # click brings that same one to the front instead of opening another.
    if not acquire_single_instance(notice_name):
        existing = _find_window(NOTICE_WINDOW_CLASS, NOTICE_TITLE)
        if existing:
            _set_foreground_window(existing)
        return
    # A plain Win32 message box, not Tk: this can fire before any window
    # exists, and a launch that's about to exit has no reason to spin one up.
    _show_message_box(0, ALREADY_RUNNING_MESSAGE, NOTICE_TITLE, MB_ICONWARNING)


def main():
    if "--selftest" in sys.argv:
        run_selftest()
        return

    headless = "--headless" in sys.argv

    if not acquire_single_instance():
        report_already_running(headless)
        sys.exit(1)

    if headless:
        run_headless()
    else:
        # Imported here so headless mode never needs Tk to be present.
        from maphide.ui import run_gui

        run_gui()


if __name__ == "__main__":
    main()
