"""Write routes under /v1 take JSON only: any other content type is 415 (decision 0060).

A cross-site <form> or a no-cors fetch can send a form encoding, text/plain, or a body with no
content type, without a CORS preflight. Refusing those keeps such a request from reaching a write.
"""

from typing import Any

import pytest

from auth_rig import AuthRig, make_auth_rig
from command_center.api.policy import is_json_content_type
from route_support import SAFE_METHODS, Endpoint, walk

# These two read a JSON body model and already answer 422 to a form or text/plain post, so no
# handler can run (tests/test_pair_api.py). They stay 422 (decision 0060, item 5).
EXEMPT = {("POST", "/v1/pair"), ("POST", "/v1/pair/refresh")}


@pytest.fixture
def rig() -> AuthRig:
    return make_auth_rig()


def write_routes(rig: AuthRig) -> list[Endpoint]:
    found = [
        e
        for e in walk(rig.app.routes)
        if e.template.startswith("/v1/")
        and e.method not in SAFE_METHODS
        and (e.method, e.template) not in EXEMPT
    ]
    assert found, "the app has /v1 write routes"
    return found


def test_the_walker_finds_the_known_write_routes(rig: AuthRig) -> None:
    assert {(e.method, e.template) for e in write_routes(rig)} == {
        ("POST", "/v1/sync"),
        ("PUT", "/v1/settings/{source}"),
        ("DELETE", "/v1/settings/{source}"),
        ("DELETE", "/v1/devices/{device_id}"),
        ("POST", "/v1/items"),
        ("PATCH", "/v1/items/{item_id}"),
        ("DELETE", "/v1/items/{item_id}"),
        ("POST", "/v1/items/{item_id}/done"),
        ("DELETE", "/v1/items/{item_id}/done"),
        ("PUT", "/v1/items/{item_id}/notes"),
        ("DELETE", "/v1/items/{item_id}/notes"),
    }


def test_a_form_post_is_415_on_every_write_route(rig: AuthRig) -> None:
    for endpoint in write_routes(rig):
        response = rig.local.request(endpoint.method, endpoint.path, data={"token": "fake-x-0000"})
        assert response.status_code == 415, endpoint
        assert response.json() == {"detail": "Content-Type must be application/json"}


def test_a_multipart_post_is_415_on_every_write_route(rig: AuthRig) -> None:
    for endpoint in write_routes(rig):
        response = rig.local.request(
            endpoint.method, endpoint.path, files={"token": (None, "fake-x-0000")}
        )
        assert response.status_code == 415, endpoint


def test_a_text_plain_body_is_415_on_every_write_route(rig: AuthRig) -> None:
    for endpoint in write_routes(rig):
        response = rig.local.request(
            endpoint.method,
            endpoint.path,
            content='{"credentials": {"token": "fake-x-0000"}}',
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 415, endpoint


def test_a_json_body_with_no_content_type_is_415_on_every_write_route(rig: AuthRig) -> None:
    # `new Blob([json])` posts with no Content-Type, and FastAPI would parse it as JSON.
    for endpoint in write_routes(rig):
        request = rig.local.build_request(
            endpoint.method, endpoint.path, content='{"credentials": {}}'
        )
        request.headers.pop("content-type", None)
        assert rig.local.send(request).status_code == 415, endpoint


def test_two_content_type_headers_are_415(rig: AuthRig) -> None:
    headers = [("Content-Type", "application/json"), ("Content-Type", "text/plain")]
    response = rig.local.put("/v1/settings/canvas", content="{}", headers=headers)
    assert response.status_code == 415


def test_a_bodiless_write_with_no_content_type_is_served(rig: AuthRig) -> None:
    # The phone and the web UI call POST /v1/sync and the DELETEs with no body at all.
    assert rig.local.post("/v1/sync").status_code == 200
    assert rig.local.delete("/v1/settings/canvas").status_code == 200
    assert rig.local.delete("/v1/devices/no-such-device").status_code == 404


def test_a_bodiless_write_that_names_a_form_type_is_415(rig: AuthRig) -> None:
    response = rig.local.post(
        "/v1/sync", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert response.status_code == 415


@pytest.mark.parametrize(
    "content_type", ["application/json", "Application/JSON", "application/json; charset=utf-8"]
)
def test_json_is_accepted_whatever_its_case_or_parameters(rig: AuthRig, content_type: str) -> None:
    response = rig.local.put(
        "/v1/settings/canvas",
        content='{"credentials": {"token": "fake-canvas-token-00000000"}}',
        headers={"Content-Type": content_type},
    )
    assert response.status_code == 200


def test_a_refused_write_never_reaches_the_handler(rig: AuthRig) -> None:
    rig.local.put(
        "/v1/settings/canvas",
        content='{"credentials": {"token": "fake-canvas-token-00000000"}}',
        headers={"Content-Type": "text/plain"},
    )
    assert rig.local.get("/v1/settings").json() == [
        {"source": "canvas", "keys": {}, "sync": None, "values": {}}
    ]


def test_a_phone_that_may_sync_is_still_held_to_json(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    response = rig.remote.post("/v1/sync", data={"a": "b"}, headers=rig.bearer(phone.access_token))
    assert response.status_code == 415


def test_a_phone_with_no_token_is_401_before_the_content_type_is_looked_at(rig: AuthRig) -> None:
    assert rig.remote.post("/v1/sync", data={"a": "b"}).status_code == 401


def test_the_web_ui_forms_are_not_affected(rig: AuthRig) -> None:
    # /settings/... is the HTMX page, protected by its own CSRF token and form-encoded by design.
    response = rig.local.put(
        "/settings/canvas", data={"token": "fake-canvas-token-00000000"}, headers=rig.csrf()
    )
    assert response.status_code == 200


def test_reads_are_not_checked(rig: AuthRig) -> None:
    assert rig.local.get("/v1/settings", headers={"Content-Type": "text/plain"}).status_code == 200


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("application/json", True),
        (" application/json ", True),
        ("APPLICATION/JSON;charset=utf-8", True),
        ("application/json ; charset=utf-8", True),
        ("application/jsonp", False),
        ("application/vnd.api+json", False),
        ("text/plain", False),
        ("application/x-www-form-urlencoded", False),
        ("multipart/form-data; boundary=x", False),
        ("", False),
        ("application/json, text/plain", False),
    ],
)
def test_the_content_type_check(value: str, expected: bool) -> None:  # noqa: FBT001
    assert is_json_content_type(value) is expected


def _typeless_post(client: Any, path: str, body: str) -> Any:  # noqa: ANN401
    request = client.build_request("POST", path, content=body)
    request.headers.pop("content-type", None)
    return client.send(request)


@pytest.mark.parametrize("path", ["/v1/pair", "/v1/pair/refresh"])
def test_a_typeless_body_is_415_on_the_pairing_routes_too(rig: AuthRig, path: str) -> None:
    # A no-cors fetch with a typeless Blob would otherwise reach the handler and spend a failure
    # of the global limiter.
    response = _typeless_post(rig.remote, path, '{"pairing_token": "x", "refresh_token": "x"}')
    assert response.status_code == 415
    assert rig.service.devices() == []


@pytest.mark.parametrize("path", ["/v1/pair", "/v1/pair/refresh"])
def test_two_content_type_headers_are_415_on_the_pairing_routes_too(
    rig: AuthRig, path: str
) -> None:
    headers = [("Content-Type", "application/json"), ("Content-Type", "text/plain")]
    assert rig.remote.post(path, content="{}", headers=headers).status_code == 415


def test_the_pairing_routes_keep_answering_a_declared_form_type_with_422(rig: AuthRig) -> None:
    assert rig.remote.post("/v1/pair", data={"pairing_token": "fake-x-0000"}).status_code == 422
