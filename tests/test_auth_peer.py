"""Under CC_BIND_ALL a loopback Host is the local user only from a trusted socket peer (0407).

The Host header and every forwarding header are the caller's to write; only the socket peer is not.
"""

import asyncio
from collections.abc import MutableMapping
from typing import Any

import pytest
from fastapi.testclient import TestClient

from auth_rig import make_auth_rig
from command_center.api import create_app
from command_center.config import Settings

DOCKER_PEER = ("172.18.0.5", 40000)
LOCAL_ONLY = "/v1/settings"  # 200 for the local user, 401 for anyone needing a token


def _client(
    *, bind_all: bool, trusted: tuple[str, ...] = (), host: str = "localhost"
) -> TestClient:
    app = create_app(make_auth_rig().container, bind_all=bind_all, trusted_peers=trusted)
    return TestClient(app, base_url=f"http://{host}", client=DOCKER_PEER)


def test_bind_all_with_an_empty_list_treats_a_claimed_loopback_host_as_remote() -> None:
    assert _client(bind_all=True).get(LOCAL_ONLY).status_code == 401


def test_the_same_request_is_local_when_the_peer_is_listed() -> None:
    assert _client(bind_all=True, trusted=("172.18.0.5",)).get(LOCAL_ONLY).status_code == 200


def test_a_cidr_entry_trusts_its_members() -> None:
    assert _client(bind_all=True, trusted=("172.18.0.0/16",)).get(LOCAL_ONLY).status_code == 200


def test_another_peer_stays_remote_when_a_different_one_is_listed() -> None:
    assert _client(bind_all=True, trusted=("172.18.0.9",)).get(LOCAL_ONLY).status_code == 401


def test_without_bind_all_nothing_changes() -> None:
    assert _client(bind_all=False).get(LOCAL_ONLY).status_code == 200
    assert _client(bind_all=False, trusted=("10.0.0.1",)).get(LOCAL_ONLY).status_code == 200


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost:8765", "LOCALHOST."])
def test_every_loopback_spelling_of_host_is_demoted_from_an_untrusted_peer(host: str) -> None:
    assert _client(bind_all=True, host=host).get(LOCAL_ONLY).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Forwarded-For": "127.0.0.1"},
        {"X-Real-IP": "127.0.0.1"},
        {"Forwarded": "for=127.0.0.1"},
        {"X-Forwarded-Host": "localhost"},
    ],
)
def test_a_forwarding_header_claiming_loopback_does_not_make_an_untrusted_peer_local(
    headers: dict[str, str],
) -> None:
    assert _client(bind_all=True).get(LOCAL_ONLY, headers=headers).status_code == 401


def test_a_forwarding_header_still_demotes_a_trusted_peer() -> None:
    client = _client(bind_all=True, trusted=("172.18.0.5",))
    assert client.get(LOCAL_ONLY, headers={"X-Forwarded-For": "100.64.0.1"}).status_code == 401


def test_a_trusted_peer_cannot_reach_an_unlisted_host() -> None:
    client = _client(bind_all=True, trusted=("172.18.0.5",), host="evil.example")
    assert client.get(LOCAL_ONLY).status_code == 400


def test_the_web_ui_is_closed_to_an_untrusted_peer_claiming_loopback() -> None:
    assert _client(bind_all=True).get("/settings").status_code == 401


def _status_for_client(client: object, trusted: tuple[str, ...]) -> int:
    """Run one raw ASGI request whose scope["client"] is `client` and return the status."""
    app = create_app(make_auth_rig().container, bind_all=True, trusted_peers=trusted)
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": LOCAL_ONLY,
        "raw_path": LOCAL_ONLY.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost")],
        "client": client,
        "server": ("localhost", 8765),
        "state": {},
    }
    asyncio.run(app(scope, receive, send))
    return int(next(m for m in sent if m["type"] == "http.response.start")["status"])


def test_a_request_with_no_peer_address_is_remote_under_bind_all() -> None:
    everyone = ("0.0.0.0/0", "::/0")
    assert _status_for_client(None, everyone) == 401
    assert _status_for_client(("172.18.0.5", 1), everyone) == 200


def test_the_setting_defaults_to_an_empty_list_and_parses_a_comma_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CC_TRUSTED_PEERS", raising=False)
    assert Settings().trusted_peers == ()
    monkeypatch.setenv("CC_TRUSTED_PEERS", "172.18.0.1, 192.168.65.0/24,")
    assert Settings().trusted_peers == ("172.18.0.1", "192.168.65.0/24")


def test_a_garbage_trusted_peer_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CC_TRUSTED_PEERS", "172.18.0.1,not-an-ip")
    with pytest.raises(ValueError, match="trusted_peers"):
        Settings()


def test_build_app_passes_bind_all_and_the_peer_list_to_the_auth_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from command_center.app import build_app  # noqa: PLC0415

    monkeypatch.delenv("CC_TRUSTED_PEERS", raising=False)
    app = build_app(Settings(bind_all=True))
    assert app.user_middleware[0].kwargs["bind_all"] is True
    assert app.user_middleware[0].kwargs["trusted_peers"] == ()
    listed = build_app(Settings(bind_all=True, trusted_peers=("172.18.0.5",)))
    assert listed.user_middleware[0].kwargs["trusted_peers"] == ("172.18.0.5",)
