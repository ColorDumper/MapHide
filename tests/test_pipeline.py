"""End-to-end tests of the worker against a fake OBS and a scripted keyboard.

These drive MapHideService the way a user does - hold a key, switch scenes,
lose the connection, delete the source - and check what ended up in OBS and
what the user was told. See fake_obs.py for the harness.
"""

from datetime import timedelta

import pytest
from fake_obs import FakeObs, Session, SteppableWallClock, make_config
from obsws_python.error import OBSSDKTimeoutError

import maphide.overlay as overlay_module


def standard_obs():
    """Three scenes: two carry the overlay, one doesn't. Every scene has a
    webcam first, so the overlay's item id is 2 and a write aimed at the wrong
    id would hit the webcam instead."""
    return FakeObs(
        {
            "Gameplay": ["Webcam", "Overlay"],
            "Camera": ["Webcam", "Overlay"],
            "Chatting": ["Webcam"],
        },
        current="Gameplay",
    )


def first_scene_read(s):
    return s.until(lambda: s.saw("New scene detected"), "the first scene to be read")


# --- the ordinary hotkey paths ------------------------------------------------


def test_holding_the_hotkey_shows_the_overlay_and_releasing_hides_it(monkeypatch):
    obs = standard_obs()
    session = Session(monkeypatch, make_config(), obs)

    def scenario(s):
        yield first_scene_read(s)
        s.keyboard.hold("G")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "the overlay to be shown")
        s.keyboard.release("G")
        yield s.until(lambda: obs.is_enabled("Gameplay") is False, "the overlay to be hidden")

    session.run(scenario)

    assert obs.is_enabled("Gameplay", "Webcam") is True
    assert obs.unexpected == []


def test_toggle_mode_shows_on_the_show_key_and_hides_on_the_hide_key(monkeypatch):
    obs = standard_obs()
    session = Session(monkeypatch, make_config(toggle_mode=True), obs)

    def scenario(s):
        yield first_scene_read(s)
        s.keyboard.hold("G")
        yield s.ticks(3)
        s.keyboard.release("G")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "the overlay to be shown")
        s.keyboard.hold("H")
        yield s.ticks(3)
        s.keyboard.release("H")
        yield s.until(lambda: obs.is_enabled("Gameplay") is False, "the overlay to be hidden")

    session.run(scenario)


def test_a_tap_that_ends_between_two_polls_still_toggles_in_toggle_mode(monkeypatch):
    obs = standard_obs()
    session = Session(monkeypatch, make_config(toggle_mode=True), obs)

    def scenario(s):
        yield first_scene_read(s)
        s.keyboard.tap("G")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "the overlay to be shown")

    session.run(scenario)


# --- scenes -------------------------------------------------------------------


def test_switching_scenes_while_shown_keeps_the_overlay_shown_in_the_new_scene(monkeypatch):
    obs = standard_obs()
    session = Session(monkeypatch, make_config(), obs)

    def scenario(s):
        yield first_scene_read(s)
        s.keyboard.hold("G")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "the overlay to be shown")
        obs.switch_to("Camera")
        yield s.until(lambda: obs.is_enabled("Camera"), "the overlay to follow to Camera")
        assert obs.is_enabled("Gameplay") is True
        s.keyboard.release("G")
        yield s.until(lambda: obs.enabled_scenes() == set(), "every scene to be hidden")

    session.run(scenario)


def test_releasing_on_a_scene_without_the_source_still_hides_it_everywhere_else(monkeypatch):
    obs = standard_obs()
    session = Session(monkeypatch, make_config(), obs)

    def scenario(s):
        yield first_scene_read(s)
        s.keyboard.hold("G")
        yield s.until(lambda: obs.enabled_scenes() == {"Gameplay", "Camera"}, "both to show")
        obs.switch_to("Chatting")
        yield s.until(lambda: s.saw("Switched to scene: Chatting"), "the switch to be noticed")
        s.keyboard.release("G")
        yield s.until(lambda: obs.enabled_scenes() == set(), "every scene to be hidden")

    session.run(scenario)

    assert any("Source 'Overlay' not found" in m for m in session.messages("status"))


# --- a lost connection --------------------------------------------------------


def test_a_dropped_connection_is_reported_and_the_overlay_state_is_restored(monkeypatch):
    obs = standard_obs()
    session = Session(monkeypatch, make_config(), obs)

    def scenario(s):
        yield first_scene_read(s)
        s.keyboard.hold("G")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "the overlay to be shown")
        # As if OBS had been restarted: the link drops and the overlay comes
        # back hidden, while the key is still held.
        obs.rule("GetCurrentProgramScene", raises=OBSSDKTimeoutError("timed out"))
        obs.set_enabled("Gameplay", False)
        yield s.until(lambda: obs.connections == 2, "a second connection")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "the overlay to be shown again")
        s.keyboard.release("G")
        yield s.until(lambda: obs.enabled_scenes() == set(), "every scene to be hidden")

    session.run(scenario)

    assert any("lost" in m for m in session.messages("error"))


# --- the source being removed and added back ----------------------------------


def test_removing_and_re_adding_the_source_recovers_with_a_single_reconnect(monkeypatch):
    obs = standard_obs()
    session = Session(monkeypatch, make_config(), obs)

    def scenario(s):
        yield first_scene_read(s)
        obs.remove_source("Gameplay")
        s.keyboard.hold("G")
        yield s.until(lambda: obs.connections == 2, "the refused write to reconnect")
        yield s.until(
            lambda: s.saw("Source 'Overlay' not found"), "the missing source to be reported"
        )
        obs.add_source("Gameplay")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "the overlay to be shown again")
        assert obs.connections == 2

    session.run(scenario)

    assert any("found in scene: Gameplay" in m for m in session.messages("status"))


def test_a_deleted_background_scene_is_dropped_without_reconnecting(monkeypatch):
    obs = standard_obs()
    session = Session(monkeypatch, make_config(), obs)

    def scenario(s):
        yield first_scene_read(s)
        s.keyboard.hold("G")
        yield s.until(lambda: obs.enabled_scenes() == {"Gameplay", "Camera"}, "both to show")
        obs.delete_scene("Camera")
        s.keyboard.release("G")
        yield s.until(
            lambda: s.saw("Scene 'Camera' is no longer available"), "the scene to be dropped"
        )
        yield s.until(lambda: obs.is_enabled("Gameplay") is False, "the active scene to hide")

    session.run(scenario)

    assert obs.connections == 1


# --- an OBS that answers badly or not at all ----------------------------------


def test_a_timeout_writing_to_a_background_scene_reconnects_instead_of_dropping_it(monkeypatch):
    # A write that times out says nothing about the scene - the link may be
    # unusable, and a late reply could be mistaken for the next answer - so it
    # has to go through the normal reconnect, not be treated as a deleted scene.
    obs = standard_obs()
    obs.rule(
        "SetSceneItemEnabled",
        raises=OBSSDKTimeoutError("timed out"),
        when=lambda payload: payload["sceneName"] == "Camera" and payload["sceneItemEnabled"],
    )
    session = Session(monkeypatch, make_config(), obs)

    def scenario(s):
        yield first_scene_read(s)
        s.keyboard.hold("G")
        yield s.until(lambda: obs.connections == 2, "the lost link to be reconnected")
        yield s.until(
            lambda: obs.enabled_scenes() == {"Gameplay", "Camera"}, "both scenes to show again"
        )

    session.run(scenario)

    assert not any("no longer available" in m for m in session.messages("status"))


@pytest.mark.parametrize(
    ("request_type", "rule"),
    [
        ("GetCurrentProgramScene", {"returns": None}),
        ("GetSceneList", {"returns": None}),
        ("GetSceneItemList", {"raises": KeyError("requestStatus")}),
        ("GetCurrentProgramScene", {"raises": TypeError("unexpected frame")}),
    ],
)
def test_an_unreadable_reply_reconnects_instead_of_stopping(monkeypatch, request_type, rule):
    obs = standard_obs()
    obs.rule(request_type, **rule)
    session = Session(monkeypatch, make_config(), obs)

    def scenario(s):
        yield s.until(lambda: obs.connections == 2, "a reconnect after the unreadable reply")
        yield first_scene_read(s)
        s.keyboard.hold("G")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "the overlay to be shown")

    session.run(scenario)

    assert any("could not read" in m for m in session.messages("error"))


# --- timing must not depend on the wall clock ---------------------------------


def test_stepping_the_clock_back_does_not_stop_the_overlay_hiding(monkeypatch):
    # A clock correction or a daylight-saving change moves the local clock
    # back. The overlay must still hide when the key is released.
    clock = SteppableWallClock(monkeypatch)
    obs = standard_obs()
    session = Session(monkeypatch, make_config(), obs)

    def scenario(s):
        yield first_scene_read(s)
        s.keyboard.hold("G")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "the overlay to be shown")
        clock.offset = timedelta(hours=-1)
        s.keyboard.release("G")
        yield s.until(
            lambda: obs.is_enabled("Gameplay") is False,
            "the overlay to be hidden after the clock stepped back",
            timeout=1.5,
        )

    session.run(scenario)


def test_stepping_the_clock_back_does_not_stop_scene_changes_being_noticed(monkeypatch):
    clock = SteppableWallClock(monkeypatch)
    obs = standard_obs()
    session = Session(monkeypatch, make_config(), obs)

    def scenario(s):
        yield first_scene_read(s)
        clock.offset = timedelta(hours=-1)
        obs.switch_to("Camera")
        yield s.until(
            lambda: s.saw("Switched to scene: Camera"),
            "the switch to be noticed after the clock stepped back",
            timeout=1.5,
        )

    session.run(scenario)


# --- the worker must always finish reporting ----------------------------------


def test_a_failure_while_clearing_the_overlay_on_stop_still_reports_stopped(monkeypatch):
    # The shutdown sweep talks to OBS once more. However that goes wrong, the
    # worker has to disconnect, say it stopped and stop claiming to be running -
    # the window waits on exactly that before it lets you start again.
    obs = standard_obs()
    session = Session(monkeypatch, make_config(), obs)
    obs.rule(
        "SetSceneItemEnabled",
        raises=KeyError("requestStatus"),
        times=None,
        when=lambda payload: session.service._stop_event.is_set(),
    )

    def scenario(s):
        yield first_scene_read(s)
        s.keyboard.hold("G")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "the overlay to be shown")

    session.run(scenario)

    assert session.service.is_running is False
    assert any(e["kind"] == "stopped" for e in session.events)
    assert obs.disconnected is True


def test_a_failure_setting_up_the_debug_log_does_not_leave_the_worker_stuck(monkeypatch):
    session = Session(monkeypatch, make_config(log_enabled=True), [])

    def locked(enabled):
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(overlay_module, "configure_logging", locked)

    session.run()

    assert session.service.is_running is False
    assert any(e["kind"] == "stopped" for e in session.events)
    assert any("debug log" in e["message"] for e in session.events)
