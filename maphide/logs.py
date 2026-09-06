"""Opt-in file logging, so a user's "it didn't hide" report has something to read.

Off by default. When enabled, the worker's status, overlay, and error events are
written to a rotating log next to the config file. Each app launch starts a fresh
file and keeps the previous couple, so a report is one session rather than a pile
of them. The password is never an event message, so it never reaches the log.
"""

import logging
from logging.handlers import RotatingFileHandler

from .paths import APP_VERSION, CONFIG_DIR

LOG_PATH = CONFIG_DIR / "maphide-debug.log"
LOGGER_NAME = "maphide"

MAX_BYTES = 512 * 1024
BACKUP_COUNT = 2

logger = logging.getLogger(LOGGER_NAME)
logger.propagate = False

_rolled_this_process = False


def _rotated_name(default_name):
    """Keep the .log extension on rotated files: maphide-debug.log.1 -> maphide-debug.1.log."""
    root, dot, index = default_name.rpartition(".")
    if dot and index.isdigit() and root.endswith(".log"):
        return f"{root[: -len('.log')]}.{index}.log"
    return default_name


def configure_logging(enabled):
    """Attach or drop the rotating file handler. Safe to call on every (re)start."""
    global _rolled_this_process

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    if not enabled:
        logger.setLevel(logging.CRITICAL)
        return

    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_PATH, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    except OSError:
        # A log file we cannot open is not a reason to stop MapHide.
        logger.setLevel(logging.CRITICAL)
        return

    handler.namer = _rotated_name

    # Roll once per app launch, not per worker start: a Save Settings restarts the
    # worker mid-session and should keep writing to the same file.
    if not _rolled_this_process:
        _rolled_this_process = True
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 0:
            handler.doRollover()

    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("MapHide %s - logging started", APP_VERSION)
