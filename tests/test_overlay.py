"""Tests for the per-scene visibility tracking that lets a hotkey toggle touch
only the active scene while every other known scene still converges to the
same value shortly after.

Two scenarios get a dedicated regression test:
- a key blip landing on the same poll as a detected scene switch must not
  leak into what gets written to OBS, and
- a scene that isn't currently active must be caught up in the background
  before you switch back to it, not reactively (and visibly) at the moment
  you do.
"""

from datetime import datetime, timedelta

from maphide.config import AppConfig
from maphide.overlay import find_stale_scene, scene_is_stale, sync_scene
from maphide.state import HIDE, SHOW, OverlayState, decide

START = datetime(2026, 1, 1, 12, 0, 0)


def at(ms):
    return START + timedelta(milliseconds=ms)


def hold_config(hide_delay_ms=120):
    return AppConfig(
        host="10.0.0.2",
        port=4455,
        password="",
        scene_item_name="Overlay",
        hotkey="G",
        toggle_mode=False,
        hide_hotkey="H",
        hide_delay_ms=hide_delay_ms,
    )


class RecordingClient:
    def __init__(self):
        self.calls = []

    def send(self, req_type, payload, raw=True):
        self.calls.append((req_type, payload))
        return {}


def _scene_call(scene_name, scene_item_id, enabled):
    return (
        "SetSceneItemEnabled",
        {
            "sceneName": scene_name,
            "sceneItemId": scene_item_id,
            "sceneItemEnabled": enabled,
        },
    )


# --- scene_is_stale ----------------------------------------------------------


def test_scene_is_stale_when_never_synced():
    scene_items = {"Gameplay": 1}
    assert scene_is_stale(scene_items, {}, "Gameplay", True) is True
    assert scene_is_stale(scene_items, {}, "Gameplay", False) is True


def test_scene_is_not_stale_once_it_matches():
    scene_items = {"Gameplay": 1}
    scene_synced = {"Gameplay": True}
    assert scene_is_stale(scene_items, scene_synced, "Gameplay", True) is False


def test_scene_is_stale_again_once_the_target_changes():
    scene_items = {"Gameplay": 1}
    scene_synced = {"Gameplay": True}
    assert scene_is_stale(scene_items, scene_synced, "Gameplay", False) is True


def test_a_scene_without_the_source_is_never_stale():
    scene_items = {"Just Chatting": 2}  # no "Gameplay" entry at all
    assert scene_is_stale(scene_items, {}, "Gameplay", True) is False


# --- find_stale_scene ---------------------------------------------------------


def test_find_stale_scene_returns_the_first_one_needing_a_write():
    scene_items = {"Gameplay": 1, "Just Chatting": 2, "Break": 3}
    scene_synced = {"Gameplay": True}  # already matches; the other two do not

    assert find_stale_scene(scene_items, scene_synced, "Gameplay", True) == "Just Chatting"


def test_find_stale_scene_excludes_the_active_scene():
    scene_items = {"Gameplay": 1}
    # "Gameplay" is stale, but it is also the excluded (active) scene.
    assert find_stale_scene(scene_items, {}, "Gameplay", True) is None


def test_find_stale_scene_returns_none_once_everything_matches():
    scene_items = {"Gameplay": 1, "Just Chatting": 2}
    scene_synced = {"Gameplay": True, "Just Chatting": True}
    assert find_stale_scene(scene_items, scene_synced, "Gameplay", True) is None


# --- sync_scene ----------------------------------------------------------------


def test_sync_scene_writes_and_records_exactly_one_scene():
    client = RecordingClient()
    scene_items = {"Gameplay": 1, "Just Chatting": 2}
    scene_synced = {}

    sync_scene(client, scene_items, scene_synced, "Gameplay", True)

    assert client.calls == [_scene_call("Gameplay", 1, True)]
    assert scene_synced == {"Gameplay": True}


# --- regression: a blip during a scene switch must not leak into the write ---


def test_a_hold_mode_blip_never_reaches_a_write_for_either_scene():
    cfg = hold_config(hide_delay_ms=120)
    state = OverlayState()
    scene_items = {"Gameplay": 1, "Just Chatting": 2}
    scene_synced = {}
    client = RecordingClient()

    # Press and hold G on Gameplay: shows immediately, and the hot path
    # records it synced the same way overlay.py's SHOW branch would.
    state, action = decide(cfg, state, True, False, False, True, at(0))
    assert action == SHOW
    sync_scene(client, scene_items, scene_synced, "Gameplay", state.overlay_visible)

    # A brief real release lands on the same poll a scene switch to
    # "Just Chatting" is being handled. desired_visible reflects it (that's
    # correct, it's the raw key state) but overlay_visible must not, since
    # the hide hasn't survived its debounce and hide_delay yet.
    state, action = decide(cfg, state, False, False, False, True, at(10))
    assert action is None
    assert state.desired_visible is False
    assert state.overlay_visible is True

    # The entered scene has never been synced, so it needs a write - but it
    # must use the settled value, not anything derived from the blip.
    assert scene_is_stale(scene_items, scene_synced, "Just Chatting", state.overlay_visible)
    sync_scene(client, scene_items, scene_synced, "Just Chatting", state.overlay_visible)

    assert client.calls == [
        _scene_call("Gameplay", 1, True),
        _scene_call("Just Chatting", 2, True),
    ]

    # The key was released for real, though, so the ordinary hide-delay logic
    # still fires the hide once it elapses - untouched by any of the above.
    state, action = decide(cfg, state, False, False, False, True, at(200))
    assert action == HIDE
    assert state.overlay_visible is False


# --- regression: a scene must be caught up before you switch back to it -----


def test_background_catch_up_fixes_a_stale_scene_before_you_return_to_it():
    scene_items = {"Gameplay": 1, "Just Chatting": 2}
    scene_synced = {}
    client = RecordingClient()

    # Show while on Gameplay, then switch to Just Chatting (still shown) -
    # both scenes end up correctly synced to True.
    sync_scene(client, scene_items, scene_synced, "Gameplay", True)
    sync_scene(client, scene_items, scene_synced, "Just Chatting", True)

    # Release the key while on Just Chatting: only the active scene is
    # touched by the hot path, exactly like overlay.py's HIDE branch.
    sync_scene(client, scene_items, scene_synced, "Just Chatting", False)

    # At this instant, Gameplay is genuinely stale - left uncorrected, it
    # would still show True in OBS until something writes False to it.
    assert scene_is_stale(scene_items, scene_synced, "Gameplay", False) is True

    # One background catch-up step, run the way overlay.py runs it every
    # poll while on Just Chatting, fixes it well before anyone could
    # plausibly switch back.
    stale = find_stale_scene(scene_items, scene_synced, "Just Chatting", False)
    assert stale == "Gameplay"
    sync_scene(client, scene_items, scene_synced, stale, False)

    # Switching back now needs no write at all - nothing to flash.
    assert scene_is_stale(scene_items, scene_synced, "Gameplay", False) is False
    calls_before_returning = len(client.calls)
    if scene_is_stale(scene_items, scene_synced, "Gameplay", False):
        sync_scene(client, scene_items, scene_synced, "Gameplay", False)
    assert len(client.calls) == calls_before_returning

    assert client.calls == [
        _scene_call("Gameplay", 1, True),
        _scene_call("Just Chatting", 2, True),
        _scene_call("Just Chatting", 2, False),
        _scene_call("Gameplay", 1, False),
    ]
