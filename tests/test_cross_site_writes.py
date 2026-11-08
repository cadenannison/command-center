"""A browser-marked cross-site write to /v1 is 403 whatever it carries (decision 0060)."""

import pytest

from auth_rig import REMOTE, AuthRig, make_auth_rig
from command_center.api.policy import is_cross_site
from route_support import SAFE_METHODS, walk

LOCAL_ORIGIN = "http://localhost"
EVIL = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}


@pytest.fixture
def rig() -> AuthRig:
    return make_auth_rig()


def test_a_bodiless_no_cors_post_from_another_site_cannot_start_a_sync(rig: AuthRig) -> None:
    # fetch(url, {method: "POST", mode: "no-cors"}): no body, no Content-Type, no preflight.
    response = rig.local.post("/v1/sync", headers=EVIL)
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-site requests are not allowed"}
    assert rig.container.sync.state("canvas") is None  # the handler never ran
    assert rig.local.post("/v1/sync").status_code == 200
    assert rig.container.sync.state("canvas") is not None  # the same call without the headers does


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": "http://localhost.evil.example"},
        {"Origin": "http://localhost:9999"},
    ],
)
def test_either_header_alone_is_enough_on_every_v1_write(
    rig: AuthRig, headers: dict[str, str]
) -> None:
    writes = [
        e
        for e in walk(rig.app.routes)
        if e.template.startswith("/v1/") and e.method not in SAFE_METHODS
    ]
    assert writes
    for endpoint in writes:
        response = rig.local.request(endpoint.method, endpoint.path, headers=headers)
        assert response.status_code == 403, (endpoint, response.status_code)


def test_the_pairing_routes_refuse_a_cross_site_post_before_the_limiter_sees_it(
    rig: AuthRig,
) -> None:
    for _ in range(10):
        response = rig.remote.post("/v1/pair", json={"pairing_token": "fake-x-0000"}, headers=EVIL)
        assert response.status_code == 403
    offer = rig.service.start_pairing()
    ok = rig.remote.post("/v1/pair", json={"pairing_token": offer.token})
    assert ok.status_code == 200  # the limiter was never charged


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-origin", "Origin": LOCAL_ORIGIN},
        {"Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "none"},
        {"Origin": LOCAL_ORIGIN},
        {},
    ],
)
def test_the_web_ui_and_native_clients_are_not_refused(
    rig: AuthRig, headers: dict[str, str]
) -> None:
    assert rig.local.post("/v1/sync", headers=headers).status_code == 200


def test_the_phone_app_sends_neither_header_and_may_sync(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    response = rig.remote.post("/v1/sync", headers=rig.bearer(phone.access_token))
    assert response.status_code == 200


def test_a_matching_origin_through_the_tailnet_name_is_not_refused(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    headers = {**rig.bearer(phone.access_token), "Origin": f"https://{REMOTE}"}
    assert rig.remote.post("/v1/sync", headers=headers).status_code == 200


def test_reads_and_the_web_ui_forms_are_not_checked(rig: AuthRig) -> None:
    assert rig.local.get("/v1/settings", headers=EVIL).status_code == 200
    # the HTMX form posts are not under /v1 and have their own CSRF token
    form = {"token": "fake-canvas-token-00000000"}
    response = rig.local.put("/settings/canvas", data=form, headers={**rig.csrf(), **EVIL})
    assert response.status_code == 200


def test_a_cross_site_write_from_a_phone_without_a_token_is_still_401(rig: AuthRig) -> None:
    assert rig.remote.post("/v1/sync", headers=EVIL).status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "headers", "expected"),
    [
        ("POST", "/v1/sync", [(b"sec-fetch-site", b"cross-site")], True),
        ("POST", "/v1/sync", [(b"Sec-Fetch-Site", b"Cross-Site")], True),
        ("POST", "/v1/sync", [(b"origin", b"http://a"), (b"host", b"a")], False),
        ("POST", "/v1/sync", [(b"origin", b"http://a"), (b"host", b"b")], True),
        ("POST", "/v1/sync", [(b"origin", b"http://a")], True),  # no Host to match
        ("GET", "/v1/settings", [(b"sec-fetch-site", b"cross-site")], False),
        ("POST", "/settings/x", [(b"sec-fetch-site", b"cross-site")], False),
        ("POST", "/v1/sync", [], False),
    ],
)
def test_the_cross_site_check(
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]],
    expected: bool,  # noqa: FBT001
) -> None:
    assert is_cross_site(method, path, headers) is expected


def test_a_repeated_host_header_is_read_the_first_time_like_the_host_rule() -> None:
    headers = [(b"host", b"a"), (b"host", b"b"), (b"origin", b"http://a")]
    assert is_cross_site("POST", "/v1/sync", headers) is False
    assert (
        is_cross_site(
            "POST", "/v1/sync", [(b"host", b"b"), (b"host", b"a"), (b"origin", b"http://a")]
        )
        is True
    )
