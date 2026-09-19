"""Preventing two copies of MapHide from running at once and fighting over
the same hotkey and OBS connection."""

import ctypes

MUTEX_NAME = "Local\\MapHide-SingleInstance"
ERROR_ALREADY_EXISTS = 183


def acquire(name=MUTEX_NAME):
    """True if this is the only running copy holding `name`.

    The handle is deliberately never closed - it lives for the life of the
    process, and Windows releases it automatically on exit (including a
    crash), so a later launch can never be blocked by a copy that died
    uncleanly.
    """
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
    if not handle:
        # Could not even ask the OS - fail open rather than block a
        # legitimate launch over something unrelated to another copy running.
        return True
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS
