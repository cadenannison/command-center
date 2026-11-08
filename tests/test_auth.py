"""install_auth: the Host header decides who needs a token; unknown hosts are refused."""

import pytest

from auth_rig import REMOTE, AuthRig, make_auth_rig
from command_center.core.pairing import ACCESS_TTL

OPEN_PATHS = {"/v1/health", "/v1/pair", "/v1/pair/refresh"}


@pytest.fixture
def rig() -> AuthRig:
    return make_auth_rig()


def test_loopback_needs_no_token(rig: AuthRig) -> None:
    assert rig.local.get("/v1/settings").status_code == 200


def test_the_loopback_address_needs_no_token_either(rig: AuthRig) -> None:
    from fastapi.testclient import TestClient  # noqa: PLC0415

    client = TestClient(rig.app, base_url="http://127.0.0.1:8765")
    assert client.get("/v1/settings").status_code == 200


def test_the_web_ui_stays_open_on_loopback(rig: AuthRig) -> None:
    assert rig.local.get("/settings").status_code == 200


def test_a_tailnet_host_without_a_token_is_refused(rig: AuthRig) -> None:
    response = rig.remote.get("/v1/settings")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"


def test_a_tailnet_host_with_a_valid_token_is_served(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    response = rig.remote.get("/v1/settings", headers=rig.bearer(phone.access_token))
    assert response.status_code == 200


def test_health_needs_no_token_from_the_tailnet(rig: AuthRig) -> None:
    assert rig.remote.get("/v1/health").json() == {"status": "ok"}


def test_the_bearer_scheme_name_is_case_insensitive(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    headers = {"Authorization": f"bearer {phone.access_token}"}
    assert rig.remote.get("/v1/settings", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "header",
    [
        "Bearer ",
        "Bearer",
        "Bearer fake-unknown-access-token",
        "Basic ZmFrZTpmYWtl",
        "fake-no-scheme-token-0000000000",
        "Bearer " + "a" * 100_000,
    ],
)
def test_a_malformed_or_unknown_credential_is_refused(rig: AuthRig, header: str) -> None:
    rig.pair_phone()
    response = rig.remote.get("/v1/settings", headers={"Authorization": header})
    assert response.status_code == 401


def test_an_expired_access_token_is_refused(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    rig.clock.advance(ACCESS_TTL)
    response = rig.remote.get("/v1/settings", headers=rig.bearer(phone.access_token))
    assert response.status_code == 401


def test_a_refresh_credential_is_not_accepted_as_an_access_token(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    response = rig.remote.get("/v1/settings", headers=rig.bearer(phone.refresh_token))
    assert response.status_code == 401


def test_two_authorization_headers_are_refused(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    headers = [
        ("Authorization", f"Bearer {phone.access_token}"),
        ("Authorization", "Bearer fake-unknown-access-token"),
    ]
    assert rig.remote.get("/v1/settings", headers=headers).status_code == 401


def test_a_revoked_device_is_refused_at_once(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    rig.service.revoke(phone.device_id)
    response = rig.remote.get("/v1/settings", headers=rig.bearer(phone.access_token))
    assert response.status_code == 401


def test_the_refusal_does_not_echo_the_token(rig: AuthRig) -> None:
    response = rig.remote.get("/v1/settings", headers=rig.bearer("fake-unknown-access-token"))
    assert "fake-unknown-access-token" not in response.text


@pytest.mark.parametrize(
    "host", ["evil.example", "localhost.evil.example", REMOTE + ".evil.example"]
)
def test_an_unknown_host_is_refused_even_with_a_valid_token(rig: AuthRig, host: str) -> None:
    from fastapi.testclient import TestClient  # noqa: PLC0415

    phone = rig.pair_phone()
    client = TestClient(rig.app, base_url=f"http://{host}")
    response = client.get("/v1/settings", headers=rig.bearer(phone.access_token))
    assert response.status_code == 400


def test_a_listed_host_with_a_port_is_matched_by_name(rig: AuthRig) -> None:
    from fastapi.testclient import TestClient  # noqa: PLC0415

    client = TestClient(rig.app, base_url=f"https://{REMOTE}:8443")
    assert client.get("/v1/settings").status_code == 401


@pytest.mark.parametrize(
    "proxy_header",
    [
        {"X-Forwarded-For": "100.64.0.9"},
        {"X-Forwarded-Host": REMOTE},
        {"Tailscale-User-Login": "someone@example.com"},
        {"Via": "1.1 serve"},
    ],
)
def test_a_loopback_host_behind_a_proxy_still_needs_a_token(
    rig: AuthRig, proxy_header: dict[str, str]
) -> None:
    # A tailnet peer can send "Host: localhost" through Serve; the proxy headers give it away.
    assert rig.local.get("/v1/settings", headers=proxy_header).status_code == 401


def test_a_loopback_host_behind_a_proxy_is_served_with_a_token(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    headers = {**rig.bearer(phone.access_token), "X-Forwarded-For": "100.64.0.9"}
    assert rig.local.get("/v1/settings", headers=headers).status_code == 200


def test_the_web_ui_is_closed_to_a_loopback_host_behind_a_proxy(rig: AuthRig) -> None:
    assert rig.local.get("/settings", headers={"X-Forwarded-For": "100.64.0.9"}).status_code == 401


WEB_REQUESTS = [
    ("GET", "/"),
    ("GET", "/week"),
    ("GET", "/month"),
    ("GET", "/settings"),
    ("GET", "/settings/canvas/status"),
    ("PUT", "/settings/canvas"),
    ("DELETE", "/settings/canvas"),
    ("GET", "/pair"),
    ("POST", "/pair/code"),
    ("GET", "/static/vendor/htmx.min.js"),
    ("GET", "/docs"),
    ("GET", "/redoc"),
    ("GET", "/openapi.json"),
]


def _concrete(path: str) -> str:
    return (
        path.replace("{device_id}", "fake-device")
        .replace("{source}", "canvas")
        .replace("{period}", "day")
    )


def _documented_requests(rig: AuthRig) -> list[tuple[str, str]]:
    paths: dict[str, dict[str, object]] = rig.app.openapi()["paths"]
    return [(method.upper(), _concrete(path)) for path, ops in paths.items() for method in ops]


def test_every_route_but_the_open_ones_needs_a_token_from_the_tailnet(rig: AuthRig) -> None:
    requests = [
        (method, path)
        for method, path in [*_documented_requests(rig), *WEB_REQUESTS]
        if path not in OPEN_PATHS
    ]
    assert len(requests) > 20  # the API, the web pages, the static files and the docs
    for method, path in requests:
        response = rig.remote.request(method, path)
        assert response.status_code == 401, f"{method} {path} was served without a token"


def test_an_unknown_path_from_the_tailnet_is_401_not_404(rig: AuthRig) -> None:
    assert rig.remote.get("/v1/no-such-route").status_code == 401


def test_without_pairing_wired_a_tailnet_host_is_refused_everywhere() -> None:
    from dataclasses import replace  # noqa: PLC0415

    from fastapi.testclient import TestClient  # noqa: PLC0415

    from command_center.api import create_app  # noqa: PLC0415

    rig = make_auth_rig()
    app = create_app(replace(rig.container, pairing=None), remote_hosts=(REMOTE,))
    client = TestClient(app, base_url=f"https://{REMOTE}")
    assert (
        client.get("/v1/settings", headers=rig.bearer("fake-any-access-token-00000")).status_code
        == 401
    )
    assert client.get("/v1/health").status_code == 200


def test_no_remote_host_listed_means_the_tailnet_name_is_an_unknown_host() -> None:
    rig = make_auth_rig(remote_hosts=())
    assert rig.remote.get("/v1/health").status_code == 400
