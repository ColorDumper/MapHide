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

from dataclasses import replace
from datetime import datetime, timedelta

import maphide.overlay as overlay_module
from maphide.config import AppConfig
from maphide.obs import ObsAuthError
from maphide.overlay import (
    MapHideService,
    find_stale_scene,
    recheck_missing_source,
    scene_is_stale,
    scene_status,
    seed_key_edge_tracking,
    sync_scene,
)
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


class SceneItemLookupClient:
    """Like RecordingClient, but GetSceneItemList returns a configured
    response instead of {} - everything else is recorded the same way."""

    def __init__(self, get_scene_item_list_response):
        self.get_scene_item_list_response = get_scene_item_list_response
        self.calls = []

    def send(self, req_type, payload, raw=True):
        self.calls.append((req_type, payload))
        if req_type == "GetSceneItemList":
            return self.get_scene_item_list_response
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


# --- MapHideService._emit -----------------------------------------------------


def test_emit_includes_the_event_kind():
    # map_hider.py's run_headless() branches on event["kind"] to know when
    # an error or a stop means the run is truly over, not just mid-retry - a
    # dict missing that key crashes the moment the first event arrives.
    service = MapHideService()

    service._emit("status", "Connected to OBS.")

    event = service.events.get_nowait()
    assert event["kind"] == "status"


def test_stopped_is_queued_before_running_flips_false(monkeypatch):
    # ui.py's _finish_service_restart polls is_running to know when it is
    # safe to start the replacement worker after a Save Settings restart. If
    # "stopped" were queued *after* is_running flips False, a poll landing
    # in that gap could start the new worker - and let it enqueue its own
    # events - before the old "stopped" event even reaches the queue,
    # letting a stale "MapHide stopped." land on top of the new worker's
    # live status a moment after it was already showing something current.
    service = MapHideService()
    service._running = True  # normally set by start(), bypassed here
    running_when_stopped_was_emitted = []
    original_emit = service._emit

    def spying_emit(kind, message, **kwargs):
        if kind == "stopped":
            running_when_stopped_was_emitted.append(service.is_running)
        original_emit(kind, message, **kwargs)

    monkeypatch.setattr(service, "_emit", spying_emit)

    def fail_fast(host, port, password):
        raise ObsAuthError("bad password")

    monkeypatch.setattr(overlay_module, "connect_obs", fail_fast)

    cfg = AppConfig(
        host="10.0.0.2",
        port=4455,
        password="wrong",
        scene_item_name="Overlay",
        hotkey="G",
        toggle_mode=False,
        hide_hotkey="H",
    )

    # A bad password gives up immediately (no retry), reaching finally fast
    # and deterministically - run synchronously, no real thread needed.
    service._run(cfg)

    assert running_when_stopped_was_emitted == [True]


# --- seed_key_edge_tracking ---------------------------------------------------


def test_seed_key_edge_tracking_seeds_from_a_real_poll(monkeypatch):
    calls = []

    def fake_poll_hotkey(vk_codes):
        calls.append(list(vk_codes))
        return (vk_codes == [1], False)

    monkeypatch.setattr(overlay_module, "poll_hotkey", fake_poll_hotkey)
    cfg = replace(hold_config(), toggle_mode=True)

    seeded = seed_key_edge_tracking(OverlayState(), cfg, [1], [2])

    assert calls == [[1], [2]]
    assert seeded.show_key_was_down is True
    assert seeded.hide_key_was_down is False


def test_seed_key_edge_tracking_skips_the_hide_poll_in_hold_mode(monkeypatch):
    # Matches the same toggle_mode gate the main poll loop already uses -
    # hold mode never reads hide_key_was_down, so there is nothing to poll.
    calls = []

    def fake_poll_hotkey(vk_codes):
        calls.append(list(vk_codes))
        return (True, False)

    monkeypatch.setattr(overlay_module, "poll_hotkey", fake_poll_hotkey)
    cfg = hold_config()

    seeded = seed_key_edge_tracking(OverlayState(), cfg, [1], [2])

    assert calls == [[1]]
    assert seeded.hide_key_was_down is False


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


def test_sync_scene_does_not_mark_a_scene_synced_when_its_item_id_is_unknown():
    # A scene whose source hasn't been detected there yet (scene_items maps
    # it to None) has nothing to write to. Marking it "synced" anyway would
    # make scene_is_stale wrongly report it as already correct once the
    # source is later found there, permanently skipping the write it needs -
    # found via manual testing of the recheck_missing_source feature above.
    client = RecordingClient()
    scene_items = {"SceneA": 1, "SceneB": None}
    scene_synced = {}

    sync_scene(client, scene_items, scene_synced, "SceneB", True)

    assert client.calls == []
    assert scene_synced == {}


# --- recheck_missing_source ---------------------------------------------------


def test_recheck_missing_source_does_nothing_once_already_known():
    client = RecordingClient()
    scene_items = {"Gameplay": 7}

    found = recheck_missing_source(client, scene_items, "Gameplay", "Overlay")

    assert found is False
    assert client.calls == []  # never asks OBS - nothing to catch up on
    assert scene_items == {"Gameplay": 7}


def test_recheck_missing_source_still_not_found_changes_nothing():
    client = SceneItemLookupClient({"sceneItems": []})
    scene_items = {"Gameplay": None}

    found = recheck_missing_source(client, scene_items, "Gameplay", "Overlay")

    assert found is False
    assert scene_items == {"Gameplay": None}


def test_recheck_missing_source_finds_it_when_added():
    client = SceneItemLookupClient({"sceneItems": [{"sourceName": "Overlay", "sceneItemId": 7}]})
    scene_items = {"Gameplay": None}

    found = recheck_missing_source(client, scene_items, "Gameplay", "Overlay")

    assert found is True
    assert scene_items == {"Gameplay": 7}
    assert client.calls == [("GetSceneItemList", {"sceneName": "Gameplay"})]


# --- scene_status ----------------------------------------------------------------


def test_scene_status_reports_a_switch_by_default():
    assert scene_status("Gameplay") == "Switched to scene: Gameplay."


def test_scene_status_reports_first_detection_separately():
    assert scene_status("Gameplay", is_first_detection=True) == "New scene detected: Gameplay."


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


# --- regression: adding the source to the active scene needs no switch -----


def test_source_added_to_the_active_scene_is_picked_up_without_a_switch():
    cfg = hold_config(hide_delay_ms=0)
    scene_items = {"Gameplay": None}  # source isn't in the active scene yet
    scene_synced = {}
    client = SceneItemLookupClient({"sceneItems": [{"sourceName": "Overlay", "sceneItemId": 5}]})
    state = OverlayState()

    # G is pressed while the source is still missing - overlay_available is
    # False, so nothing happens, exactly like overlay.py's own gating.
    overlay_available = any(found is not None for found in scene_items.values())
    assert overlay_available is False
    state, action = decide(cfg, state, True, False, False, overlay_available, at(0))
    assert action is None

    # The source gets added to Gameplay in OBS. The periodic recheck (run
    # independently of any scene switch, the way overlay.py's _run() runs
    # it) picks it up.
    found = recheck_missing_source(client, scene_items, "Gameplay", cfg.scene_item_name)
    assert found is True
    overlay_available = any(found is not None for found in scene_items.values())
    assert overlay_available is True

    # G is still held - the very next poll now actually shows it, no scene
    # switch required.
    state, action = decide(cfg, state, True, False, False, overlay_available, at(10))
    assert action == SHOW
    sync_scene(client, scene_items, scene_synced, "Gameplay", state.overlay_visible)

    assert client.calls[-1] == _scene_call("Gameplay", 5, True)


def test_a_press_while_the_active_scenes_item_id_is_unknown_does_not_block_the_later_correction():
    # Regression for a real bug found via manual testing: overlay_available
    # can already be True because the source exists in a *different* scene,
    # so a press while on a scene whose item_id isn't known yet still fires
    # a SHOW/HIDE action and calls sync_scene - which used to mark that
    # scene "synced" anyway even though nothing was written, permanently
    # blocking the real write once the source was later found there too.
    cfg = hold_config(hide_delay_ms=0)
    scene_items = {"SceneA": 1, "SceneB": None}
    scene_synced = {}
    client = SceneItemLookupClient({"sceneItems": [{"sourceName": "Overlay", "sceneItemId": 7}]})
    state = OverlayState()
    overlay_available = any(found is not None for found in scene_items.values())
    assert overlay_available is True  # source already exists in SceneA

    # Press G while on SceneB, whose item_id isn't known yet.
    state, action = decide(cfg, state, True, False, False, overlay_available, at(0))
    assert action == SHOW
    sync_scene(client, scene_items, scene_synced, "SceneB", state.overlay_visible)
    assert client.calls == []  # nothing to write to yet

    # The source gets added to SceneB in OBS; the periodic recheck finds it.
    found = recheck_missing_source(client, scene_items, "SceneB", cfg.scene_item_name)
    assert found is True

    # SceneB must still be considered stale - the earlier "sync" never
    # actually wrote anything, so this is the first real chance to.
    assert scene_is_stale(scene_items, scene_synced, "SceneB", state.overlay_visible) is True
    sync_scene(client, scene_items, scene_synced, "SceneB", state.overlay_visible)

    assert client.calls[-1] == _scene_call("SceneB", 7, True)
