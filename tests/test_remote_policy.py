"""What a paired phone may do: read, and POST /v1/sync. Every route is classified here.

The route table below is checked against the app's real routes in both directions, so adding a
route without deciding what a phone may do with it fails this file (decision 0060).
"""

from typing import Any

import pytest

from auth_rig import REMOTE, AuthRig, make_auth_rig
from command_center.api.policy import REMOTE_WRITES, refusal_status, remote_may_call
from route_support import Endpoint, walk

# What the table can say about a route for a phone holding a valid access token.
READ = "read"  # a GET that changes nothing: served
SYNC = "sync"  # the one write a phone is allowed: served
OPEN = "open"  # reachable with no token at all (how a phone gets one)
HIDDEN = "hidden"  # the policy lets it through; the page's own check answers a phone 404
DENIED = "denied"  # 403, and the handler never runs

POLICY: dict[tuple[str, str], str] = {
    # health and pairing: no token needed
    ("GET", "/v1/health"): OPEN,
    ("POST", "/v1/pair"): OPEN,
    ("POST", "/v1/pair/refresh"): OPEN,
    # reads
    ("GET", "/v1/events"): READ,
    ("GET", "/v1/agenda/{period}"): READ,
    ("GET", "/v1/attention"): READ,
    ("GET", "/v1/settings"): READ,
    ("GET", "/v1/summary"): READ,
    ("GET", "/"): READ,
    ("GET", "/week"): READ,
    ("GET", "/month"): READ,
    ("GET", "/settings"): READ,
    ("GET", "/settings/{source}/status"): READ,
    ("GET", "/pair"): HIDDEN,
    ("GET", "/static"): READ,
    ("GET", "/openapi.json"): READ,
    ("GET", "/docs"): READ,
    ("GET", "/docs/oauth2-redirect"): READ,
    ("GET", "/redoc"): READ,
    # the one write
    ("POST", "/v1/sync"): SYNC,
    # everything else is refused for a phone
    ("GET", "/v1/devices"): READ,
    ("DELETE", "/v1/devices/{device_id}"): DENIED,
    ("PUT", "/v1/settings/{source}"): DENIED,
    ("DELETE", "/v1/settings/{source}"): DENIED,
    ("PUT", "/settings/{source}"): DENIED,
    ("DELETE", "/settings/{source}"): DENIED,
    ("POST", "/pair/code"): DENIED,
}


@pytest.fixture
def rig() -> AuthRig:
    return make_auth_rig()


@pytest.fixture
def endpoints(rig: AuthRig) -> list[Endpoint]:
    return list(walk(rig.app.routes))


def test_the_walker_sees_every_part_of_the_app(endpoints: list[Endpoint]) -> None:
    templates = {e.template for e in endpoints}
    assert {"/v1/sync", "/v1/devices", "/settings/{source}", "/static", "/docs"} <= templates


def test_every_route_is_classified(endpoints: list[Endpoint]) -> None:
    unclassified = [e for e in endpoints if (e.method, e.template) not in POLICY]
    assert unclassified == [], (
        f"decide what a paired phone may do with {unclassified}, then add it to POLICY and, if it "
        "is a write the phone may call, to api/policy.py"
    )


def test_the_table_names_no_route_that_does_not_exist(endpoints: list[Endpoint]) -> None:
    real = {(e.method, e.template) for e in endpoints}
    assert set(POLICY) - real == set()


def test_only_sync_is_a_write_a_phone_may_make() -> None:
    assert {("POST", "/v1/sync")} == REMOTE_WRITES


def test_the_table_agrees_with_the_policy_function_for_every_route(
    endpoints: list[Endpoint],
) -> None:
    for endpoint in endpoints:
        row = POLICY[(endpoint.method, endpoint.template)]
        if row == OPEN:
            continue
        assert remote_may_call(endpoint.method, endpoint.path) is (row in {READ, SYNC, HIDDEN}), (
            endpoint
        )


def _call(client: Any, endpoint: Endpoint, headers: dict[str, str]) -> Any:  # noqa: ANN401
    # JSON for every write, so a refusal can only be the policy, never the content type.
    kwargs: dict[str, Any] = {"headers": headers}
    if endpoint.method in {"POST", "PUT"} and not endpoint.path.startswith("/v1/pair"):
        kwargs["json"] = {"credentials": {"token": "fake-canvas-token-00000000"}}
    return client.request(endpoint.method, endpoint.path, **kwargs)


def test_a_phone_is_refused_every_denied_route_and_the_handler_does_not_run(
    rig: AuthRig, endpoints: list[Endpoint]
) -> None:
    phone = rig.pair_phone()
    other = rig.pair_phone("Tablet")
    headers = rig.bearer(phone.access_token)
    denied = [e for e in endpoints if POLICY[(e.method, e.template)] == DENIED]
    assert denied, "the table denies something"
    for endpoint in denied:
        # the revoke path names a real device, so a handler that ran would show
        target = Endpoint(
            endpoint.method, endpoint.template.replace("{device_id}", other.device_id)
        )
        response = _call(rig.remote, target, headers)
        if endpoint.template.startswith("/v1/"):
            assert response.status_code == 403, (endpoint, response.text)
            assert response.json() == {"detail": "A paired phone may not do this"}
        else:  # the web UI's own routes do not exist for a phone
            assert response.status_code == 404, (endpoint, response.text)
            assert response.json() == {"detail": "Not Found"}
    assert len(rig.service.devices()) == 2  # nothing revoked


def test_a_denied_settings_write_stores_nothing_and_a_denied_pair_code_mints_nothing(
    rig: AuthRig,
) -> None:
    phone = rig.pair_phone()  # consumes its own pairing token
    headers = rig.bearer(phone.access_token)
    body = {"credentials": {"token": "fake-canvas-token-00000000"}}
    before = rig.local.get("/v1/settings").json()
    assert rig.store.pairing_hashes() == set()
    assert rig.remote.put("/v1/settings/canvas", json=body, headers=headers).status_code == 403
    assert rig.remote.delete("/v1/settings/canvas", headers=headers).status_code == 403
    assert rig.remote.post("/pair/code", headers=headers).status_code == 404
    assert rig.local.get("/v1/settings").json() == before
    assert rig.store.pairing_hashes() == set()


def test_a_phone_may_read_and_sync(rig: AuthRig, endpoints: list[Endpoint]) -> None:
    phone = rig.pair_phone()
    headers = rig.bearer(phone.access_token)
    served = [e for e in endpoints if POLICY[(e.method, e.template)] in {READ, SYNC}]
    for endpoint in served:
        response = _call(rig.remote, endpoint, headers)
        assert response.status_code not in {401, 403, 415}, (endpoint, response.status_code)
        assert response.status_code < 500, (endpoint, response.status_code)
        if endpoint.template != "/static" and not endpoint.template.startswith("/v1/"):
            # a web page the phone may read must be served, not the middleware's JSON 404
            assert response.status_code == 200, (endpoint, response.status_code)
    assert rig.remote.post("/v1/sync", headers=headers).status_code == 200


def test_the_pairing_page_is_hidden_from_a_phone_by_the_page_itself(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    assert rig.remote.get("/pair", headers=rig.bearer(phone.access_token)).status_code == 404
    assert rig.local.get("/pair").status_code == 200


def test_open_routes_need_no_token_from_the_tailnet(rig: AuthRig) -> None:
    assert rig.remote.get("/v1/health").status_code == 200
    assert (
        rig.remote.post("/v1/pair", json={"pairing_token": "fake-unknown-0000"}).status_code == 401
    )
    assert rig.remote.post("/v1/pair/refresh", json={"refresh_token": "fake-x"}).status_code == 401


def test_without_a_token_a_denied_route_is_401_not_403(rig: AuthRig) -> None:
    # The refusal must not tell an unauthenticated caller which routes exist.
    assert rig.remote.put("/v1/settings/canvas", json={"credentials": {}}).status_code == 401
    assert rig.remote.get("/v1/devices").status_code == 401


def test_loopback_is_unchanged_for_every_route(rig: AuthRig, endpoints: list[Endpoint]) -> None:
    for endpoint in endpoints:
        if POLICY[(endpoint.method, endpoint.template)] != DENIED:
            continue
        response = _call(rig.local, endpoint, {})
        # a web write may still be 403 for its CSRF token; what must be absent is the phone rule
        assert "paired phone" not in response.text, (endpoint, response.text)
        assert response.status_code != 401, (endpoint, response.text)


def test_the_web_ui_still_connects_and_deletes_on_loopback(rig: AuthRig) -> None:
    headers = rig.csrf()
    form = {"token": "fake-canvas-token-00000000"}
    assert rig.local.put("/settings/canvas", data=form, headers=headers).status_code == 200
    assert rig.local.delete("/settings/canvas", headers=headers).status_code == 200
    assert rig.local.post("/pair/code", headers=headers).status_code == 200


def test_a_loopback_host_behind_a_proxy_is_a_phone_too(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    headers = {**rig.bearer(phone.access_token), "X-Forwarded-For": "100.64.0.9"}
    assert rig.local.delete("/v1/devices/no-such-device", headers=headers).status_code == 403
    assert rig.local.get("/v1/settings", headers=headers).status_code == 200


def test_a_websocket_from_a_phone_is_closed_by_default(rig: AuthRig) -> None:
    from starlette.testclient import TestClient  # noqa: PLC0415
    from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

    phone = rig.pair_phone()
    client = TestClient(rig.app, base_url=f"https://{REMOTE}")
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("/v1/anything", headers=rig.bearer(phone.access_token)),
    ):
        pass
    assert closed.value.code == 1008


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/v1/settings", True),
        ("HEAD", "/v1/settings", True),
        ("OPTIONS", "/v1/settings", True),
        ("POST", "/v1/sync", True),
        ("GET", "/v1/devices", True),
        ("GET", "/v1/devices/abc", True),
        ("DELETE", "/v1/devices/abc", False),
        ("PUT", "/v1/settings/canvas", False),
        ("DELETE", "/v1/settings/canvas", False),
        ("POST", "/pair/code", False),
        ("POST", "/v1/sync/", False),  # only the exact path is allowed
        ("PATCH", "/v1/events", False),
        ("POST", "/v1/events", False),
        ("get", "/v1/events", False),  # methods are upper case on the wire
        ("TRACE", "/v1/events", False),
        ("POST", "/v1/SYNC", False),
    ],
)
def test_the_policy_function(method: str, path: str, expected: bool) -> None:  # noqa: FBT001
    assert remote_may_call(method, path) is expected


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/v1/devices/abc", 403),
        ("/v1/settings/canvas", 403),
        ("/pair/code", 404),
        ("/settings/x", 404),
    ],
)
def test_the_api_refuses_with_403_and_the_web_ui_with_404(path: str, status: int) -> None:
    assert refusal_status(path) == status
