"""A stand-in for OBS and the keyboard, so the whole worker can run end to end.

FakeObs behaves like the obsws-python client MapHide talks to: it keeps real
scenes and sources, answers the requests MapHide makes with the same response
shapes and error codes, and can be told to fail, time out or reply oddly at
exact points. FakeKeyboard stands in for the key state Windows reports.

Session runs MapHideService against both. A scenario is a generator that
drives the keyboard and OBS and yields what to wait for next, so a test reads
top to bottom:

    def scenario(s):
        s.keyboard.hold("G")
        yield s.until(lambda: obs.is_enabled("Gameplay"), "overlay shown")
        s.keyboard.release("G")
        yield s.until(lambda: not obs.is_enabled("Gameplay"), "overlay hidden")

Waits run on real time at the worker's real poll rate, so the debounce and
hide delay behave exactly as they do for a user.
"""

import time
from datetime import datetime, timedelta

from obsws_python.error import OBSSDKRequestError

import maphide.hotkeys as hotkeys_module
import maphide.overlay as overlay_module
from maphide.config import AppConfig
from maphide.hotkeys import HOTKEY_TO_VK
from maphide.obs import ObsAuthError
from maphide.overlay import MapHideService

OVERLAY = "Overlay"
_UNSET = object()


def make_config(**overrides):
    values = {
        "host": "10.0.0.2",
        "port": 4455,
        "password": "",
        "scene_item_name": OVERLAY,
        "hotkey": "G",
        "toggle_mode": False,
        "hide_hotkey": "H",
        "hide_delay_ms": 0,
    }
    values.update(overrides)
    return AppConfig(**values)


class FakeObs:
    """Scenes hold named sources; each source gets a scene-local item id, the
    way OBS numbers them. The overlay source starts hidden and everything else
    starts visible."""

    def __init__(self, scenes, current=None, overlay=OVERLAY):
        self.overlay = overlay
        self.scenes = {}
        self._next_id = {}
        for scene, sources in scenes.items():
            self.add_scene(scene, sources)
        self.current = current if current is not None else next(iter(self.scenes))
        self.calls = []
        self.unexpected = []
        self.connections = 0
        self.disconnected = False
        self._rules = []

    # --- changing what OBS contains ------------------------------------------

    def add_scene(self, scene, sources=()):
        self.scenes[scene] = {}
        self._next_id[scene] = 1
        for source in sources:
            self.add_source(scene, source)

    def add_source(self, scene, source=None):
        source = source or self.overlay
        item_id = self._next_id[scene]
        self._next_id[scene] += 1
        self.scenes[scene][source] = {"id": item_id, "enabled": source != self.overlay}
        return item_id

    def remove_source(self, scene, source=None):
        del self.scenes[scene][source or self.overlay]

    def delete_scene(self, scene):
        del self.scenes[scene]

    def rename_scene(self, old, new):
        self.scenes = {
            (new if name == old else name): items for name, items in self.scenes.items()
        }
        self._next_id[new] = self._next_id.pop(old)
        if self.current == old:
            self.current = new

    def switch_to(self, scene):
        self.current = scene

    def set_enabled(self, scene, enabled, source=None):
        self.scenes[scene][source or self.overlay]["enabled"] = enabled

    # --- looking at what OBS contains ----------------------------------------

    def item_id(self, scene, source=None):
        return self.scenes[scene][source or self.overlay]["id"]

    def is_enabled(self, scene, source=None):
        """True or False, or None when the scene or source isn't there."""
        item = self.scenes.get(scene, {}).get(source or self.overlay)
        return None if item is None else item["enabled"]

    def enabled_scenes(self):
        return {name for name in self.scenes if self.is_enabled(name)}

    # --- scripted failures ---------------------------------------------------

    def rule(self, req_type, *, raises=None, returns=_UNSET, times=1, after=0, when=None):
        """Make a request fail or answer oddly. It fires on matching requests
        after the first `after` of them, `times` times (None for always).
        `when` narrows it to requests whose payload it accepts."""
        self._rules.append(
            {
                "req_type": req_type,
                "raises": raises,
                "returns": returns,
                "times": times,
                "after": after,
                "when": when,
                "seen": 0,
                "fired": 0,
            }
        )

    def _matching_rule(self, req_type, payload):
        for rule in self._rules:
            if rule["req_type"] != req_type:
                continue
            if rule["when"] is not None and not rule["when"](payload):
                continue
            rule["seen"] += 1
            if rule["seen"] > rule["after"] and (
                rule["times"] is None or rule["fired"] < rule["times"]
            ):
                rule["fired"] += 1
                return rule
        return None

    # --- the client surface MapHide uses -------------------------------------

    def send(self, req_type, payload=None, raw=False):
        self.calls.append((req_type, payload))
        rule = self._matching_rule(req_type, payload)
        if rule is not None:
            if rule["raises"] is not None:
                raise rule["raises"]
            if rule["returns"] is not _UNSET:
                return rule["returns"]
        handler = getattr(self, f"_handle_{req_type}", None)
        if handler is None:
            self.unexpected.append(req_type)
            raise OBSSDKRequestError(req_type, 204, "Unknown request type")
        return handler(payload or {})

    def disconnect(self):
        self.disconnected = True

    def _no_scene(self, req_type):
        return OBSSDKRequestError(req_type, 600, "No scene was found by the requested name.")

    def _handle_GetCurrentProgramScene(self, payload):
        return {"currentProgramSceneName": self.current}

    def _handle_GetSceneList(self, payload):
        scenes = [{"sceneName": name, "sceneIndex": i} for i, name in enumerate(self.scenes)]
        return {"currentProgramSceneName": self.current, "scenes": scenes}

    def _handle_GetSceneItemList(self, payload):
        scene = payload.get("sceneName")
        if scene not in self.scenes:
            raise self._no_scene("GetSceneItemList")
        items = [
            {"sourceName": source, "sceneItemId": item["id"], "sceneItemEnabled": item["enabled"]}
            for source, item in self.scenes[scene].items()
        ]
        return {"sceneItems": items}

    def _handle_SetSceneItemEnabled(self, payload):
        scene = payload.get("sceneName")
        if scene not in self.scenes:
            raise self._no_scene("SetSceneItemEnabled")
        for item in self.scenes[scene].values():
            if item["id"] == payload.get("sceneItemId"):
                item["enabled"] = bool(payload["sceneItemEnabled"])
                return None
        raise OBSSDKRequestError("SetSceneItemEnabled", 600, "No scene item was found.")


class FakeKeyboard:
    """Key state the way GetAsyncKeyState reports it: whether a key is down,
    and whether it was pressed since it was last asked about."""

    def __init__(self):
        self._down = set()
        self._pressed = set()

    def hold(self, key):
        code = HOTKEY_TO_VK[key]
        self._down.add(code)
        self._pressed.add(code)

    def release(self, key):
        self._down.discard(HOTKEY_TO_VK[key])

    def tap(self, key):
        """Down and back up between two polls, as when the worker is busy."""
        self._pressed.add(HOTKEY_TO_VK[key])

    def read(self, code):
        pressed = code in self._pressed
        self._pressed.discard(code)
        return code in self._down, pressed


class SteppableWallClock:
    """Lets a test move the wall clock the worker sees, forwards or back, the
    way a DST change or a clock correction does."""

    def __init__(self, monkeypatch):
        self.offset = timedelta(0)
        clock = self

        class _SteppedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + clock.offset

        monkeypatch.setattr(overlay_module, "datetime", _SteppedDatetime)


class _Wait:
    def __init__(self, ready, what, timeout):
        self.ready = ready
        self.what = what
        self.deadline = time.monotonic() + timeout


class Session:
    """Runs MapHideService._run on the calling thread against a FakeObs and a
    FakeKeyboard, advancing the scenario each time the worker polls the keys.

    `connect` is a FakeObs (every connection attempt reaches it) or a list
    consumed one attempt at a time - an exception in the list is raised, and
    a list that runs dry is refused as a wrong password so the worker gives up
    instead of retrying forever.
    """

    def __init__(self, monkeypatch, cfg, connect, *, max_seconds=15.0):
        self.cfg = cfg
        self.service = MapHideService()
        self.keyboard = FakeKeyboard()
        self.events = []
        self._connect = connect
        self._gen = None
        self._wait = None
        self._failure = None
        self._ticks = 0
        self._show_code = cfg.show_vk_codes()[0]
        self._started = time.monotonic()
        self._max_seconds = max_seconds

        monkeypatch.setattr(overlay_module, "connect_obs", self._connect_obs)
        monkeypatch.setattr(overlay_module, "configure_logging", lambda enabled: None)
        monkeypatch.setattr(hotkeys_module, "read_key_state", self._read_key)
        # Short enough that tests don't sit through real retry and rescan
        # waits, long enough to stay ordered the way they are in use.
        monkeypatch.setattr(overlay_module, "RECONNECT_TICK", 0.001)
        monkeypatch.setattr(overlay_module, "RECONNECT_DELAY", 0.001)
        monkeypatch.setattr(overlay_module, "SCENE_REFRESH_INTERVAL", 0.02)
        monkeypatch.setattr(overlay_module, "MISSING_SOURCE_RECHECK_INTERVAL", 0.05)

    # --- waiting -------------------------------------------------------------

    def until(self, condition, what="the condition", timeout=3.0):
        return _Wait(condition, what, timeout)

    def ticks(self, count):
        target = self._ticks + count
        return _Wait(lambda: self._ticks >= target, f"{count} polls", 5.0)

    def pause(self, seconds):
        end = time.monotonic() + seconds
        return _Wait(lambda: time.monotonic() >= end, f"{seconds}s to pass", seconds + 5.0)

    def drain(self):
        while not self.service.events.empty():
            self.events.append(self.service.events.get_nowait())
        return self.events

    def messages(self, kind=None):
        return [e["message"] for e in self.drain() if kind is None or e["kind"] == kind]

    def saw(self, text, kind=None):
        return any(text in message for message in self.messages(kind))

    # --- running -------------------------------------------------------------

    def run(self, scenario=None):
        self._gen = scenario(self) if scenario is not None else None
        self.service._running = True
        self.service._run(self.cfg)
        self.drain()
        if self._failure is not None:
            raise AssertionError(self._failure)
        return self.events

    def _connect_obs(self, host, port, password):
        target = self._connect
        if isinstance(target, FakeObs):
            client = target
        elif target:
            client = target.pop(0)
            if isinstance(client, Exception):
                raise client
        else:
            raise ObsAuthError("The scripted connections ran out.")
        client.connections += 1
        client.disconnected = False
        return client

    def _read_key(self, code):
        if code == self._show_code:
            self._ticks += 1
            self._advance()
        return self.keyboard.read(code)

    def _stop_with(self, failure=None):
        if failure is not None and self._failure is None:
            self._failure = failure
        self.service.stop()

    def _advance(self):
        if self.service._stop_event.is_set():
            return
        if time.monotonic() - self._started > self._max_seconds:
            self._stop_with(f"The session ran longer than {self._max_seconds}s.")
            return
        if self._gen is None:
            return
        while True:
            if self._wait is not None:
                if not self._wait.ready():
                    if time.monotonic() > self._wait.deadline:
                        self._stop_with(f"Timed out waiting for {self._wait.what}.")
                    return
                self._wait = None
            try:
                self._wait = next(self._gen)
            except StopIteration:
                self._stop_with()
                return
            except AssertionError as exc:
                self._stop_with(f"The scenario failed: {exc}")
                return
