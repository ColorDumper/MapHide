"""Talking to OBS over the WebSocket, and telling its failures apart."""

import json
import logging
import sys

try:
    import websocket
    from obsws_python import ReqClient
    from obsws_python.error import OBSSDKError, OBSSDKRequestError, OBSSDKTimeoutError
except ImportError as e:
    print("ERROR: obsws_python not installed or import failed:", e)
    print("Install in your venv: pip install obsws-python")
    sys.exit(1)

logging.getLogger("obsws_python").setLevel(logging.CRITICAL)

# Bounds the socket during connect and the identify handshake. A streaming PC
# that accepts the connection but never answers holds the worker for this long.
CONNECT_TIMEOUT = 3
# Bounds every request after connect (see connect_obs). Short, so a streaming PC
# that stalls mid-session is caught in about a second rather than in 3s steps -
# the worker then drops the link and reconnects.
REQUEST_TIMEOUT = 1
OBS_BAD_PASSWORD = "Failed to connect to OBS. The OBS WebSocket password appears to be incorrect."
OBS_UNREACHABLE = "Failed to connect to OBS. Make sure OBS is open and the WebSocket server is available."
OBS_SETTINGS_WRONG = "Failed to connect to OBS. Check that OBS is open and your connection settings are correct."
OBS_LINK_LOST = "The connection to OBS was lost. Reconnect after OBS is available again."
OBS_READ_REFUSED = "OBS returned an error while reading the current scene."
OBS_WRITE_REFUSED = "OBS returned an error while updating the overlay source."
OBS_OVERLAY_MAY_REMAIN = "MapHide stopped, but lost the connection before it could hide the overlay. Check OBS."


class ObsConnectionError(Exception):
    pass


class ObsAuthError(ObsConnectionError):
    pass


# What a lost link looks like by the time it reaches MapHide: obsws-python's own
# timeout wrapper, websocket-client's closed/timeout family, the socket errors
# underneath them, and - because OBS signals a rejected session by closing the
# socket - an empty read that json cannot parse.
OBS_TRANSPORT_ERRORS = (
    OBSSDKTimeoutError,
    websocket.WebSocketException,
    OSError,
    json.JSONDecodeError,
)


def connect_obs(host, port, password, timeout=CONNECT_TIMEOUT):
    # The try holds a single third-party call, so a broad final clause cannot mask
    # a mistake of ours - there is no MapHide logic inside it to go wrong.
    try:
        client = ReqClient(host=host, port=port, password=password, timeout=timeout)
    except OBSSDKTimeoutError as exc:
        raise ObsConnectionError(OBS_UNREACHABLE) from exc
    except OBSSDKError as exc:
        # OBS closes the socket on a bad password rather than answering, so
        # obsws-python reports it as a failed identify.
        raise ObsAuthError(OBS_BAD_PASSWORD) from exc
    except OSError as exc:
        raise ObsConnectionError(OBS_UNREACHABLE) from exc
    except Exception as exc:
        raise ObsConnectionError(OBS_SETTINGS_WRONG) from exc

    # The connect timeout above is still on the socket as its read timeout. Drop
    # it to REQUEST_TIMEOUT for the requests that follow. This reaches past
    # obsws-python's public API; if a version bump moves the socket, the guard
    # leaves the longer timeout in place rather than failing the connection.
    try:
        client.base_client.ws.settimeout(REQUEST_TIMEOUT)
    except (AttributeError, OSError):
        pass
    return client


def find_scene_item_id(client, scene_name, source_name):
    try:
        resp = client.send("GetSceneItemList", {"sceneName": scene_name}, raw=True)
    except OBSSDKRequestError as exc:
        raise ObsConnectionError(OBS_READ_REFUSED) from exc
    except OBS_TRANSPORT_ERRORS as exc:
        raise ObsConnectionError(OBS_LINK_LOST) from exc

    items = resp.get("sceneItems") or resp.get("scene_items") or []
    for item in items:
        name = item.get("sourceName") or item.get("source_name")
        item_id = item.get("sceneItemId") or item.get("scene_item_id")
        if name == source_name:
            return item_id
    return None


def get_current_scene(client):
    try:
        resp = client.send("GetCurrentProgramScene", raw=True)
    except OBSSDKRequestError as exc:
        raise ObsConnectionError(OBS_READ_REFUSED) from exc
    except OBS_TRANSPORT_ERRORS as exc:
        raise ObsConnectionError(OBS_LINK_LOST) from exc
    return resp.get("currentProgramSceneName") or resp.get("current_program_scene_name")


def set_scene_item_enabled(client, scene_name, scene_item_id, enabled):
    payload = {
        "sceneName": scene_name,
        "sceneItemId": scene_item_id,
        "sceneItemEnabled": bool(enabled),
    }
    # The one call that can strand the overlay on screen, and the only one that
    # had no error handling at all.
    try:
        return client.send("SetSceneItemEnabled", payload, raw=True)
    except OBSSDKRequestError as exc:
        raise ObsConnectionError(OBS_WRITE_REFUSED) from exc
    except OBS_TRANSPORT_ERRORS as exc:
        raise ObsConnectionError(OBS_LINK_LOST) from exc


def find_overlay_scene_items(client, source_name):
    try:
        resp = client.send("GetSceneList", raw=True)
    except OBSSDKRequestError as exc:
        raise ObsConnectionError(OBS_READ_REFUSED) from exc
    except OBS_TRANSPORT_ERRORS as exc:
        raise ObsConnectionError(OBS_LINK_LOST) from exc

    scenes = resp.get("scenes") or resp.get("scene_list") or []
    scene_items = {}
    for scene in scenes:
        scene_name = scene.get("sceneName") or scene.get("scene_name")
        if scene_name:
            scene_items[scene_name] = find_scene_item_id(client, scene_name, source_name)
    return scene_items


def disconnect_obs(client):
    try:
        client.disconnect()
    except (websocket.WebSocketException, OSError):
        # Closing a socket the far end has already dropped.
        pass


def set_overlay_enabled(client, scene_items, current_scene_name, enabled):
    # The overlay covers one thing - whether the map is open - so it belongs in the
    # same state in every scene that carries the source. Keeping them all in step
    # means an OBS scene transition needs no work from MapHide and cannot catch the
    # incoming scene uncovered. Current scene first, since it is the one on screen.
    ordered = [name for name in (current_scene_name,) if name in scene_items]
    ordered += [name for name in scene_items if name != current_scene_name]
    for scene_name in ordered:
        scene_item_id = scene_items[scene_name]
        if scene_item_id is not None:
            set_scene_item_enabled(client, scene_name, scene_item_id, enabled)
