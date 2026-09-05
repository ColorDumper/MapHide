"""Tests for the OBS transport wrapper: connect timeout split and error mapping."""

import pytest
from obsws_python.error import OBSSDKError, OBSSDKTimeoutError

from maphide import obs
from maphide.obs import (
    CONNECT_TIMEOUT,
    REQUEST_TIMEOUT,
    ObsAuthError,
    ObsConnectionError,
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


@pytest.mark.parametrize(
    "raised, expected",
    [
        (OBSSDKTimeoutError("no answer"), ObsConnectionError),
        (OBSSDKError("identify failed"), ObsAuthError),
        (ConnectionRefusedError(61, "refused"), ObsConnectionError),
        (ValueError("garbage host"), ObsConnectionError),
    ],
)
def test_connect_failures_map_to_maphide_errors(monkeypatch, raised, expected):
    def boom(**kwargs):
        raise raised

    monkeypatch.setattr(obs, "ReqClient", boom)
    with pytest.raises(expected):
        connect_obs("10.0.0.2", 4455, "pw")
