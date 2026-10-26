"""Opt-in file logging, so a user's "it didn't hide" report has something to read.

Off by default. When enabled, the worker's status, overlay, and error events are
written to a rotating log next to the config file. Each app launch starts a fresh
file and keeps the previous couple, so a report is one session rather than a pile
of them. The password is never an event message, so it never reaches the log.
"""

import logging
import os
import re
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .paths import APP_VERSION, CONFIG_DIR

LOG_PATH = CONFIG_DIR / "maphide-debug.log"
LOGGER_NAME = "maphide"

MAX_BYTES = 512 * 1024
BACKUP_COUNT = 2

logger = logging.getLogger(LOGGER_NAME)
logger.propagate = False

_rolled_this_process = False


UNKNOWN_REASON = "an unexpected error occurred"


def plain_reason(exc):
    """A short reason to show in the window, in the system's own wording where
    it has one ("Permission denied"). Never str(exc): for most OS errors that
    carries the full file path, and with it the Windows user name."""
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror
    return UNKNOWN_REASON


def _scrub(text):
    """Show the user's home folder as ~, in the forms it takes inside an
    exception message (plain, forward slashes, and repr-escaped)."""
    try:
        home = str(Path.home())
    except RuntimeError:
        return text
    for form in {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}:
        text = re.sub(re.escape(form), "~", text, flags=re.IGNORECASE)
    return text


def describe_exception(exc):
    """One line for the debug log: the exception's type and message, and the
    last few places it passed through as file:function:line, with no folders."""
    frames = traceback.extract_tb(exc.__traceback__)[-4:]
    where = " <- ".join(
        f"{os.path.basename(frame.filename)}:{frame.name}:{frame.lineno}"
        for frame in reversed(frames)
    )
    return _scrub(f"{type(exc).__name__}: {exc} [{where}]")


def describe_cause(exc):
    """What an error was raised from, by type and error code only - the
    message of a network failure can carry the address it was talking to."""
    cause = exc.__cause__
    if cause is None:
        return None
    code = getattr(cause, "errno", None) or getattr(cause, "code", None)
    name = type(cause).__name__
    return f"{name} (code {code})" if code else name


def _rotated_name(default_name):
    """Keep the .log extension on rotated files: maphide-debug.log.1 -> maphide-debug.1.log."""
    root, dot, index = default_name.rpartition(".")
    if dot and index.isdigit() and root.endswith(".log"):
        return f"{root[: -len('.log')]}.{index}.log"
    return default_name


def configure_logging(enabled):
    """Attach or drop the rotating file handler. Safe to call on every
    (re)start. Returns None when there is nothing to report - `enabled` was
    False, or the handler attached fine - or an error message when it was
    True but the file could not be opened, the one case worth telling a
    caller about."""
    global _rolled_this_process

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    if not enabled:
        logger.setLevel(logging.CRITICAL)
        return None

    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_PATH, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    except OSError as exc:
        # A log file we cannot open is not a reason to stop MapHide - but
        # the caller still needs to know, so a user who asked for one isn't
        # left believing they have a report they don't.
        logger.setLevel(logging.CRITICAL)
        return plain_reason(exc)

    handler.namer = _rotated_name

    # Roll once per app launch, not per worker start: a Save Settings restarts the
    # worker mid-session and should keep writing to the same file.
    if not _rolled_this_process:
        try:
            if LOG_PATH.exists() and LOG_PATH.stat().st_size > 0:
                handler.doRollover()
        except OSError as exc:
            # The previous log can be held open by another program. Same
            # outcome as not being able to open the file at all, and the
            # handler must not be left holding it.
            handler.close()
            logger.setLevel(logging.CRITICAL)
            return plain_reason(exc)
        _rolled_this_process = True

    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("MapHide %s - logging started", APP_VERSION)
    return None
