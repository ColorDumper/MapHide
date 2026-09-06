"""Tests for the opt-in rotating file log."""

import logging

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
