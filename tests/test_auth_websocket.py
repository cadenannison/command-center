"""A websocket the auth check refuses is closed cleanly, not left to an ASGI error."""

import pytest
from starlette.websockets import WebSocketDisconnect

from auth_rig import make_auth_rig


def test_a_remote_websocket_without_a_token_is_closed_with_policy_violation() -> None:
    rig = make_auth_rig()
    with pytest.raises(WebSocketDisconnect) as closed, rig.remote.websocket_connect("/v1/ws"):
        pass
    assert closed.value.code == 1008


def test_a_websocket_to_an_unlisted_host_is_closed() -> None:
    rig = make_auth_rig()
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        rig.remote.websocket_connect("/v1/ws", headers={"Host": "evil.example"}),
    ):
        pass
    assert closed.value.code == 1008
