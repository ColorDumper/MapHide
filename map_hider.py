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

import sys

from maphide.config import load_config
from maphide.overlay import MapHideService
from maphide.paths import CONFIG_PATH


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

    service = MapHideService(
        show_vk_codes=cfg.hotkey_vk_code(),
        show_hotkey_label=cfg.hotkey,
        toggle_mode=cfg.toggle_mode,
        hide_vk_codes=cfg.hide_hotkey_vk_code(),
        hide_hotkey_label=cfg.hide_hotkey,
    )
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
            event = service.events.get(timeout=0.5)
            print(f"{event['timestamp']}  {event['message']}")
            if event["kind"] in {"error", "stopped"} and not service.is_running:
                break
    except KeyboardInterrupt:
        print("\nExiting - stopping service...")
        service.stop()
        service.wait(timeout=2)



def main():
    if "--headless" in sys.argv:
        run_headless()
    else:
        # Imported here so headless mode never needs Tk to be present.
        from maphide.ui import run_gui

        run_gui()


if __name__ == "__main__":
    main()
