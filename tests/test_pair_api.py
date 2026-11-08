"""POST /v1/pair, POST /v1/pair/refresh, GET /v1/devices, DELETE /v1/devices/{id}."""

import logging
from typing import Any

import pytest

from auth_rig import AuthRig, make_auth_rig
from command_center.core.pairing import FAILURE_LIMIT, LOCK_DURATION, PAIRING_TTL

DEVICE_FIELDS = {"id", "name", "created_at", "last_seen_at"}
TOKEN_FIELDS = {
    "device_id",
    "token_type",
    "access_token",
    "access_expires_at",
    "refresh_token",
}


@pytest.fixture
def rig() -> AuthRig:
    return make_auth_rig()


def pair(rig: AuthRig, token: str, name: str | None = "Pixel") -> Any:  # noqa: ANN401
    return rig.remote.post("/v1/pair", json={"pairing_token": token, "device_name": name})


def test_a_pairing_token_is_exchanged_for_credentials(rig: AuthRig) -> None:
    offer = rig.service.start_pairing()
    response = pair(rig, offer.token)
    body = response.json()
    assert response.status_code == 200
    assert set(body) == TOKEN_FIELDS
    assert body["token_type"] == "bearer"  # noqa: S105
    assert response.headers["cache-control"] == "no-store"


def test_the_access_token_from_pairing_opens_the_api(rig: AuthRig) -> None:
    body = pair(rig, rig.service.start_pairing().token).json()
    response = rig.remote.get("/v1/settings", headers=rig.bearer(body["access_token"]))
    assert response.status_code == 200


def test_a_pairing_token_cannot_be_replayed(rig: AuthRig) -> None:
    offer = rig.service.start_pairing()
    assert pair(rig, offer.token).status_code == 200
    replay = pair(rig, offer.token)
    assert replay.status_code == 401
    assert offer.token not in replay.text


def test_an_expired_pairing_token_is_refused(rig: AuthRig) -> None:
    offer = rig.service.start_pairing()
    rig.clock.advance(PAIRING_TTL)
    assert pair(rig, offer.token).status_code == 401


def test_a_wrong_token_and_a_used_token_get_the_same_answer(rig: AuthRig) -> None:
    offer = rig.service.start_pairing()
    pair(rig, offer.token)
    used = pair(rig, offer.token)
    wrong = pair(rig, "fake-wrong-token-0000000000")
    assert (used.status_code, used.json()) == (wrong.status_code, wrong.json())


def test_five_failures_lock_pairing_with_a_retry_after(rig: AuthRig) -> None:
    offer = rig.service.start_pairing()
    for _ in range(FAILURE_LIMIT):
        assert pair(rig, "fake-wrong-token-0000000000").status_code == 401
    locked = pair(rig, offer.token)
    assert locked.status_code == 429
    assert locked.headers["retry-after"] == str(int(LOCK_DURATION.total_seconds()))
    assert rig.service.devices() == []


def test_pairing_works_again_once_the_lock_ends(rig: AuthRig) -> None:
    offer = rig.service.start_pairing()
    for _ in range(FAILURE_LIMIT):
        pair(rig, "fake-wrong-token-0000000000")
    rig.clock.advance(LOCK_DURATION)
    assert pair(rig, offer.token).status_code == 200


def test_pairing_is_reachable_from_loopback_too(rig: AuthRig) -> None:
    offer = rig.service.start_pairing()
    response = rig.local.post("/v1/pair", json={"pairing_token": offer.token})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"pairing_token": ""},
        {"pairing_token": "x" * 129},
        {"pairing_token": 12345},
        {"pairing_token": "fake-token-0000000000", "device_name": "n" * 101},
        {"pairing_token": "fake-token-0000000000", "extra": "field"},
    ],
)
def test_a_malformed_pair_request_is_422_and_echoes_nothing(
    rig: AuthRig, body: dict[str, Any]
) -> None:
    response = rig.remote.post("/v1/pair", json=body)
    assert response.status_code == 422
    assert '"input"' not in response.text
    assert "x" * 129 not in response.text
    assert "fake-token-0000000000" not in response.text


def test_a_form_post_cannot_pair(rig: AuthRig) -> None:
    # A cross-site <form> can only send form encodings; the route accepts JSON alone.
    offer = rig.service.start_pairing()
    response = rig.remote.post("/v1/pair", data={"pairing_token": offer.token})
    assert response.status_code == 422
    assert rig.service.devices() == []


def test_a_text_plain_post_cannot_pair(rig: AuthRig) -> None:
    offer = rig.service.start_pairing()
    response = rig.remote.post(
        "/v1/pair",
        content=f'{{"pairing_token": "{offer.token}"}}',
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 422
    assert rig.service.devices() == []


def test_refresh_returns_a_new_pair_and_retires_the_old(rig: AuthRig) -> None:
    first = pair(rig, rig.service.start_pairing().token).json()
    response = rig.remote.post("/v1/pair/refresh", json={"refresh_token": first["refresh_token"]})
    second = response.json()
    assert response.status_code == 200
    assert set(second) == TOKEN_FIELDS
    assert second["refresh_token"] != first["refresh_token"]
    assert second["device_id"] == first["device_id"]
    old = rig.remote.get("/v1/settings", headers=rig.bearer(first["access_token"]))
    assert old.status_code == 401
    new = rig.remote.get("/v1/settings", headers=rig.bearer(second["access_token"]))
    assert new.status_code == 200


def test_reusing_a_rotated_refresh_credential_revokes_the_device(rig: AuthRig) -> None:
    first = pair(rig, rig.service.start_pairing().token).json()
    second = rig.remote.post(
        "/v1/pair/refresh", json={"refresh_token": first["refresh_token"]}
    ).json()
    reuse = rig.remote.post("/v1/pair/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401
    assert rig.local.get("/v1/devices").json() == []
    after = rig.remote.get("/v1/settings", headers=rig.bearer(second["access_token"]))
    assert after.status_code == 401


def test_refresh_failures_lock_refreshing(rig: AuthRig) -> None:
    for _ in range(FAILURE_LIMIT):
        rig.remote.post(
            "/v1/pair/refresh", json={"refresh_token": "fake-unknown-refresh-credential"}
        )
    locked = rig.remote.post(
        "/v1/pair/refresh", json={"refresh_token": "fake-unknown-refresh-credential"}
    )
    assert locked.status_code == 429
    assert "retry-after" in locked.headers


def test_devices_lists_each_phone_without_any_secret(rig: AuthRig) -> None:
    phone = rig.pair_phone("Pixel 9")
    (device,) = rig.local.get("/v1/devices").json()
    assert set(device) == DEVICE_FIELDS
    assert device["name"] == "Pixel 9"
    assert device["id"] == phone.device_id
    assert phone.access_token not in str(device)
    assert phone.refresh_token not in str(device)


def test_devices_needs_a_token_from_the_tailnet(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    assert rig.remote.get("/v1/devices").status_code == 401
    assert rig.remote.get("/v1/devices", headers=rig.bearer(phone.access_token)).status_code == 200


def test_deleting_a_device_ends_its_tokens_at_once(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    assert rig.local.delete(f"/v1/devices/{phone.device_id}").status_code == 204
    assert rig.local.get("/v1/devices").json() == []
    assert rig.remote.get("/v1/settings", headers=rig.bearer(phone.access_token)).status_code == 401
    refresh = rig.remote.post("/v1/pair/refresh", json={"refresh_token": phone.refresh_token})
    assert refresh.status_code == 401


def test_deleting_an_unknown_device_is_404(rig: AuthRig) -> None:
    assert rig.local.delete("/v1/devices/fake-no-such-device").status_code == 404


def test_deleting_a_device_needs_a_token_from_the_tailnet(rig: AuthRig) -> None:
    phone = rig.pair_phone()
    assert rig.remote.delete(f"/v1/devices/{phone.device_id}").status_code == 401
    assert len(rig.service.devices()) == 1


def test_a_cross_origin_preflight_is_not_granted(rig: AuthRig) -> None:
    # Without CORS headers a browser will not send a cross-site DELETE or a JSON POST.
    phone = rig.pair_phone()
    headers = {
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "content-type",
    }
    response = rig.local.options(f"/v1/devices/{phone.device_id}", headers=headers)
    assert "access-control-allow-origin" not in response.headers
    assert response.status_code == 405
    assert len(rig.service.devices()) == 1


def test_without_pairing_wired_the_pair_routes_answer_404() -> None:
    from dataclasses import replace  # noqa: PLC0415

    from fastapi.testclient import TestClient  # noqa: PLC0415

    from command_center.api import create_app  # noqa: PLC0415

    rig = make_auth_rig()
    client = TestClient(
        create_app(replace(rig.container, pairing=None)), base_url="http://localhost"
    )
    assert (
        client.post("/v1/pair", json={"pairing_token": "fake-token-0000000000"}).status_code == 404
    )
    assert client.get("/v1/devices").status_code == 404


def test_the_flow_logs_no_token_or_credential(
    rig: AuthRig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    offer = rig.service.start_pairing()
    first = pair(rig, offer.token).json()
    second = rig.remote.post(
        "/v1/pair/refresh", json={"refresh_token": first["refresh_token"]}
    ).json()
    rig.remote.post("/v1/pair/refresh", json={"refresh_token": first["refresh_token"]})
    rig.remote.get("/v1/settings", headers=rig.bearer("fake-unknown-access-token"))
    pair(rig, "fake-wrong-token-0000000000")
    for secret in (
        offer.token,
        first["access_token"],
        first["refresh_token"],
        second["access_token"],
        second["refresh_token"],
        "fake-unknown-access-token",
        "fake-wrong-token-0000000000",
    ):
        assert secret not in caplog.text


def test_the_contract_lists_the_pairing_routes_and_the_bearer_scheme(rig: AuthRig) -> None:
    spec = rig.app.openapi()
    assert {"/v1/pair", "/v1/pair/refresh", "/v1/devices", "/v1/devices/{device_id}"} <= set(
        spec["paths"]
    )
    scheme = spec["components"]["securitySchemes"]["DeviceToken"]
    assert (scheme["type"], scheme["scheme"]) == ("http", "bearer")
    assert spec["paths"]["/v1/settings"]["get"]["security"] == [{"DeviceToken": []}]
    assert "security" not in spec["paths"]["/v1/pair"]["post"]
    assert "security" not in spec["paths"]["/v1/health"]["get"]
