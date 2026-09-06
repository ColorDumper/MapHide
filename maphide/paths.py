"""Where MapHide's files live, in a source checkout and in a frozen build."""

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller: bundled data lives under sys._MEIPASS (a temp dir for
    # one-file builds, the _internal folder for one-dir builds).
    APP_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    # This module sits one level down in the package, so the assets and the
    # entry point are in the parent directory.
    APP_DIR = Path(__file__).resolve().parent.parent
APP_NAME = "MapHide"
APP_VERSION = "v0.2.5"
CONFIG_DIR = Path(os.getenv("APPDATA", APP_DIR)) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"
LEGACY_CONFIG_PATH = APP_DIR / "config.json"
ICON_ICO_PATH = APP_DIR / "MapHide.ico"
ICON_RUNTIME_PNG_PATH = APP_DIR / "assets" / "MapHide_Icon.png"
ICON_WINDOW_PNG_PATH = APP_DIR / "assets" / "MapHide_Icon_32.png"
ICON_TRAY_PNG_PATH = APP_DIR / "assets" / "MapHide_Icon_64.png"
WATERMARK_PNG_PATH = APP_DIR / "assets" / "MapHide_Watermark.png"
APP_USER_MODEL_ID = "MapHide.App"
