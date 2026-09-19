"""Preventing two copies of MapHide from running at once and fighting over
the same hotkey and OBS connection."""

import ctypes

# use_last_error=True routes GetLastError through ctypes' own thread-safe
# copy (read back with ctypes.get_last_error()) instead of the raw Win32
# value, which ctypes' own docs warn can be cleared as a side effect of
# other ctypes calls in between. CreateMutexW below sets that error itself,
# so nothing else needs to run in between for this to matter here - but it's
# the correct, documented way to read it regardless.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MUTEX_NAME = "Local\\MapHide-SingleInstance"
ERROR_ALREADY_EXISTS = 183


def acquire(name=MUTEX_NAME):
    """True if this is the only running copy holding `name`.

    The handle is deliberately never closed - it lives for the life of the
    process, and Windows releases it automatically on exit (including a
    crash), so a later launch can never be blocked by a copy that died
    uncleanly.
    """
    handle = _kernel32.CreateMutexW(None, False, name)
    if not handle:
        # Could not even ask the OS - fail open rather than block a
        # legitimate launch over something unrelated to another copy running.
        return True
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS
