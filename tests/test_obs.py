"""Tests for the OBS transport wrapper: connect timeout split and error mapping."""

import pytest
from obsws_python.error import OBSSDKError, OBSSDKRequestError, OBSSDKTimeoutError

from maphide import obs
from maphide.obs import (
    CONNECT_TIMEOUT,
    REQUEST_TIMEOUT,
    ObsAuthError,
    ObsConnectionError,
    ObsUnreachableError,
    connect_obs,
)


class FakeWs:
    def __init__(self):
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value


class FakeReqClient:
    def __init__(self, host, port, password, timeout):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self.base_client = type("Base", (), {})()
        self.base_client.ws = FakeWs()


def test_request_timeout_is_shorter_than_the_connect_timeout():
    assert REQUEST_TIMEOUT < CONNECT_TIMEOUT


def test_connect_holds_the_long_timeout_then_shortens_the_socket(monkeypatch):
    monkeypatch.setattr(obs, "ReqClient", FakeReqClient)
    client = connect_obs("10.0.0.2", 4455, "pw")
    assert client.timeout == CONNECT_TIMEOUT
    assert client.base_client.ws.timeout == REQUEST_TIMEOUT


def test_shortening_the_socket_is_best_effort(monkeypatch):
    class Grumpy(FakeReqClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

            def refuse(_value):
                raise OSError("socket already gone")

            self.base_client.ws.settimeout = refuse

    monkeypatch.setattr(obs, "ReqClient", Grumpy)
    assert connect_obs("10.0.0.2", 4455, "pw") is not None


class RaisingClient:
    def __init__(self, raised):
        self.raised = raised

    def send(self, *args, **kwargs):
        raise self.raised


class ReplyingClient:
    def __init__(self, reply):
        self.reply = reply

    def send(self, *args, **kwargs):
        return self.reply


READS_AND_WRITES = [
    lambda client: obs.find_scene_item_id(client, "Scene", "Overlay"),
    lambda client: obs.get_current_scene(client),
    lambda client: obs.set_scene_item_enabled(client, "Scene", 1, True),
    lambda client: obs.find_overlay_scene_items(client, "Overlay"),
]
READS = [READS_AND_WRITES[0], READS_AND_WRITES[1], READS_AND_WRITES[3]]


@pytest.mark.parametrize("call", READS_AND_WRITES)
def test_a_refused_request_is_told_apart_from_a_lost_link(call):
    refused = OBSSDKRequestError("SomeRequest", 600, "No scene was found")
    with pytest.raises(obs.ObsRequestRefused):
        call(RaisingClient(refused))

    with pytest.raises(ObsConnectionError) as lost:
        call(RaisingClient(OBSSDKTimeoutError("no answer")))
    assert not isinstance(lost.value, obs.ObsRequestRefused)


@pytest.mark.parametrize("call", READS_AND_WRITES)
@pytest.mark.parametrize("raised", [KeyError("requestStatus"), TypeError("unexpected frame")])
def test_a_reply_that_cannot_be_read_is_a_connection_error(call, raised):
    with pytest.raises(ObsConnectionError) as error:
        call(RaisingClient(raised))
    assert not isinstance(error.value, obs.ObsRequestRefused)


@pytest.mark.parametrize("call", READS)
def test_a_missing_reply_body_is_a_connection_error(call):
    with pytest.raises(ObsConnectionError):
        call(ReplyingClient(None))


@pytest.mark.parametrize(
    "raised, expected",
    [
        (OBSSDKTimeoutError("no answer"), ObsUnreachableError),
        (OBSSDKError("identify failed"), ObsAuthError),
        (ConnectionRefusedError(61, "refused"), ObsUnreachableError),
        (ValueError("garbage host"), ObsConnectionError),
    ],
)
def test_connect_failures_map_to_maphide_errors(monkeypatch, raised, expected):
    def boom(**kwargs):
        raise raised

    monkeypatch.setattr(obs, "ReqClient", boom)
    with pytest.raises(expected):
        connect_obs("10.0.0.2", 4455, "pw")
