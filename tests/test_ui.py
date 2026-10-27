"""Tests for the parts of the window that can be checked without drawing it."""

from maphide.config import default_config
from maphide.overlay import CONNECTED, STOPPING, ServiceStatus
from maphide.ui import NOTICE_MS, MapHideApp, status_line


class _Var:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class _Label:
    def __init__(self):
        self.style = "Muted.TLabel"

    def configure(self, **options):
        self.style = options.get("style", self.style)


class _Root:
    def __init__(self):
        self.jobs = {}
        self._next_id = 0

    def after(self, milliseconds, callback):
        self._next_id += 1
        self.jobs[self._next_id] = (milliseconds, callback)
        return self._next_id

    def after_cancel(self, job):
        self.jobs.pop(job, None)


def make_app():
    """The window's notice handling without a window: only the pieces it
    touches are stood in for. It has no status variable at all, so a notice
    that tried to write the status line would fail here."""
    app = MapHideApp.__new__(MapHideApp)
    app.root = _Root()
    app.help_text_var = _Var()
    app.help_label = _Label()
    app.running_config = default_config()
    app.reset_confirm_pending = False
    app._notice_job = None
    return app


def run_pending_notice(app):
    ((_milliseconds, callback),) = app.root.jobs.values()
    app.root.jobs.clear()
    callback()


def test_the_status_line_shows_the_services_own_wording():
    status = ServiceStatus(CONNECTED, "Connected to OBS.")

    assert status_line(status, restart_pending=False) == "Connected to OBS."


def test_the_status_line_hides_the_stop_and_start_of_a_settings_restart():
    status = ServiceStatus(STOPPING, "Stopping...")

    assert status_line(status, restart_pending=True) == "Applying settings..."


def test_a_notice_replaces_the_help_text_and_is_scheduled_to_go():
    app = make_app()

    app._show_notice("Show key supports A-Z.")

    assert app.help_text_var.get() == "Show key supports A-Z."
    assert app.help_label.style == "Notice.TLabel"
    ((milliseconds, _callback),) = app.root.jobs.values()
    assert milliseconds == NOTICE_MS


def test_when_a_notice_clears_the_usual_help_comes_back():
    app = make_app()
    app._show_notice("Show key supports A-Z.")

    run_pending_notice(app)

    assert app.help_text_var.get() == "Hold G to show the overlay. Release G to hide it."
    assert app.help_label.style == "Muted.TLabel"


def test_a_newer_notice_takes_over_from_an_older_one():
    app = make_app()
    app._show_notice("First")
    app._show_notice("Second")

    assert app.help_text_var.get() == "Second"
    assert len(app.root.jobs) == 1


def test_refreshing_the_help_text_does_not_wipe_a_notice():
    app = make_app()
    app._show_notice("Show key supports A-Z.")

    app._update_help_text()

    assert app.help_text_var.get() == "Show key supports A-Z."


def test_a_reset_confirmation_lapses_when_its_notice_does():
    app = make_app()
    app._show_notice("Click Reset Defaults again to confirm.", confirms_reset=True)
    assert app.reset_confirm_pending is True

    run_pending_notice(app)

    assert app.reset_confirm_pending is False


def test_any_other_notice_cancels_a_pending_reset_confirmation():
    app = make_app()
    app._show_notice("Click Reset Defaults again to confirm.", confirms_reset=True)

    app._show_notice("Show key supports A-Z.")

    assert app.reset_confirm_pending is False
