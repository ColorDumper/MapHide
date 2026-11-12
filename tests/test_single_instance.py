"""Tests for the OS-level guard against two copies of MapHide running at once."""

import subprocess
import sys
import uuid

from maphide import single_instance


def _unique_name():
    # A real Windows named mutex, scoped to this one test so runs can never
    # see a name a previous test (or the real app) already holds.
    return f"Local\\MapHide-Test-{uuid.uuid4().hex}"


def test_the_first_acquire_of_a_name_succeeds():
    assert single_instance.acquire(_unique_name()) is True


def test_a_second_acquire_of_the_same_name_reports_already_running():
    name = _unique_name()
    assert single_instance.acquire(name) is True
    assert single_instance.acquire(name) is False


def test_two_different_names_do_not_interfere():
    assert single_instance.acquire(_unique_name()) is True
    assert single_instance.acquire(_unique_name()) is True


def test_a_launch_that_finds_one_running_does_not_keep_it_marked_running():
    # Another process holds the name, as a running MapHide would.
    name = _unique_name()
    holder = subprocess.Popen(  # noqa: S603 - this interpreter, fixed code
        [
            sys.executable,
            "-c",
            "import sys; from maphide import single_instance as s;"
            f" s.acquire({name!r}); print('held', flush=True); sys.stdin.read()",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        assert single_instance.acquire(name) is False

        holder.stdin.close()
        holder.wait(timeout=10)

        # Only the other process held it: once it's gone, so is the name.
        assert single_instance.is_running(name) is False
    finally:
        holder.kill()


# --- talking to the running copy ----------------------------------------------


def test_the_command_pipe_is_named_after_the_windows_user():
    name = single_instance.command_pipe_name("Alex")

    assert name.startswith("MapHide-")
    assert name == single_instance.command_pipe_name("alex")
    assert name != single_instance.command_pipe_name("Sam")
    assert "alex" not in name.lower()


def test_sending_with_nobody_listening_reports_not_delivered():
    pipe = f"MapHide-Test-{uuid.uuid4().hex}"

    assert single_instance.send_command("show", pipe_name=pipe, wait_ms=50) is False


def test_an_unknown_command_is_refused():
    try:
        single_instance.send_command("format-c")
    except ValueError:
        return
    raise AssertionError("an unknown command was sent")


def test_a_held_name_reads_as_running_without_being_taken():
    name = _unique_name()
    assert single_instance.is_running(name) is False

    assert single_instance.acquire(name) is True
    assert single_instance.is_running(name) is True
    # Asking didn't take it: it's still held by the first acquire only.
    assert single_instance.acquire(name) is False


def test_waiting_for_a_copy_that_never_closes_gives_up():
    name = _unique_name()
    single_instance.acquire(name)

    assert single_instance.wait_until_closed(0.2, name=name, poll_seconds=0.05) is False


def test_waiting_with_no_copy_running_returns_at_once():
    assert single_instance.wait_until_closed(5, name=_unique_name()) is True


def test_the_command_pipe_is_scoped_to_the_windows_session():
    assert single_instance.command_pipe_name("Alex", session=1) != (
        single_instance.command_pipe_name("Alex", session=2)
    )
