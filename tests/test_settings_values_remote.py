"""Plain setting values (Apple ID, Canvas URL, location) go to loopback only (decision 0106)."""

from auth_rig import AuthRig, make_auth_rig

TOKEN = "fake-canvas-token-ABCD1234"  # noqa: S105  (fake- test value)
URL = "https://fake-school.example"


def connected_rig() -> AuthRig:
    rig = make_auth_rig()
    put = rig.local.put(
        "/v1/settings/canvas", json={"credentials": {"token": TOKEN, "base_url": URL}}
    )
    assert put.json()["ok"] is True
    return rig


def test_loopback_gets_the_plain_values() -> None:
    rig = connected_rig()

    (item,) = rig.local.get("/v1/settings").json()

    assert item["values"] == {"base_url": URL}


def test_a_paired_phone_gets_neither_values_nor_key_status() -> None:
    rig = connected_rig()
    phone = rig.pair_phone()

    response = rig.remote.get("/v1/settings", headers=rig.bearer(phone.access_token))

    assert response.status_code == 403  # off the phone allowlist (decision 0412)
    assert response.json() == {"detail": "A paired phone may not do this"}
    assert URL not in response.text
    assert "1234" not in response.text


def test_a_loopback_host_with_a_proxy_header_is_treated_as_a_phone() -> None:
    rig = connected_rig()
    phone = rig.pair_phone()
    headers = {**rig.bearer(phone.access_token), "X-Forwarded-For": "100.64.0.9"}

    response = rig.local.get("/v1/settings", headers=headers)

    assert response.status_code == 403  # a phone: off the allowlist (decision 0412)
    assert URL not in response.text
