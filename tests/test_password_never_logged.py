"""The OBS password never reaches a log: not the debug log, not anything a
log handler could pick up, and not the console.

The OBS library itself logs the password on every connect, at info level.
MapHide turns that library's logging down to critical only; these tests
hold that in place, through MapHide's real connect code and the real
library."""

import logging
import socket
import time
from dataclasses import replace

import pytest

from maphide import logs
from maphide.config import default_config
from maphide.obs import ObsUnreachableError, connect_obs
from maphide.overlay import MapHideService

SECRET = "pw-that-must-never-be-logged-7f3a"  # noqa: S105 - a made-up test value


def closed_port():
    """A local port nothing listens on, so a connect fails at once."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Everything(logging.Handler):
    """Collects every record any logger lets through, at any level."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


def set_level(logger, level):
    """Set `logger`'s level, returning a way to put the old one back.
    setLevel, not the attribute: logging caches levels and only setLevel
    clears that."""
    old = logger.level
    logger.setLevel(level)
    return lambda: logger.setLevel(old)


@pytest.fixture
def captured():
    handler = Everything()
    root = logging.getLogger()
    restore = set_level(root, logging.DEBUG)
    root.addHandler(handler)
    # MapHide's own logger doesn't pass records up to the root.
    logs.logger.addHandler(handler)
    yield handler
    root.removeHandler(handler)
    logs.logger.removeHandler(handler)
    restore()


def try_to_connect():
    with pytest.raises(ObsUnreachableError):
        connect_obs("127.0.0.1", closed_port(), SECRET, timeout=1)


def test_connecting_never_logs_the_password(captured, capsys):
    try_to_connect()

    assert not [line for line in captured.lines if SECRET in line]
    assert SECRET not in capsys.readouterr().err


def test_the_check_above_would_catch_a_leak(captured):
    # The library logs the password unless MapHide quiets it.
    restore = set_level(logging.getLogger("obsws_python"), logging.DEBUG)
    try:
        try_to_connect()
    finally:
        restore()

    assert [line for line in captured.lines if SECRET in line]


def test_the_debug_log_never_holds_the_password(tmp_path, monkeypatch):
    log_file = tmp_path / "maphide-debug.log"
    monkeypatch.setattr(logs, "LOG_PATH", log_file)
    cfg = replace(
        default_config(),
        host="127.0.0.1",
        port=closed_port(),
        password=SECRET,
        scene_item_name="Overlay",
        auto_reconnect=False,
        log_enabled=True,
    )
    service = MapHideService()
    try:
        service.start(cfg)
        deadline = time.monotonic() + 10
        while service.is_running and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not service.is_running
    finally:
        service.stop()
        logs.configure_logging(False)

    written = log_file.read_text(encoding="utf-8")
    # It did log the failed connection, just never the password.
    assert "Failed to connect" in written
    assert SECRET not in written
