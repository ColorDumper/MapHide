"""Preventing two copies of MapHide from running at once and fighting over
the same hotkey and OBS connection."""

import ctypes
from ctypes import wintypes

# use_last_error=True routes GetLastError through ctypes' own thread-safe
# copy (read back with ctypes.get_last_error()) instead of the raw Win32
# value, which ctypes' own docs warn can be cleared as a side effect of
# other ctypes calls in between. CreateMutexW below sets that error itself,
# so nothing else needs to run in between for this to matter here - but it's
# the correct, documented way to read it regardless.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
# Declared so handles keep their full 64 bits; ctypes would otherwise read
# them as 32-bit ints.
_kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.OpenMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.WaitNamedPipeW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
_kernel32.WaitNamedPipeW.restype = wintypes.BOOL
_kernel32.ProcessIdToSessionId.argtypes = (wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
_kernel32.ProcessIdToSessionId.restype = wintypes.BOOL

MUTEX_NAME = "Local\\MapHide-SingleInstance"
ERROR_ALREADY_EXISTS = 183


def acquire(name=MUTEX_NAME):
    """True if this is the only running copy holding `name`.

    The winner's handle is deliberately never closed - it lives for the life
    of the process, and Windows releases it automatically on exit (including
    a crash), so a later launch can never be blocked by a copy that died
    uncleanly. A launch that finds `name` already held lets go of its handle
    at once: holding it would keep `name` marked as running after the real
    copy exits.
    """
    handle = _kernel32.CreateMutexW(None, False, name)
    if not handle:
        # Could not even ask the OS - fail open rather than block a
        # legitimate launch over something unrelated to another copy running.
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return False
    return True


# --- talking to the running copy -------------------------------------------
#
# The running copy listens on a named pipe for one-word commands. A second
# launch uses it to bring the running window forward instead of starting
# again, and `MapHide.exe --quit` uses it to close MapHide the same way Exit
# in the tray does. The pipe is named after the Windows user, so another
# user signed in on the same PC never reaches this one, and only this user
# can open it.

COMMAND_SHOW = "show"
COMMAND_QUIT = "quit"
COMMANDS = (COMMAND_SHOW, COMMAND_QUIT)

ERROR_FILE_NOT_FOUND = 2
SYNCHRONIZE = 0x00100000
# Lets whichever process the next command reaches bring its window forward.
# Windows only lets the program you just launched do that, so the launch
# hands the permission on.
ASFW_ANY = -1
PIPE_WAIT_MS = 2000
PIPE_PREFIX = r"\\.\pipe" + "\\"


def _session_id():
    """The Windows session this process runs in (one per signed-in user)."""
    import os

    session = wintypes.DWORD()
    if not _kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        return 0
    return session.value


def command_pipe_name(user=None, session=None):
    """The running copy's command pipe name for `user` in Windows `session`
    (this user and session by default), as Qt's QLocalServer takes it:
    without the pipe path prefix. Scoped to the session like MUTEX_NAME, so
    a copy signed in elsewhere at the same time is never reached."""
    import getpass
    import hashlib

    user = user if user is not None else getpass.getuser()
    session = session if session is not None else _session_id()
    key = f"{user.lower()}|{session}".encode("utf-8")
    return f"MapHide-{hashlib.sha256(key).hexdigest()[:16]}"


def send_command(command, pipe_name=None, wait_ms=PIPE_WAIT_MS):
    """Send `command` (one of COMMANDS) to the running copy. Returns whether
    it was delivered; False if no copy is listening."""
    if command not in COMMANDS:
        raise ValueError(f"Unknown command: {command!r}")
    path = PIPE_PREFIX + (pipe_name or command_pipe_name())
    if command == COMMAND_SHOW:
        ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    # Waits for the pipe to be free if the running copy is busy with
    # another connection; fails at once if nothing is listening.
    if not _kernel32.WaitNamedPipeW(path, wait_ms):
        return False
    return _write_line(path, f"{command}\n".encode("ascii"), wait_ms / 1000)


def _write_line(path, data, timeout_seconds):
    """Write `data` to the pipe at `path`, giving up after `timeout_seconds`.
    The write only finishes once the running copy reads it, so a copy that
    has stopped responding would otherwise hang this launch for good."""
    import threading

    delivered = []

    def write():
        try:
            with open(path, "wb", buffering=0) as pipe:
                pipe.write(data)
            delivered.append(True)
        except OSError:
            pass

    # A daemon thread: if the write never finishes, it doesn't hold up exit.
    writer = threading.Thread(target=write, name="SendCommand", daemon=True)
    writer.start()
    writer.join(timeout_seconds)
    return bool(delivered)


def is_running(name=MUTEX_NAME):
    """Whether a copy of MapHide holds `name`. Asks without taking it, unlike
    acquire()."""
    handle = _kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if not handle:
        return ctypes.get_last_error() != ERROR_FILE_NOT_FOUND
    _kernel32.CloseHandle(handle)
    return True


def wait_until_closed(timeout_seconds, name=MUTEX_NAME, poll_seconds=0.1):
    """Wait up to `timeout_seconds` for the running copy to exit. Returns
    whether it did."""
    import time

    deadline = time.monotonic() + timeout_seconds
    while is_running(name):
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_seconds)
    return True
