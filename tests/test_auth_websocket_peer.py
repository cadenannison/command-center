"""A websocket claiming a loopback Host is remote under CC_BIND_ALL unless its peer is trusted.

A probe app sits behind the middleware, so the tests see whether the request got through and as
whom, not just a close code (a local websocket to an unknown route closes with 1008 as well).
"""

import asyncio
from collections.abc import MutableMapping
from typing import Any

from fastapi import FastAPI

from command_center.api.auth import LOOPBACK_STATE_KEY, DeviceAuthMiddleware

PEER = ("172.18.0.5", 40000)


class _Probe:
    def __init__(self) -> None:
        self.reached_as_loopback: list[bool] = []

    async def __call__(self, scope: Any, _receive: Any, send: Any) -> None:  # noqa: ANN401
        self.reached_as_loopback.append(bool(scope.get("state", {}).get(LOOPBACK_STATE_KEY)))
        await send({"type": "websocket.close", "code": 1000})


def _connect(
    *,
    bind_all: bool,
    trusted: tuple[str, ...],
    client: tuple[str, int] | None = PEER,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> tuple[_Probe, list[MutableMapping[str, Any]]]:
    probe = _Probe()
    middleware = DeviceAuthMiddleware(
        probe, FastAPI(), (), bind_all=bind_all, trusted_peers=trusted
    )
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "websocket.connect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    scope: dict[str, Any] = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": "/v1/ws",
        "raw_path": b"/v1/ws",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost"), *extra_headers],
        "client": client,
        "server": ("localhost", 8765),
        "subprotocols": [],
        "state": {},
    }
    asyncio.run(middleware(scope, receive, send))
    return probe, sent


def test_an_untrusted_peer_claiming_loopback_is_closed_before_the_app() -> None:
    probe, sent = _connect(bind_all=True, trusted=())
    assert probe.reached_as_loopback == []
    assert sent == [{"type": "websocket.close", "code": 1008}]


def test_a_forwarding_header_does_not_help_an_untrusted_peer() -> None:
    probe, sent = _connect(
        bind_all=True, trusted=(), extra_headers=((b"x-forwarded-for", b"127.0.0.1"),)
    )
    assert probe.reached_as_loopback == []
    assert sent == [{"type": "websocket.close", "code": 1008}]


def test_a_websocket_with_no_peer_address_is_closed_before_the_app() -> None:
    probe, _ = _connect(bind_all=True, trusted=("0.0.0.0/0", "::/0"), client=None)
    assert probe.reached_as_loopback == []


def test_a_trusted_peer_reaches_the_app_as_the_local_user() -> None:
    probe, _ = _connect(bind_all=True, trusted=("172.18.0.5",))
    assert probe.reached_as_loopback == [True]


def test_without_bind_all_the_peer_is_not_looked_at() -> None:
    probe, _ = _connect(bind_all=False, trusted=())
    assert probe.reached_as_loopback == [True]
