"""Tests for the opt-in rotating file log."""

import logging
from pathlib import Path

import pytest

from maphide import logs


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(logs, "LOG_PATH", tmp_path / "maphide-debug.log")
    monkeypatch.setattr(logs, "_rolled_this_process", False)
    yield tmp_path
    logs.configure_logging(False)


def test_disabled_attaches_no_handler(log_dir):
    logs.configure_logging(False)
    assert logs.logger.handlers == []
    logs.logger.info("nothing should be written")
    assert not (log_dir / "maphide-debug.log").exists()


def test_enabled_writes_events_to_the_file(log_dir):
    logs.configure_logging(True)
    logs.logger.info("status: %s", "Connected to OBS.")
    contents = (log_dir / "maphide-debug.log").read_text(encoding="utf-8")
    assert "logging started" in contents
    assert "Connected to OBS." in contents


def test_reconfigure_does_not_stack_handlers(log_dir):
    logs.configure_logging(True)
    logs.configure_logging(True)
    assert len(logs.logger.handlers) == 1


def test_enabling_then_disabling_detaches_the_handler(log_dir):
    logs.configure_logging(True)
    logs.configure_logging(False)
    assert logs.logger.handlers == []
    assert logs.logger.level == logging.CRITICAL


def test_a_worker_restart_keeps_writing_to_the_same_file(log_dir):
    logs.configure_logging(True)
    logs.logger.info("first line")
    logs.configure_logging(True)  # e.g. Save Settings restarts the worker
    logs.logger.info("second line")
    contents = (log_dir / "maphide-debug.log").read_text(encoding="utf-8")
    assert "first line" in contents and "second line" in contents
    assert not (log_dir / "maphide-debug.1.log").exists()


def test_a_new_launch_rolls_the_previous_log_aside(log_dir, monkeypatch):
    logs.configure_logging(True)
    logs.logger.info("old session")
    logs.configure_logging(False)

    monkeypatch.setattr(logs, "_rolled_this_process", False)
    logs.configure_logging(True)
    logs.logger.info("new session")

    # Rotated files keep the .log extension so Windows still opens them.
    assert not (log_dir / "maphide-debug.log.1").exists()
    assert "old session" in (log_dir / "maphide-debug.1.log").read_text(encoding="utf-8")
    current = (log_dir / "maphide-debug.log").read_text(encoding="utf-8")
    assert "new session" in current and "old session" not in current


# --- reporting whether logging actually started -----------------------------


def test_disabled_has_nothing_to_report(log_dir):
    assert logs.configure_logging(False) is None


def test_enabled_has_nothing_to_report_on_success(log_dir):
    assert logs.configure_logging(True) is None


def test_enabled_reports_an_error_when_the_file_cannot_be_opened(log_dir, monkeypatch):
    # A user who ticked "write a debug log" and got silence, with nothing
    # telling them it never actually started, has no way to know their bug
    # report will show up empty - this is the one case worth reporting.
    def refuse(*args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(logs, "RotatingFileHandler", refuse)

    error = logs.configure_logging(True)

    assert error is not None
    assert "Permission denied" in error
    assert logs.logger.handlers == []
    assert logs.logger.level == logging.CRITICAL


def test_a_start_failure_names_the_reason_but_not_the_file(log_dir, monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError(
            13, "Permission denied", r"C:\Users\someone\AppData\Roaming\MapHide\maphide-debug.log"
        )

    monkeypatch.setattr(logs, "RotatingFileHandler", refuse)

    error = logs.configure_logging(True)

    assert error == "Permission denied"


def test_plain_reason_prefers_the_systems_own_wording():
    error = OSError(13, "Permission denied", r"C:\Users\someone\config.json")
    assert logs.plain_reason(error) == "Permission denied"


def test_plain_reason_does_not_repeat_unknown_text():
    assert logs.plain_reason(ValueError(r"C:\Users\someone\x")) == "an unexpected error occurred"
    assert logs.plain_reason(OSError("no code")) == "an unexpected error occurred"


def _raise_with_home_in_message():
    raise KeyError(f"missing under {Path.home()}\\Documents")


def test_describe_exception_gives_type_message_and_place_without_the_home_folder():
    try:
        _raise_with_home_in_message()
    except KeyError as exc:
        text = logs.describe_exception(exc)

    assert "KeyError" in text
    assert "missing under ~" in text
    assert "test_logs.py:_raise_with_home_in_message:" in text
    assert str(Path.home()).lower() not in text.lower()


def test_describe_cause_names_the_underlying_failure_and_its_code():
    try:
        try:
            raise ConnectionResetError(10054, "reset by peer, host 10.0.0.2")
        except OSError as inner:
            raise RuntimeError("outer") from inner
    except RuntimeError as exc:
        assert logs.describe_cause(exc) == "ConnectionResetError (code 10054)"
    assert logs.describe_cause(RuntimeError("no cause")) is None


def test_a_previous_log_that_cannot_be_rolled_aside_is_reported_not_raised(log_dir, monkeypatch):
    # The previous session's log can be held open by another program, which
    # makes setting the new one aside fail. That is the same "could not start
    # the log" case as not being able to open the file, not a crash.
    log_file = log_dir / "maphide-debug.log"
    log_file.write_text("previous session\n", encoding="utf-8")

    def locked(self):
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(logs.RotatingFileHandler, "doRollover", locked)

    error = logs.configure_logging(True)

    assert error is not None
    assert "cannot access" in error
    assert logs.logger.handlers == []
    assert logs.logger.level == logging.CRITICAL
    # A handle left open would stop Windows deleting the file.
    log_file.unlink()
