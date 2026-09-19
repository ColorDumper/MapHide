"""Tests for map_hider.py's entry point: the already-running notice's UX, and
the headless Ctrl+C shutdown-wait polling loop."""

import uuid

import map_hider


def _unique_notice_name():
    # A real Windows named mutex, scoped to this one test so runs can never
    # see a name a previous test (or the real app) already holds.
    return f"Local\\MapHide-Test-Notice-{uuid.uuid4().hex}"


def _patch_win32(monkeypatch, found_window=0):
    box_calls = []
    find_calls = []
    foreground_calls = []
    monkeypatch.setattr(map_hider, "_show_message_box", lambda *args: box_calls.append(args))
    # list.append() returns None, so `or found_window` records the call and
    # still hands back the fake window handle the real FindWindowW would.
    monkeypatch.setattr(
        map_hider, "_find_window", lambda *args: find_calls.append(args) or found_window
    )
    monkeypatch.setattr(
        map_hider, "_set_foreground_window", lambda *args: foreground_calls.append(args)
    )
    return box_calls, find_calls, foreground_calls


def test_a_gui_notice_shows_once_and_never_searches_for_an_existing_window(monkeypatch):
    box_calls, find_calls, foreground_calls = _patch_win32(monkeypatch)

    map_hider.report_already_running(headless=False, notice_name=_unique_notice_name())

    assert box_calls == [
        (0, map_hider.ALREADY_RUNNING_MESSAGE, map_hider.NOTICE_TITLE, map_hider.MB_ICONWARNING)
    ]
    assert find_calls == []
    assert foreground_calls == []


def test_repeated_gui_launches_bring_the_existing_notice_forward_instead_of_opening_another(
    monkeypatch,
):
    # Simulates a user clicking the exe several times in a row while it's
    # already running: each click is its own process, but they'd all race
    # for the same notice mutex here, so only the first should own the box -
    # every later click should just refocus that one, not open a new one.
    fake_hwnd = 4242
    box_calls, find_calls, foreground_calls = _patch_win32(monkeypatch, found_window=fake_hwnd)
    name = _unique_notice_name()

    map_hider.report_already_running(headless=False, notice_name=name)
    map_hider.report_already_running(headless=False, notice_name=name)
    map_hider.report_already_running(headless=False, notice_name=name)

    assert len(box_calls) == 1  # only the first launch ever opens one
    assert find_calls == [
        (map_hider.NOTICE_WINDOW_CLASS, map_hider.NOTICE_TITLE),
        (map_hider.NOTICE_WINDOW_CLASS, map_hider.NOTICE_TITLE),
    ]
    assert foreground_calls == [(fake_hwnd,), (fake_hwnd,)]


def test_a_missing_window_is_not_an_error(monkeypatch):
    # The owning notice could close between losing the mutex race and the
    # window search landing (FindWindowW returns 0) - nothing to focus, and
    # that must not raise or otherwise break the launch that lost the race.
    _, find_calls, foreground_calls = _patch_win32(monkeypatch, found_window=0)
    name = _unique_notice_name()
    map_hider.acquire_single_instance(name)  # simulate another launch already owning the notice

    map_hider.report_already_running(headless=False, notice_name=name)

    assert find_calls  # it did look
    assert foreground_calls == []  # but had nothing to bring forward


def test_a_new_notice_name_can_show_its_own_box(monkeypatch):
    # Once the mutex behind an old notice is released (the box was
    # dismissed and that process exited), a fresh notice must still work -
    # this isn't a one-shot latch, just a per-notice dedup.
    box_calls, _, _ = _patch_win32(monkeypatch)

    map_hider.report_already_running(headless=False, notice_name=_unique_notice_name())
    map_hider.report_already_running(headless=False, notice_name=_unique_notice_name())

    assert len(box_calls) == 2


def test_headless_prints_every_time_instead_of_deduping(capsys):
    # No modal window to stack up in headless mode, so nothing needs the
    # notice-mutex dance - every launch just prints its own line.
    map_hider.report_already_running(headless=True)
    map_hider.report_already_running(headless=True)

    out = capsys.readouterr().out
    assert out.count(map_hider.ALREADY_RUNNING_MESSAGE) == 2


# --- _wait_for_service_stop (Ctrl+C shutdown wait) ----------------------------
#
# Duck-typed in place of a real MapHideService: none of these tests actually
# sleep, since the fake's wait() just flips is_running by itself rather than
# joining a real thread - what's under test is the polling loop's logic
# (when does it stop calling wait() again?), not real timing.


class _FakeService:
    def __init__(self, stops_after_waits):
        self.is_running = True
        self.wait_calls = 0
        self._stops_after_waits = stops_after_waits

    def wait(self, timeout):
        self.wait_calls += 1
        if self.wait_calls >= self._stops_after_waits:
            self.is_running = False


def test_returns_as_soon_as_the_service_actually_stops():
    service = _FakeService(stops_after_waits=3)

    map_hider._wait_for_service_stop(service, ceiling_ms=10_000, poll_seconds=0.001)

    assert service.wait_calls == 3
    assert service.is_running is False


def test_a_slow_shutdown_within_the_ceiling_is_not_cut_short():
    # What the old fixed SHUTDOWN_WAIT_SECONDS=2 would have gotten wrong:
    # the worker takes longer than that to actually stop (e.g. still
    # writing "hide" to several scenes on the way out via
    # set_overlay_enabled's all_scenes sweep), but well within the new
    # ceiling - it must be waited out, not cut short.
    service = _FakeService(stops_after_waits=20)  # 20 * 0.25s poll = 5s > the old 2s wait

    map_hider._wait_for_service_stop(service, ceiling_ms=15_000, poll_seconds=0.25)

    assert service.wait_calls == 20
    assert service.is_running is False


def test_gives_up_at_the_ceiling_if_the_service_never_reports_stopped():
    # The backstop: Ctrl+C must still eventually let the process exit even
    # if something someday blocks past its own timeouts.
    service = _FakeService(stops_after_waits=10**9)  # never actually stops

    map_hider._wait_for_service_stop(service, ceiling_ms=5, poll_seconds=0.01)

    assert service.is_running is True  # gave up - not because it stopped
    assert service.wait_calls == 1  # one 10ms poll already clears the 5ms ceiling
