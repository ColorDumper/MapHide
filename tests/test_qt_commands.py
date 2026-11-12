"""A second launch of MapHide reaches the running copy over its command
pipe: a real pipe here, with Qt listening on one end as the app does."""

import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from maphide.qt.app import CommandServer  # noqa: E402
from maphide.single_instance import send_command  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def server(qt_app):
    received = []
    name = f"MapHide-Test-{uuid.uuid4().hex}"
    server = CommandServer(
        name,
        on_show=lambda: received.append("show"),
        on_quit=lambda: received.append("quit"),
    )
    assert server.listening
    yield name, received
    server.close()


def until(condition, seconds=3):
    end = time.monotonic() + seconds
    while not condition() and time.monotonic() < end:
        QGuiApplication.processEvents()
        time.sleep(0.01)
    return condition()


def send(command, name):
    """Send from a separate process, as a second launch of MapHide does,
    while this one keeps the listening side running."""
    code = (
        "import sys; from maphide.single_instance import send_command; "
        f"sys.exit(0 if send_command({command!r}, pipe_name={name!r}) else 1)"
    )
    # A fixed command with no outside input.
    sender = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT)  # noqa: S603
    until(lambda: sender.poll() is not None, seconds=10)
    return sender.wait(5) == 0


def test_show_reaches_the_running_copy(server):
    name, received = server

    assert send("show", name)

    assert until(lambda: received == ["show"])


def test_quit_reaches_the_running_copy(server):
    name, received = server

    assert send("quit", name)

    assert until(lambda: received == ["quit"])


def test_each_launch_is_heard(server):
    name, received = server

    for _ in range(3):
        assert send("show", name)

    assert until(lambda: received == ["show"] * 3)


def test_a_copy_that_has_stopped_responding_does_not_hang_the_launch(server):
    name, received = server

    # Nothing runs the listening side here, as if the running copy had frozen.
    started = time.monotonic()
    delivered = send_command("show", pipe_name=name, wait_ms=300)

    assert not delivered
    assert time.monotonic() - started < 2
