"""Tests for the parts of the window that can be checked without drawing it."""

from maphide.overlay import CONNECTED, STOPPING, ServiceStatus
from maphide.ui import status_line


def test_the_status_line_shows_the_services_own_wording():
    status = ServiceStatus(CONNECTED, "Connected to OBS.")

    assert status_line(status, restart_pending=False) == "Connected to OBS."


def test_the_status_line_hides_the_stop_and_start_of_a_settings_restart():
    status = ServiceStatus(STOPPING, "Stopping...")

    assert status_line(status, restart_pending=True) == "Applying settings..."
