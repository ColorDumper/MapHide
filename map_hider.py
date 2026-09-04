"""
map_hider.py

Entry point for MapHide. Runs on the gaming PC, watches for the configured
key, and tells OBS on the streaming PC to show or hide the overlay source.

The application itself lives in the maphide package:
    hotkeys.py  reading the keyboard
    overlay.py  deciding what the overlay should be
    obs.py      sending that to OBS over the WebSocket
    ui.py       the settings window and tray icon
"""

import queue
import sys

from maphide.config import load_config
from maphide.overlay import MapHideService
from maphide.paths import CONFIG_PATH

EVENT_POLL_SECONDS = 0.5
SHUTDOWN_WAIT_SECONDS = 2


def run_headless():
    print(f"MapHide starting - reading config from {CONFIG_PATH}...")
    try:
        cfg = load_config()
    except (OSError, ValueError, KeyError) as exc:
        print("Failed to load config:", exc)
        print(
            'Example config:\n{\n'
            '  "host":"",\n'
            '  "port":4455,\n'
            '  "password":"",\n'
            '  "scene_item_name":"",\n'
            '  "auto_connect":false,\n'
            '  "hotkey":"G",\n'
            '  "toggle_mode":false,\n'
            '  "hide_hotkey":"H",\n'
            '  "hide_delay_ms":120\n}'
        )
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
        service.wait(timeout=SHUTDOWN_WAIT_SECONDS)



def main():
    if "--headless" in sys.argv:
        run_headless()
    else:
        # Imported here so headless mode never needs Tk to be present.
        from maphide.ui import run_gui

        run_gui()


if __name__ == "__main__":
    main()
